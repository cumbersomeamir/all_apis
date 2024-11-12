from flask import Flask, request, jsonify, send_file
import openai
import os
import uuid
from elevenlabs import ElevenLabs
import requests
import json
import re
from pydub import AudioSegment
from moviepy.editor import *
import shutil  # For deleting folder contents
import boto3
from botocore.exceptions import NoCredentialsError
from pprint import pprint

# AWS credentials and S3 bucket details from environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")  # e.g., 'us-east-1'
# API keys and endpoint
subscription_key = os.getenv("BING_SUBSCRIPTION_KEY")
backup_key = os.getenv("BING_BACKUP_KEY")  # Optional backup key
endpoint = "https://api.bing.microsoft.com/v7.0/search"
subscription_id = os.getenv("BING_SUBSCRIPTION_ID")
location = "Global"

app = Flask(__name__)

# API keys from environment variables
openai_api_key = os.getenv("OPENAI_API_KEY")
elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")

# Initialize the OpenAI client
client = openai.OpenAI(api_key=openai_api_key)


# Function to upload video to S3
def upload_file_to_s3(file_path, bucket_name, s3_filename):
    s3 = boto3.client('s3',
                      region_name=aws_region,
                      aws_access_key_id=aws_access_key,
                      aws_secret_access_key=aws_secret_key)

    try:
        s3.upload_file(file_path, bucket_name, s3_filename)
        s3_url = f"https://{bucket_name}.s3.{aws_region}.amazonaws.com/{s3_filename}"
        print(f"File uploaded to {s3_url}")
        return s3_url
    except FileNotFoundError:
        print("The file was not found")
        return None
    except NoCredentialsError:
        print("Credentials not available")
        return None


# Function to generate text
def generate_text(topic, num_frames):
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a super creative non-fiction story writer"},
            {"role": "user", "content": f"Your job is to generate {num_frames} single line very short sentences which will be used in a voiceover about the topic {topic}. Please give numbered list only like 1. 2. 3. and so on"}
        ]
    )
    response = completion.choices[0].message.content
    sentences = re.split(r'\d+\.\s', response)[1:]  # Split by numbered list, and ignore the first empty element
    cleaned_sentences = [sentence.strip().replace("\n", "") for sentence in sentences]
    
    return cleaned_sentences


# Function to submit text to ElevenLabs
def submit_text(generated_text):
    url = "https://api.elevenlabs.io/v1/text-to-speech/TlLWC5O5AUzxAg7ysFZB"
    headers = {
        "Content-Type": "application/json",
        "xi-api-key": elevenlabs_api_key
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
        print("Success:")
    else:
        print(f"Error {response.status_code}: {response.content}")

# Function to get history item ID from ElevenLabs
def get_history_item_id():
    client = ElevenLabs(api_key=elevenlabs_api_key)
    resp = client.history.get_all(page_size=1, voice_id="TlLWC5O5AUzxAg7ysFZB")
    history_item_id = resp.history[0].history_item_id
    return history_item_id

# Function to create audio file
def create_audiofile(history_item_id, durations):
    output_folder = "generated_audio_bing"
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)  # Ensure the folder is recreated if missing

    client = ElevenLabs(api_key=elevenlabs_api_key)
    audio_generator = client.history.get_audio(history_item_id=str(history_item_id))

    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}.mp3"
    file_path = os.path.join(output_folder, filename)

    with open(file_path, "wb") as audio_file:
        for chunk in audio_generator:
            audio_file.write(chunk)

    audio = AudioSegment.from_file(file_path)
    duration = len(audio) / 1000
    durations.append(duration)
    print(f"{file_path} saved successfully, duration: {duration} seconds")

