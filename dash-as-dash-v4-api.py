#Use moviepy version - pip install moviepy==1.0.3
from flask import Flask, request, jsonify
import openai
import os
import json
import ast
from io import BytesIO
import requests
import cv2
import numpy as np
from moviepy.editor import ImageClip, concatenate_videoclips, VideoFileClip, AudioFileClip, ImageSequenceClip
from moviepy.video.fx.all import resize, crop
import boto3
from botocore.exceptions import NoCredentialsError
from PIL import Image
from urllib.request import urlopen, urlretrieve
import uuid



app = Flask(__name__)
openai_api_key = os.getenv("OPENAI_API_KEY")

# Initialize the OpenAI client
client = openai.OpenAI(api_key=openai_api_key)

# Defining AWS credentials
aws_region = os.getenv("AWS_REGION")
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
bucket_name = os.getenv("S3_BUCKET_NAME")

# Clear assets function
def clear_all_folders():
    folders = ["images_with_text", "action_images_with_metrics", "dash_images"]
    for folder in folders:
        clear_folder(folder)
        os.makedirs(folder, exist_ok=True)  # Ensure folder exists after clearing

# Clear a specific folder
def clear_folder(folder_path):
    for filename in os.listdir(folder_path):
        file_path = os.path.join(folder_path, filename)
        os.remove(file_path)
    print(f"Cleared all files in folder: {folder_path}")

# Upload file to S3
def upload_file_to_s3(file_path, bucket_name, s3_filename):
    s3 = boto3.client('s3',
                      region_name=aws_region,
                      aws_access_key_id=aws_access_key,
                      aws_secret_access_key=aws_secret_key)
    try:
        # Generate a unique filename if not provided
        if s3_filename is None:
            unique_id = uuid.uuid4().hex
            s3_filename = f"final_dash_video_{unique_id}.mp4"
        
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

# Generating text using OpenAI GPT-4 API
def generate_text(num_frames, topic1, topic2):
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You create prompts which will be used in a text to image model"},
            {"role": "user", "content": f"You create {num_frames} prompts which will be used to create images. {topic1} as {topic2} . Try to focus on a singular subject Only give a python list with these prompts and nothing else. Don't include ```python"}
        ]
    )
    response = completion.choices[0].message.content
    return ast.literal_eval(response)

# Generating casual images
def generate_image(prompts_list, images_list):
    for prompt in prompts_list:
        resp = client.images.generate(
                model="dall-e-3",
                prompt=prompt,
                n=1,
                size="1024x1024"
            )
        image_url = resp.data[0].url
        print("The image url is ", image_url)
        images_list.append(image_url)
    return images_list

# Create a folder to store images
def download_images(image_urls, folder_name="dash_images"):
    if not os.path.exists(folder_name):
        os.makedirs(folder_name)
    
    downloaded_images = []
    for index, url in enumerate(image_urls):
        try:
            response = requests.get(url, stream=True)
            if response.status_code == 200:
                image_path = os.path.join(folder_name, f"image_{index + 1}.png")
                with open(image_path, "wb") as file:
                    for chunk in response.iter_content(1024):
                        file.write(chunk)
                downloaded_images.append(image_path)
            else:
                print(f"Failed to download image from {url}")
        except Exception as e:
            print(f"Error downloading {url}: {e}")
    return downloaded_images

# Create a video from images
def create_video_from_images(image_paths, output_video_path="final_dash_video.mp4", duration_per_image=1.5):
    try:
        clip = ImageSequenceClip(image_paths, durations=[duration_per_image] * len(image_paths))
        clip.write_videofile(output_video_path, codec="libx264", fps=24)
        print(f"Video created at {output_video_path}")
    except Exception as e:
        print(f"Error creating video: {e}")

# Add trimmed audio to video
def add_trimmed_audio_to_video(video_path, audio_path, output_path):
    video = VideoFileClip(video_path)
    audio = AudioFileClip(audio_path)
    
    # Trim audio or video to match the shorter duration
    min_duration = min(video.duration, audio.duration)
    video = video.subclip(0, min_duration)
    audio = audio.subclip(0, min_duration)
    
    # Set the trimmed audio to the video
    video_with_audio = video.set_audio(audio)
    video_with_audio.write_videofile(output_path, codec="libx264", audio_codec="aac")
    print(f"Final video with trimmed audio saved at {output_path}")

# Flask endpoint
@app.route('/create-dash-video', methods=['POST'])
def create_dash_video():
    try:
        # Clear all folders before starting
        clear_all_folders()

        # Parse request data
        data = request.json
        topic1 = data['topic1']
        topic2 = data['topic2']
        num_frames = data['num_frames']
        audio_path = "sample.mp3"  # Predefined audio file
        
        # Generate prompts
        images_list = []
        prompts_list = generate_text(num_frames, topic1, topic2)
        print("Generated prompts: ", prompts_list)

        # Generate images using DALL-E
        final_images_list = generate_image(prompts_list, images_list)
        print("Generated images: ", final_images_list)

        # Download images
        downloaded_images = download_images(final_images_list)

        # Create video from images
        create_video_from_images(downloaded_images, "final_dash_video.mp4")

        # Add trimmed audio to video
        add_trimmed_audio_to_video("final_dash_video.mp4", audio_path, "final_dash_video_with_audio_trimmed.mp4")

        # Upload final video to S3
        final_video_url = upload_file_to_s3("final_dash_video_with_audio_trimmed.mp4", bucket_name, None)

        # Return video URL
        return jsonify({"status": "success", "video_url": final_video_url}), 200
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == '__main__':
    app.run(debug= True, host='0.0.0.0', port=7051)
