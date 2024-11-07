from flask import Flask, request, jsonify, send_file
import openai
import time
import os
import uuid
from elevenlabs import VoiceSettings
from elevenlabs.client import ElevenLabs
import requests
import json
import re
from pydub import AudioSegment
from moviepy.editor import *
import googleapiclient.discovery
import yt_dlp
import boto3
import nltk
from nltk.corpus import stopwords
from collections import Counter

nltk.download("stopwords")
stop_words = set(stopwords.words("english"))

app = Flask(__name__)

# Retrieve API keys from environment variables
openai.api_key = os.getenv("OPENAI_API_KEY")
api_key = os.getenv("ELEVENLABS_API_KEY")
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")

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
        {"role": "user", "content": "Your job is to generate "+ str(num_frames) + " single-line sentences which will be used in a voiceover about the topic "+ str(topic)+ ". Please give a numbered list only like 1. 2. 3. and so on."}
      ]
    )
    response = completion.choices[0].message.content
    # Extract sentences from the response
    sentences = re.split(r'\d+\.\s', response)[1:]  # Split by numbered list, and ignore the first empty element
    # Clean up sentences by removing any newline characters
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
    

def submit_text(generated_text):
    url = "https://api.elevenlabs.io/v1/text-to-speech/TlLWC5O5AUzxAg7ysFZB"
    headers = {
        "Content-Type": "application/json",
        "xi-api-key": api_key
    }
    data = {
        "text": generated_text,
        "voice_settings": {
            "stability": 0.1,
            "similarity_boost": 0
        }
    }

    response = requests.post(url, headers=headers, data=json.dumps(data))
    
    if response.status_code == 200:
        print("Successfully submitted to elevenlabs")
    else:
        print(f"Error {response.status_code}: {response.content}")

def get_history_item_id():
    client = ElevenLabs(
        api_key=api_key,
    )
    resp = client.history.get_all(
        page_size=1,
        voice_id="TlLWC5O5AUzxAg7ysFZB",
    )
    history_item_id = resp.history[0].history_item_id
    return history_item_id

def create_audiofile(history_item_id, unique_id):
    output_folder = "generated_audio"
    client = ElevenLabs(
        api_key=api_key,
    )
    
    # Getting the audio generator
    audio_generator = client.history.get_audio(
        history_item_id=str(history_item_id),
    )
    
    # Filename with unique_id
    filename = f"{unique_id}.mp3"
    
    # Full path to save the file
    file_path = os.path.join(output_folder, filename)
    
    # Ensure the output folder exists
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    # Saving the audio data to a file
    with open(file_path, "wb") as audio_file:
        for chunk in audio_generator:
            audio_file.write(chunk)

    # Load the saved audio file to get its duration
    audio = AudioSegment.from_file(file_path)
    duration = len(audio) / 1000  # Duration in seconds

    print(f"{file_path} saved successfully, duration: {duration} seconds")
    
    return duration

def youtube_search(query, max_results=5):
    youtube = googleapiclient.discovery.build("youtube", "v3", developerKey=YOUTUBE_API_KEY)

    try:
        # Perform the initial search with stricter criteria
        request = youtube.search().list(
            part="snippet",
            q=f"{query} B roll",
            maxResults=max_results,
            type="video",

        )
        response = request.execute()

        # Broaden the search if no results are found
        if not response['items']:
            print("No specific B-roll videos found; broadening search.")
            request = youtube.search().list(
                part="snippet",
                q=query,  # Broaden search to the general query
                maxResults=max_results + 5,
                type="video"
            )
            response = request.execute()

        # Extract video URLs from search results
        video_links = []
        for item in response['items']:
            video_id = item['id']['videoId']
            video_url = f"https://www.youtube.com/watch?v={video_id}"
            video_links.append(video_url)
            print(f"Found video: {item['snippet']['title']} ({video_url})")

        return video_links

    except Exception as e:
        print(f"Error searching YouTube API: {str(e)}")
        return []

def download_video(url, output_folder, unique_id):
    try:
        if not os.path.exists(output_folder):
            os.makedirs(output_folder)
        
        # Adjusting yt-dlp options to download any available format and not fail
        ydl_opts = {
            'format': 'mp4',  # Download any available mp4 format
            'outtmpl': os.path.join(output_folder, f'{unique_id}.%(ext)s'),  # Save video with unique_id
            'ignoreerrors': True,  # Ignore any errors and continue
            'merge_output_format': 'mp4',  # Ensure output is mp4
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
    audio_folder = "generated_audio"
    video_folder = "downloaded_videos"
    output_folder = "generated_video"

    # Ensure the output folder exists
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    clips = []

    for info in clip_info:
        unique_id = info['unique_id']
        duration = info['duration']

        audio_file = os.path.join(audio_folder, f"{unique_id}.mp3")
        video_file = None

        # Find the video file with matching unique_id
        for file in os.listdir(video_folder):
            if file.startswith(unique_id):
                video_file = os.path.join(video_folder, file)
                break

        if video_file is None:
            print(f"No video file found for {unique_id}")
            continue

        # Load the audio clip
        audio_clip = AudioFileClip(audio_file)

        # Load the video clip
        video_clip = VideoFileClip(video_file)

        # If video is longer than audio, trim it
        if video_clip.duration > audio_clip.duration:
            video_clip = video_clip.subclip(0, audio_clip.duration)
        # If video is shorter than audio, extend it
        elif video_clip.duration < audio_clip.duration:
            # Calculate how much time to add
            time_to_add = audio_clip.duration - video_clip.duration
            # Freeze the last frame
            last_frame = video_clip.to_ImageClip(duration=time_to_add)
            video_clip = concatenate_videoclips([video_clip, last_frame])
        # Else, durations are equal, do nothing

        # Set the audio of the video clip to be the audio clip
        video_clip = video_clip.set_audio(audio_clip)

        # Ensure the video clip duration matches the audio duration exactly
        video_clip = video_clip.set_duration(audio_clip.duration)

        clips.append(video_clip)

    # Concatenate all clips
    final_clip = concatenate_videoclips(clips, method='compose')

    # Write the result to a file
    output_path = os.path.join(output_folder, "final_video.mp4")
    final_clip.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac')

    print(f"Video saved as {output_path}")





@app.route('/video-story', methods=['POST'])
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

    # Main execution
    generated_array = generate_text(topic, num_frames)
    
    clip_info = []
    
    for text in generated_array:
        unique_id = str(uuid.uuid4())
        submit_text(text)
        history_id = get_history_item_id()
        duration = create_audiofile(history_id, unique_id)
        download_video_for_text(text, unique_id)
        clip_info.append({
            'unique_id': unique_id,
            'duration': duration
        })

    # Create the video
    create_video(clip_info)

    # Path to the generated video
    video_file_path = os.path.join("generated_video", "final_video.mp4")
    
    # Upload the video to S3 and get the URL
    s3_url = upload_to_s3(video_file_path, "final_video")

    if s3_url:
        # Return the S3 URL in the response
        return jsonify({'video_url': s3_url}), 200
    else:
        return jsonify({'error': 'Failed to upload video to S3'}), 500
        
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=7004)

#Not specific enough 