# Function to create video from images and audio without motion
def create_video(durations, num_frames):
    audio_folder = "generated_audio_bing"
    image_folder = "queried_images_bing"
    output_folder = "generated_video_bing"

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)  # Ensure the folder is recreated if missing

    audio_files = sorted([f for f in os.listdir(audio_folder) if f.endswith('.mp3')])[:num_frames]
    image_files = sorted([f for f in os.listdir(image_folder) if f.endswith('.jpg')])[:num_frames]

    clips = []

    for audio_file, image_file, duration in zip(audio_files, image_files, durations):
        audio_clip = AudioFileClip(os.path.join(audio_folder, audio_file))
        image_clip = ImageClip(os.path.join(image_folder, image_file)).set_duration(duration)
        video_clip = image_clip.set_audio(audio_clip).resize(height=720).set_position("center")
        clips.append(video_clip)

    final_clip = concatenate_videoclips(clips, method="compose")
    output_path = os.path.join(output_folder, "final_video.mp4")
    final_clip.write_videofile(output_path, fps=24, codec='libx264', audio_codec='aac')

    print(f"Video saved as {output_path}")
    cleanup_folders([audio_folder, image_folder])
    return output_path


# Function to clean up folders after processing
def cleanup_folders(folders):
    for folder in folders:
        if os.path.exists(folder):
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                    elif os.path.isdir(file_path):
                        shutil.rmtree(file_path)
                except Exception as e:
                    print(f"Failed to delete {file_path}. Reason: {e}")
            print(f"Cleaned up {folder} folder")

def query_images(topic):
    mkt = 'en-US'
    params = {'q': topic}
    headers = {'Ocp-Apim-Subscription-Key': subscription_key}

    try:
        response = requests.get(endpoint, headers=headers, params=params)
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        print("Request failed:", e)

    response_dict = response.json() if hasattr(response, 'json') else response

    images = [item['image']['contentUrl'] for item in response_dict.get('news', {}).get('value', []) if 'image' in item]
    os.makedirs("queried_images_bing", exist_ok=True)  # Ensure the folder is recreated if missing

    for i, url in enumerate(images):
        try:
            img_data = requests.get(url).content
            with open(f"queried_images_bing/image_{i}.jpg", "wb") as img_file:
                img_file.write(img_data)
        except requests.RequestException as e:
            print(f"Failed to download {url}: {e}")

def add_captions_to_video(video_url):
    captioning_api_url = f"http://{os.getenv('EXTERNAL_IP')}:7020/caption_video"
    headers = {
        "Content-Type": "application/json"
    }
    data = {
        "video_url": video_url
    }
    response = requests.post(captioning_api_url, headers=headers, json=data)
    #print("Captioning API response:", response.json())

    
    if response.status_code == 200:
        captioned_video_url = response.json().get("video_url")
        return captioned_video_url
    else:
        print(f"Error {response.status_code}: {response.content}")
        return None


# Modify the Flask endpoint for image-story
@app.route('/image-story', methods=['POST'])
def image_story():
    # Clean up folders at the beginning of each request
    cleanup_folders(["generated_audio_bing", "queried_images_bing", "generated_video_bing"])
    data = request.get_json()
    topic = data.get('topic')
    num_frames = data.get('num_frames')

    if not topic or not num_frames:
        return jsonify({"error": "Please provide 'topic' and 'num_frames' in the request body"}), 400

    try:
        num_frames = int(num_frames)
    except ValueError:
        return jsonify({"error": "'num_frames' must be an integer"}), 400

    durations = []
    query_images(topic)
    generated_array = generate_text(topic, num_frames)
    
    for text in generated_array:
        submit_text(text)
        history_id = get_history_item_id()
        create_audiofile(history_id, durations)
    
    video_path = create_video(durations, num_frames)

    # Upload the video to S3
    unique_s3_filename = f"videos/{uuid.uuid4()}.mp4"
    s3_url = upload_file_to_s3(video_path, s3_bucket_name, unique_s3_filename)

    if s3_url:
        captioned_video_url = add_captions_to_video(s3_url)
        if captioned_video_url:
            return jsonify({"captioned_video_url": captioned_video_url}), 200
        else:
            return jsonify({"error": "Failed to add captions to video"}), 500
    else:
        return jsonify({"error": "Failed to upload video to S3"}), 500



# Flask app runs as usual
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=7023)
