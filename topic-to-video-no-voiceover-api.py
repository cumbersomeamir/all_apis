from flask import Flask, request, jsonify, send_file
import openai
import time
import os
import uuid
from moviepy.editor import *
import googleapiclient.discovery
import yt_dlp
import boto3
import nltk
from nltk.corpus import stopwords
from collections import Counter
import re
import requests

nltk.download("stopwords")
stop_words = set(stopwords.words("english"))

app = Flask(__name__)

# Retrieve API keys from environment variables
openai.api_key = os.getenv("OPENAI_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")
external_ip = os.getenv("EXTERNAL_IP")

# Initialize OpenAI client
client = openai.OpenAI()

# S3 client initialization
s3_client = boto3.client(
    's3',
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_key,
    region_name=aws_region
)


def upload_to_s3(file_path, unique_id):
    s3_key = f"videos/{unique_id}.mp4"
    try:
        s3_client.upload_file(file_path, s3_bucket_name, s3_key)
        s3_url = f"https://{s3_bucket_name}.s3.{aws_region}.amazonaws.com/{s3_key}"
        return s3_url
    except Exception as e:
        print(f"Error uploading to S3: {str(e)}")
        return None
        
def generate_text(topic, num_frames):
    completion = client.chat.completions.create(
      model="gpt-4o-mini",
      messages=[
        {"role": "system", "content": "You are a super creative non-fiction story writer"},
        {"role": "user", "content": "Your job is to generate "+ str(num_frames) + " single-line sentences which will be used in a video story about the topic "+ str(topic)+ ". Please give a numbered list only like 1. 2. 3. and so on."}
      ]
    )
    response = completion.choices[0].message.content
    sentences = re.split(r'\d+\.\s', response)[1:]
    cleaned_sentences = [sentence.strip().replace("\n", "") for sentence in sentences]
    return cleaned_sentences
    
def extract_subject(text):
    completion = client.chat.completions.create(
      model="gpt-4o-mini",
      messages=[
        {"role": "system", "content": "You only return subject of the sentence"},
        {"role": "user", "content": f"You simply return the subject of the sentence {text} and nothing else"}
      ]
    )
    response = completion.choices[0].message.content
    return response

def youtube_search(query, max_results=5):
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)
    request = youtube.search().list(
        part="snippet",
        q=str(query) + " B roll",
        maxResults=max_results,
        type="video",
    )
    response = request.execute()
    
    if not response['items']:
        print("No videos found, trying a broader search.")
        request = youtube.search().list(
            part="snippet",
            q="general " + query,
            maxResults=max_results + 5
        )
        response = request.execute()

    video_links = []
    for item in response['items']:
        video_title = item['snippet']['title']
        video_id = item['id']['videoId']
        video_url = f"https://www.youtube.com/watch?v={video_id}"
        video_links.append(video_url)
        print(f"Found video: {video_title} ({video_url})")

    return video_links

def download_video(url, output_folder, unique_id):
    try:
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        
        ydl_opts = {
            'format': 'mp4',
            'outtmpl': os.path.join(output_folder, f'{unique_id}.%(ext)s'),
            'ignoreerrors': True,
            'merge_output_format': 'mp4',
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([url])
        
        print(f"Downloaded video from: {url}")
    
    except Exception as e:
        print(f"Error downloading video: {str(e)}")


def search_and_download(query, max_results=1, output_folder="downloaded_videos", unique_id=None):
    video_urls = youtube_search(query, max_results)
    for url in video_urls:
        download_video(url, output_folder, unique_id)

def download_video_for_text(text, unique_id):
    keyword = extract_subject(text)
    print("The keyword is ", keyword)
    search_and_download(keyword, max_results=1, output_folder="downloaded_videos", unique_id=unique_id)

def create_video(clip_info):
    video_folder = "downloaded_videos"
    output_folder = "generated_video"

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    clips = []

    for info in clip_info:
        unique_id = info['unique_id']
        duration = info['duration']

        video_file = None
        for file in os.listdir(video_folder):
            if file.startswith(unique_id):
                video_file = os.path.join(video_folder, file)
                break

        if video_file is None:
            print(f"No video file found for {unique_id}")
            continue

        video_clip = VideoFileClip(video_file)
        video_clip = video_clip.set_duration(duration)

        clips.append(video_clip)

    final_clip = concatenate_videoclips(clips, method='compose')

    output_path = os.path.join(output_folder, "final_video.mp4")
    final_clip.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac')

    print(f"Video saved as {output_path}")


@app.route('/create-video-no-voiceover', methods=['POST'])
def video_story():
    data = request.get_json()
    topic = data.get('topic')
    num_frames = data.get('num_frames')

    if not topic or not num_frames:
        return jsonify({'error': 'Please provide both topic and num_frames'}), 400

    try:
        num_frames = int(num_frames)
    except ValueError:
        return jsonify({'error': 'num_frames must be an integer'}), 400

    generated_array = generate_text(topic, num_frames)
    
    clip_info = []
    
    for text in generated_array:
        unique_id = str(uuid.uuid4())
        download_video_for_text(text, unique_id)
        clip_info.append({
            'unique_id': unique_id,
            'duration': 5  # Default to 5 seconds or adjust as needed
        })

    create_video(clip_info)

    video_file_path = os.path.join("generated_video", "final_video.mp4")
    
    s3_url = upload_to_s3(video_file_path, "final_video")

    if s3_url:
        response = requests.post(
            f"http://{external_ip}:7020/caption_video",
            headers={"Content-Type": "application/json"},
            json={"video_url": s3_url}
        )

        if response.status_code == 200:
            captioned_video_url = response.json().get("video_url")
            return jsonify({"video_url": captioned_video_url}), 200
        else:
            return jsonify({"error": "Failed to send video to caption endpoint"}), 500

        
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=7035)
