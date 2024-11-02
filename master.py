import asyncio
import os
import re
import uuid
import requests
import json
import boto3
from moviepy.editor import VideoFileClip, concatenate_videoclips, AudioFileClip
from pydub import AudioSegment
import openai
from elevenlabs import ElevenLabs
from fal_client import submit_async, status_async, result_async

# Initialize environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")
openai_api_key = os.getenv("OPENAI_API_KEY")
elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")

# Initialize OpenAI and ElevenLabs clients
client = openai.OpenAI(api_key=openai_api_key)
elevenlabs_client = ElevenLabs(api_key=elevenlabs_api_key)

async def text_to_video_Kling(prompt, webhook_url=None):
    handler = await submit_async(
        "fal-ai/kling-video/v1/standard/text-to-video",
        arguments={"prompt": prompt},
        webhook_url=webhook_url
    )
    request_id = handler.request_id
    print(f"Request ID: {request_id}")

    # Check the status until the video is completed
    while True:
        status = await status_async("fal-ai/kling-video/v1/standard/text-to-video", request_id, with_logs=True)
        if hasattr(status, 'status') and status.status == "Completed":
            break
        elif hasattr(status, 'status') and status.status == "Failed":
            raise Exception("Video generation failed.")
        await asyncio.sleep(2)
    
    result = await result_async("fal-ai/kling-video/v1/standard/text-to-video", request_id)
    return result['video_url']

def generate_prompts(topic, num_prompts):
    response = client.chat.completions.create(
        model="gpt-4",
        messages=[
            {"role": "system", "content": "You are a creative story writer."},
            {"role": "user", "content": f"Generate {num_prompts} single-line prompts about {topic}."}
        ]
    )
    text = response.choices[0].message.content
    prompts = re.split(r'\d+\.\s', text)[1:]
    return [prompt.strip() for prompt in prompts[:num_prompts]]

def create_voiceover(text):
    url = "https://api.elevenlabs.io/v1/text-to-speech/TlLWC5O5AUzxAg7ysFZB"
    headers = {"Content-Type": "application/json", "xi-api-key": elevenlabs_api_key}
    data = {"text": text, "voice_settings": {"stability": 0.1, "similarity_boost": 0}}

    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        audio_file = f"{uuid.uuid4()}.mp3"
        with open(audio_file, "wb") as file:
            file.write(response.content)
        return audio_file
    else:
        raise Exception(f"Error {response.status_code}: {response.content}")

def download_and_combine_videos(video_urls, audio_files, output_path="final_video.mp4"):
    clips = []
    for video_url, audio_file in zip(video_urls, audio_files):
        video_clip = VideoFileClip(video_url)
        audio_clip = AudioFileClip(audio_file)
        video_clip = video_clip.set_audio(audio_clip)
        clips.append(video_clip)

    final_video = concatenate_videoclips(clips, method="compose")
    final_video.write_videofile(output_path)
    print(f"Final video saved to {output_path}")

async def main():
    # Step 1: Generate two prompts
    topic = "A stylish woman in Tokyo at night"
    prompts = generate_prompts(topic, num_prompts=2)
    
    # Step 2: Generate videos based on prompts
    video_tasks = [text_to_video_Kling(prompt) for prompt in prompts]
    video_urls = await asyncio.gather(*video_tasks)
    print("Video URLs:", video_urls)
    
    # Step 3: Generate voiceovers
    audio_files = [create_voiceover(prompt) for prompt in prompts]
    print("Audio files created:", audio_files)
    
    # Step 4: Combine videos and voiceovers into final video
    download_and_combine_videos(video_urls, audio_files)

# Run the main function
asyncio.run(main())

