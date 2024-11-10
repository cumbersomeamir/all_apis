from flask import Flask, request, jsonify
import openai
import os
import uuid
from elevenlabs import ElevenLabs
import requests, base64
import json
import re
from pydub import AudioSegment
from moviepy.editor import *
import shutil
import boto3
from botocore.exceptions import NoCredentialsError
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip

# API keys from environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")
openai_api_key = os.getenv("OPENAI_API_KEY")

# Initialize Flask app and OpenAI client
app = Flask(__name__)
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
        return s3_url
    except FileNotFoundError:
        return None
    except NoCredentialsError:
        return None

# Function to generate text
def generate_text(topic, num_prompts):
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a creative storytelling assistant. ..."},
            {"role": "user", "content": f"Your job is to generate {num_prompts} short sentences ..."}
        ]
    )
    response = completion.choices[0].message.content
    sentences = re.split(r'\d+\.\s', response)[1:]
    return [sentence.strip().replace("\n", "") for sentence in sentences]

# Function to create consistent images
def create_consistent_images(num_prompts, topic, subject_description, consistent_subjects, image_prompts):
    nvidia_api_key = os.getenv("NVIDIA_API_KEY")
    invoke_url = "https://ai.api.nvidia.com/v1/genai/nvidia/consistory"
    headers = {
        "Authorization": f"Bearer {nvidia_api_key}",
        "Accept": "application/json",
    }
    os.makedirs("consistent_images", exist_ok=True)

    for i in range(0, min(num_prompts, len(image_prompts)), 2):

        scene_prompt2 = image_prompts[i+1] if i+1 < len(image_prompts) else ""
        subject_tokens = consistent_subjects.split(",") if isinstance(consistent_subjects, str) else consistent_subjects

        payload = {
            "mode": 'init',
            "subject_prompt": subject_description,
            "subject_tokens": [token.strip() for token in subject_tokens],
            "subject_seed": 43,
            "style_prompt": "A photo of",
            "scene_prompt1": image_prompts[i],
            "scene_prompt2": scene_prompt2,
            "negative_prompt": "",
            "cfg_scale": 5,
            "same_initial_noise": False
        }
        response = requests.post(invoke_url, headers=headers, json=payload)
        response.raise_for_status()
        data = response.json()

        for idx, img_data in enumerate(data.get('artifacts', [])):
            img_base64 = img_data.get("base64")
            if img_base64:
                img_bytes = base64.b64decode(img_base64)
                with open(f'consistent_images/image_{i}_{idx}.jpg', "wb") as f:
                    f.write(img_bytes)

    return os.path.abspath("consistent_images")

# Function to create final video with audio
def create_final_video_with_audio(image_folder, output_folder, audio_file, final_video_name="final_video_with_audio.mp4", duration=2):
    os.makedirs(output_folder, exist_ok=True)
    images = sorted([os.path.join(image_folder, img) for img in os.listdir(image_folder) if img.endswith(('.jpg', '.jpeg', '.png'))])
    clips = [ImageClip(img_path).set_duration(duration) for img_path in images]
    final_clip = concatenate_videoclips(clips, method="compose")
    audio = AudioFileClip(audio_file)
    if audio.duration > final_clip.duration:
        audio = audio.subclip(0, final_clip.duration)
    final_clip = final_clip.set_audio(audio)
    final_video_path = os.path.join(output_folder, final_video_name)
    final_clip.write_videofile(final_video_path, codec="libx264", audio_codec="aac", fps=24)
    return final_video_path

# Route to handle the API request
@app.route('/generate_video', methods=['POST'])
def generate_video():
    data = request.get_json()
    topic = data.get('topic')
    video_length = int(data.get('video_length', 20))
    subject_description = data.get('subject_description', topic)
    consistent_subjects = data.get('consistent_subjects', '')
    num_prompts = video_length // 2

    # Generate prompts and images
    image_prompts = generate_text(topic, num_prompts)
    consistent_images_path = create_consistent_images(num_prompts, topic, subject_description, consistent_subjects, image_prompts)
    
    # Define paths
    image_folder = consistent_images_path
    output_folder = "/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/combined_consistent_videos"
    audio_file = "/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/emotional_music.mp3"
    
    # Create final video
    final_video_path = create_final_video_with_audio(image_folder, output_folder, audio_file)
    
    # Upload to S3
    s3_filename = f"{uuid.uuid4()}.mp4"
    s3_url = upload_file_to_s3(final_video_path, s3_bucket_name, s3_filename)

    # Cleanup all assets
    shutil.rmtree("consistent_images")
    shutil.rmtree(output_folder)
    
    if s3_url:
        return jsonify({"status": "success", "video_url": s3_url}), 200
    else:
        return jsonify({"status": "error", "message": "Failed to upload video to S3"}), 500

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port='7016')
