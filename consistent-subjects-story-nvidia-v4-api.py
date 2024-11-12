# Importing libraries
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
import shutil  # For deleting folder contents
import boto3
from botocore.exceptions import NoCredentialsError
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip

# API keys from environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")  # e.g., 'us-east-1'
openai_api_key = os.getenv("OPENAI_API_KEY")

# Initialize the OpenAI client
client = openai.OpenAI(api_key=openai_api_key)

app = Flask(__name__)

# Function to upload video to S3
def upload_file_to_s3(file_path, bucket_name, s3_filename):
    s3 = boto3.client('s3', region_name=aws_region,
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

# Function to generate text prompts
def generate_text(topic, num_prompts):
    try:
        completion = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": "Generate short, vivid sentences describing scenes for a story."},
                {"role": "user", "content": f"Generate {num_prompts} short sentences about {topic}. Numbered list only."}
            ]
        )
        response = completion.choices[0].message.content
        sentences = re.split(r'\d+\.\s', response)[1:]  # Split by numbered list, ignore the first empty element
        cleaned_sentences = [sentence.strip().replace("\n", "") for sentence in sentences]
        print("Generated image prompts:", cleaned_sentences)  # Debugging output
        return cleaned_sentences if cleaned_sentences else []
    except Exception as e:
        print("Error generating text:", e)
        return []

# Function to clean up folders before processing
def clean_folder(folder_path):
    if os.path.exists(folder_path):
        shutil.rmtree(folder_path)
    os.makedirs(folder_path)
    print(f"Cleaned and created folder: {folder_path}")  # Debugging output

# Function to create consistent images
def create_consistent_images(num_prompts, topic, subject_description, consistent_subjects, image_prompts):
    nvidia_api_key = os.getenv("NVIDIA_API_KEY")
    invoke_url = "https://ai.api.nvidia.com/v1/genai/nvidia/consistory"
    headers = {
        "Authorization": f"Bearer {nvidia_api_key}",
        "Accept": "application/json",
    }
    
    image_folder = "/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/consistent_images"
    clean_folder(image_folder)

    max_prompts = min(num_prompts, len(image_prompts))  # Ensure we do not exceed available prompts
    print(f"Using max prompts: {max_prompts} out of {len(image_prompts)} available prompts")  # Debugging output

    for i in range(0, max_prompts, 2):
        scene_prompt1 = image_prompts[i]
        scene_prompt2 = image_prompts[i+1] if i+1 < len(image_prompts) else ""
        subject_tokens = consistent_subjects.split(",")

        payload = {
            "mode": 'init',
            "subject_prompt": subject_description,
            "subject_tokens": [token.strip() for token in subject_tokens],
            "subject_seed": 43,
            "style_prompt": "A photo of",
            "scene_prompt1": scene_prompt1,
            "scene_prompt2": scene_prompt2,
            "cfg_scale": 5,
            "same_initial_noise": False
        }

        print("Sending payload:", payload)  # Debugging payload output
        response = requests.post(invoke_url, headers=headers, json=payload)
        
        if response.status_code != 200:
            print(f"Error {response.status_code}: {response.json()}")
            continue
        
        data = response.json()
        if 'artifacts' not in data:
            print("No artifacts found in the response.")
            continue

        for idx, img_data in enumerate(data['artifacts']):
            img_base64 = img_data.get("base64")
            if img_base64:
                img_path = f"{image_folder}/image_{i}_{idx}.jpg"
                with open(img_path, "wb") as f:
                    f.write(base64.b64decode(img_base64))
                print(f"Saved image at {img_path}")
            else:
                print(f"No base64 data for image {idx} in response for prompt {i}")

    return image_folder

# Function to create final video with audio
def create_final_video_with_audio(image_folder, output_folder, audio_file, final_video_name="final_video_with_audio.mp4", duration=2):
    clean_folder(output_folder)
    
    images = sorted([os.path.join(image_folder, img) for img in os.listdir(image_folder) if img.endswith(('.jpg', '.jpeg', '.png'))])
    print("Found image files:", images)

    if not images:
        print("No images found in the specified folder.")
        return None
    
    try:
        clips = [ImageClip(img_path).set_duration(duration) for img_path in images]
        if not clips:
            print("No clips created from images.")
            return None

        final_clip = concatenate_videoclips(clips, method="compose")
        audio = AudioFileClip(audio_file)
        audio = audio.subclip(0, final_clip.duration)

        final_clip = final_clip.set_audio(audio)
        final_video_path = os.path.join(output_folder, final_video_name)
        final_clip.write_videofile(final_video_path, codec="libx264", audio_codec="aac", fps=24)
        print(f"Final video with audio saved at: {final_video_path}")
        return final_video_path
    except Exception as e:
        print("Error during video creation:", e)
        return None

@app.route('/generate-video', methods=['POST'])
def generate_video():
    data = request.get_json()
    video_length = int(data.get("video_length", 10))  # Default length of 10 seconds if not provided
    topic = data.get("topic", "default topic")
    subject_description = data.get("subject_description", "default subject")
    consistent_subjects = data.get("consistent_subjects", "default subjects")

    num_prompts = int(video_length / 2)

    # Generating image prompts and images
    image_prompts = generate_text(topic, num_prompts)
    if not image_prompts:
        return jsonify({"error": "No prompts generated."}), 400

    # Define paths and execute the video creation
    image_folder = "/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/consistent_images"
    output_folder = "/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/combined_consistent_videos"
    audio_file = "/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/emotional_music.mp3"

    print("Creating images...")
    create_consistent_images(num_prompts, topic, subject_description, consistent_subjects, image_prompts)

    print("Creating final video with audio...")
    final_video_path = create_final_video_with_audio(image_folder, output_folder, audio_file)
    if not final_video_path:
        return jsonify({"error": "Failed to create final video."}), 500

    # Upload to S3
    s3_filename = f"{uuid.uuid4()}.mp4"
    s3_url = upload_file_to_s3(final_video_path, s3_bucket_name, s3_filename)
    if not s3_url:
        return jsonify({"error": "Failed to upload video to S3."}), 500

    return jsonify({"s3_url": s3_url}), 200

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0',port=7025)
