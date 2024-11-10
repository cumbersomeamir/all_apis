# Importing all libraries
from flask import Flask, request, jsonify, send_file
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
def generate_text(topic, num_prompts):
    completion = client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {"role": "system", "content": "You are a creative storytelling assistant. Your task is to provide a list of 10 short, vivid sentences that describe a dramatic, emotional, or adventurous journey taken by a dog wearing a bowtie. Each sentence should depict a specific moment or scene that builds upon the previous one, as if telling a visual story in chronological order. Avoid abstract language and instead describe clear actions, settings, or emotions to guide the images. Ensure that the list follows a sequence that feels like a cohesive story, progressing from a calm beginning to a more intense middle and a meaningful ending."},
            {"role": "user", "content": f"Your job is to generate {num_prompts} short sentences that will be used to create an engaging and coherent visual story about {topic}. Keep them extremely short and simple like walking in the garden, feeding birds in the square, no need to mention the name of the subject. Just go for vivid imagery. Please give numbered list only like 1. 2. 3. and so on"}
        ]
    )
    response = completion.choices[0].message.content
    sentences = re.split(r'\d+\.\s', response)[1:]  # Split by numbered list, and ignore the first empty element
    cleaned_sentences = [sentence.strip().replace("\n", "") for sentence in sentences]
    
    return cleaned_sentences

def create_consistent_images(num_prompts, topic, subject_description, consistent_subjects, image_prompts):
    nvidia_api_key = os.getenv("NVIDIA_API_KEY")
    invoke_url = "https://ai.api.nvidia.com/v1/genai/nvidia/consistory"
    headers = {
        "Authorization": f"Bearer {nvidia_api_key}",
        "Accept": "application/json",
    }

    os.makedirs("consistent_images", exist_ok=True)

    for i in range(0, num_prompts, 2):
        # Ensure we don't access out of bounds for image_prompts[i+1]
        scene_prompt2 = image_prompts[i+1] if i+1 < len(image_prompts) else ""

        # Split consistent_subjects into an array if it's provided as a single string
        subject_tokens = consistent_subjects.split(",") if isinstance(consistent_subjects, str) else consistent_subjects

        payload = {
            "mode": 'init',
            "subject_prompt": subject_description,
            "subject_tokens": [token.strip() for token in subject_tokens],  # Trim whitespace
            "subject_seed": 43,
            "style_prompt": "A photo of",
            "scene_prompt1": image_prompts[i],
            "scene_prompt2": scene_prompt2,
            "negative_prompt": "",
            "cfg_scale": 5,
            "same_initial_noise": False
        }

        # Debugging output
        print("Payload:", payload)

        response = requests.post(invoke_url, headers=headers, json=payload)
        
        if response.status_code == 422:
            print("Error 422: Unprocessable Entity - Check payload format and values.")
            print("Response:", response.json())  # Check response for more error details
            break
        
        response.raise_for_status()
        data = response.json()

        for idx, img_data in enumerate(data.get('artifacts', [])):
            img_base64 = img_data.get("base64")
            if img_base64:
                img_bytes = base64.b64decode(img_base64)
                with open(f'consistent_images/image_{i}_{idx}.jpg', "wb") as f:
                    f.write(img_bytes)

    return os.path.abspath("consistent_images")

def create_final_video_with_audio(image_folder, output_folder, audio_file, final_video_name="final_video_with_audio.mp4", duration=2):
    # Ensure output folder exists
    os.makedirs(output_folder, exist_ok=True)
    
    # Collect image files sorted by their filename
    images = sorted([os.path.join(image_folder, img) for img in os.listdir(image_folder) if img.endswith(('.jpg', '.jpeg', '.png'))])
    
    # List to store video clips
    clips = []
    
    # Convert each image to a 2-second video and add to clips list
    for img_path in images:
        clip = ImageClip(img_path).set_duration(duration)
        clips.append(clip)
    
    # Concatenate all clips into a single video
    final_clip = concatenate_videoclips(clips, method="compose")
    
    # Check the duration of the final video
    video_duration = final_clip.duration
    print(f"Video duration: {video_duration} seconds")

    # Load audio file and trim it to match the video duration
    audio = AudioFileClip(audio_file)
    if audio.duration > video_duration:
        audio = audio.subclip(0, video_duration)
    print(f"Audio duration after trimming: {audio.duration} seconds")

    # Add audio to the final video
    final_clip = final_clip.set_audio(audio)
    
    # Path to save the final video
    final_video_path = os.path.join(output_folder, final_video_name)
    
    # Write the video file
    final_clip.write_videofile(final_video_path, codec="libx264", audio_codec="aac", fps=24)

    print(f"Final video with audio saved at: {final_video_path}")

'''
# Inputs
video_length = input("Enter the length of the video ")
topic = input("Enter the topic of the video ")
subject_description = input("Enter the subject description ")
consistent_subjects = input("Enter the subject/subjects which will remain consistent in the story ")
num_prompts = int(int(video_length) / 2)

# Calling functions
image_prompts = generate_text(topic, num_prompts)
print("The image prompts are:", image_prompts)
consistent_images_path = create_consistent_images(num_prompts, topic, subject_description, consistent_subjects, image_prompts)
print("The path of all the images is", consistent_images_path)
'''
# Define paths
image_folder = "/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/consistent_images"
output_folder = "/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/combined_consistent_videos"
audio_file = "/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/emotional_music.mp3"

# Call the final video creation function
create_final_video_with_audio(image_folder, output_folder, audio_file)


#Try different styles from Nvidia
#Sound Effects need to be added - prompt should be shorted to having isolated sound effects, also a single long sound effect can also be generated for the whole video
