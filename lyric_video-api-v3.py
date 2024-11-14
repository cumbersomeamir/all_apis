from flask import Flask, request, jsonify
import requests
import moviepy.editor as mp
import boto3
import os
from uuid import uuid4

app = Flask(__name__)

# Load environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME", "mygenerateddatabucket")
aws_region = os.getenv("AWS_REGION", "eu-north-1")
external_ip = os.getenv("EXTERNAL_IP")

# AWS S3 configuration
s3_client = boto3.client(
    "s3",
    region_name=aws_region,
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_key
)

# Endpoint to handle video generation and audio merging
@app.route('/create-video-with-audio', methods=['POST'])
def create_video_with_audio():
    # Retrieve input data
    data = request.get_json()
    audio_url = data.get("audio_url")
    topic = data.get("topic")
    num_frames = data.get("num_frames")

    # Step 1: Request video generation
    response = requests.post("http://localhost:7035/video-story", json={"topic": topic, "num_frames": num_frames})
    if response.status_code != 200:
        return jsonify({"error": "Failed to generate video"}), 500

    video_url = response.json().get("video_url")
    print(f"Video URL: {video_url}")

    # Step 2: Download video and audio
    video_filename = f"/tmp/{uuid4()}.mp4"
    audio_filename = f"/tmp/{uuid4()}.mp3"
    combined_filename = f"/tmp/{uuid4()}_combined.mp4"

    # Download video
    video_data = requests.get(video_url)
    with open(video_filename, 'wb') as f:
        f.write(video_data.content)

    # Download audio
    audio_data = requests.get(audio_url)
    with open(audio_filename, 'wb') as f:
        f.write(audio_data.content)

    # Step 3: Load video and audio, mute video, and combine
    video_clip = mp.VideoFileClip(video_filename).without_audio()
    audio_clip = mp.AudioFileClip(audio_filename)

    # Truncate audio or video to the shortest duration
    min_duration = min(video_clip.duration, audio_clip.duration)
    final_video = video_clip.subclip(0, min_duration).set_audio(audio_clip.subclip(0, min_duration))
    final_video.write_videofile(combined_filename, codec="libx264", audio_codec="aac")

    # Step 4: Upload the combined video to S3
    s3_key = f"videos/{uuid4()}_final_combined_video.mp4"
    s3_client.upload_file(combined_filename, s3_bucket_name, s3_key)
    combined_video_url = f"https://{s3_bucket_name}.s3.{aws_region}.amazonaws.com/{s3_key}"
    print(f"Final Combined Video URL: {combined_video_url}")

    # Clean up temporary files
    os.remove(video_filename)
    os.remove(audio_filename)
    os.remove(combined_filename)

    # Step 5: Send combined video URL to captioning API
    caption_response = requests.post(
        f"http://{external_ip}:7020/caption_video",
        json={"video_url": combined_video_url},
        headers={"Content-Type": "application/json"}
    )

    # Check if the captioning API request was successful
    if caption_response.status_code != 200:
        return jsonify({"error": "Failed to caption video"}), 500

    # Retrieve the final video URL with captions
    captioned_video_url = caption_response.json().get("video_url")
    print(f"Captioned Video URL: {captioned_video_url}")

    # Return the final captioned video URL to the user
    return jsonify({"captioned_video_url": captioned_video_url})

if __name__ == "__main__":
    app.run(debug=True, host='0.0.0.0', port=7036)
