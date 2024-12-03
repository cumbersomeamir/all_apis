#Use moviepy version - pip install moviepy==1.0.3
import fal_client
import fal_client
import asyncio
import boto3
import os
import uuid
import requests
from flask import Flask, request, jsonify
from moviepy.editor import VideoFileClip, AudioFileClip, concatenate_videoclips
from elevenlabs import ElevenLabs

# Initialize Flask app
app = Flask(__name__)

# API keys from environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")
elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Helper function to clean up folder contents
def clean_up_folders(folders):
    for folder in folders:
        if os.path.exists(folder):
            for file in os.listdir(folder):
                file_path = os.path.join(folder, file)
                if os.path.isfile(file_path):
                    os.remove(file_path)

# Function to upload file to S3
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

# Logs for queue updates
def on_queue_update(update):
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
            print(log["message"])

# Create an image
def create_image(prompt):
    result = fal_client.subscribe(
        "fal-ai/recraft-v3",
        arguments={"prompt": prompt},
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    image_url = result['images'][0]['url']
    print("Image URL:", image_url)
    return image_url

# Download video helper function
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

# Create a video from the image URL
async def image_to_video(image_url):
    handler = await fal_client.submit_async(
        "fal-ai/kling-video/v1/standard/image-to-video",
        arguments={"prompt": "Add motion to the image", "image_url": image_url},
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
        elif "Queued" in str(status):
            print("Request is still in queue...")
        elif "InProgress" in str(status):
            print("Request is currently running...")
    
        await asyncio.sleep(2)
    
    result = await fal_client.result_async("fal-ai/kling-video/v1/standard/image-to-video", request_id)
    video_url = result['video']['url']
    print("Video URL:", video_url)
    return video_url, result

def generate_sound_effect(text: str):
    file_path = "output.mp3"
    folder_path = "emotional_sound_effects"
    os.makedirs(folder_path, exist_ok=True)
    output_path = os.path.join(folder_path, file_path)
    
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
    return output_path


def combine_video_audio(video_path, audio_path):
    folder_path = "combined_emotional_videos"
    os.makedirs(folder_path, exist_ok=True)

    # Load video and audio clips
    video_clip = VideoFileClip(video_path)
    audio_clip = AudioFileClip(audio_path)

    # Trim the audio clip if it’s longer than the video or extend it if shorter
    audio_clip = audio_clip.subclip(0, min(audio_clip.duration, video_clip.duration))

    # Set audio to video and save
    video_with_audio = video_clip.set_audio(audio_clip)
    output_path = os.path.join(folder_path, f"{uuid.uuid4()}.mp4")
    video_with_audio.write_videofile(output_path, codec="libx264", audio_codec="aac")

    print(f"Combined video saved to {output_path}")
    return output_path


# Main function to handle the process
async def process_request(text, image_text):
    # Generate the image prompt
    background_extra = "create an image where at the top there is a text with white background saying "
    underneath_extra = "And underneath is an image of "
    prompt = f"{background_extra}{text}{underneath_extra}{image_text}"
    
    # Step 1: Create Image
    image_url = create_image(prompt)
    
    # Step 2: Convert Image to Video
    video_url, _ = await image_to_video(image_url)
    #video_url="https://v3.fal.media/files/monkey/z3GtKt1YCMob9imKearWb_output.mp4"
    video_path = download_video(video_url)
    
    # Step 3: Generate Sound Effect
    sound_output_path = generate_sound_effect("mellow mystery background music ")
    
    # Step 4: Combine Video and Sound
    final_video_path = combine_video_audio(video_path, sound_output_path)
    
    # Step 5: Upload to S3
    s3_filename = os.path.basename(final_video_path)
    s3_url = upload_file_to_s3(final_video_path, s3_bucket_name, s3_filename)
    
    return s3_url

# Define the API endpoint
@app.route('/generate-video', methods=['POST'])
def generate_video():
    data = request.json
    text = data.get("text")
    image_text = data.get("image_text")
    
    if not text or not image_text:
        return jsonify({"error": "Both 'text' and 'image_text' are required"}), 400

    # Clean up folders before processing
    clean_up_folders(["downloaded_loop_videos", "emotional_sound_effects", "combined_emotional_videos"])

    # Process the request
    s3_url = asyncio.run(process_request(text, image_text))
    return jsonify({"video_url": s3_url})

# Run Flask app
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=7022)
