# Recipe
'''
Enter a topic to generate Loop Video using Kling
'''

import os
import boto3
from PIL import Image
import requests
from io import BytesIO
import asyncio
import fal_client
import openai
from elevenlabs import ElevenLabs
import json
import uuid
from pydub import AudioSegment
import requests
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips
from flask import Flask, request, jsonify
import shutil

app = Flask(__name__)

# API keys from environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")  # e.g., 'us-east-1'

elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Upload to S3 function
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

# Function to create a video from prompt using Kling
async def text_to_video(prompt):
    handler = await fal_client.submit_async(
        "fal-ai/kling-video/v1/standard/text-to-video",
        arguments={
            "prompt": prompt
        },
        webhook_url=None,
    )

    request_id = handler.request_id
    print("Request ID:", request_id)
    result_fetched = False

    while not result_fetched:
        status = await fal_client.status_async("fal-ai/kling-video/v1/standard/text-to-video", request_id, with_logs=True)
        print(f"Current Status: {status}")
        
        if "Completed" in str(status):
            print("Request completed.")
            result_fetched = True
        elif "Failed" in str(status):
            raise Exception("Request failed.")
        
        await asyncio.sleep(2)
        
    result = await fal_client.result_async("fal-ai/kling-video/v1/standard/image-to-video", request_id)
    video_url = result['video']['url']
    print("Video URL:", video_url)
    return video_url, result

def download_video(video_url):
    folder_path = "downloaded_loop_videos"
    os.makedirs(folder_path, exist_ok=True)
    file_name = f"{uuid.uuid4()}.mp4"
    file_path = os.path.join(folder_path, file_name)
    
    response = requests.get(video_url, stream=True)
    if response.status_code == 200:
        with open(file_path, "wb") as file:
            for chunk in response.iter_content(chunk_size=8192):
                file.write(chunk)
        print(f"Downloaded to {file_path}")
    else:
        print("Failed to download video")
        file_path = None
    
    return file_path

def generate_sound_effect(text: str, output_path: str):
    folder_path = "loop_sound_effects"
    os.makedirs(folder_path, exist_ok=True)
    output_path = os.path.join(folder_path, output_path)
    
    print("Generating sound effects...")
    result = elevenlabs.text_to_sound_effects.convert(
        text=text,
        duration_seconds=5,
        prompt_influence=0.3,
    )

    with open(output_path, "wb") as f:
        for chunk in result:
            f.write(chunk)
    print(f"Audio saved to {output_path}")

def combine_video_audio(video_path, audio_path):
    folder_path = "combined_loop_videos"
    os.makedirs(folder_path, exist_ok=True)
    
    video_clip = VideoFileClip(video_path)
    audio_clip = AudioFileClip(audio_path)
    video_with_audio = video_clip.set_audio(audio_clip)
    output_path = os.path.join(folder_path, f"{uuid.uuid4()}.mp4")
    video_with_audio.write_videofile(output_path, codec="libx264")
    print(f"Combined video saved to {output_path}")
    return output_path

def cleanup_folders():
    folders_to_clean = ["downloaded_loop_videos", "loop_sound_effects", "combined_loop_videos"]
    for folder in folders_to_clean:
        if os.path.exists(folder):
            shutil.rmtree(folder)
            print(f"Deleted contents of {folder}")

@app.route('/generate-loop-video', methods=['POST'])
def generate_loop_video():
    data = request.get_json()
    topic = data.get('topic', 'Default Topic')
    prompt = "Create a trippy loop video about " + str(topic)

    # Asynchronous execution
    video_url, video_response = asyncio.run(text_to_video(prompt))
    video_path = download_video(video_url)
    generate_sound_effect("Mellow Trippy loop mystery", "output_sound_effect.mp3")
    final_video_path = combine_video_audio(video_path, "loop_sound_effects/output_sound_effect.mp3")

    # Upload final video to S3
    s3_filename = f"final_videos/{uuid.uuid4()}.mp4"
    s3_url = upload_file_to_s3(final_video_path, s3_bucket_name, s3_filename)

    # Clean up folders
    cleanup_folders()

    # Return the S3 URL as JSON
    return jsonify({"video_url": s3_url})

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=7015)


#Sound Effect not present on the combined video, api created test
