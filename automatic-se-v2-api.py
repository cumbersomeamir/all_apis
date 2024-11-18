import os
import boto3
from flask import Flask, request, jsonify
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip
import openai
import json
from elevenlabs import ElevenLabs
import uuid

# Initialize Flask app
app = Flask(__name__)

# Initialize ElevenLabs
elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Load environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME", "mygenerateddatabucket")
aws_region = os.getenv("AWS_REGION", "eu-north-1")

# Initialize OpenAI client
openai_api_key = os.getenv("OPENAI_API_KEY")
client = openai.OpenAI(api_key=openai_api_key)

# AWS S3 configuration
s3_client = boto3.client(
    "s3",
    region_name=aws_region,
    aws_access_key_id=aws_access_key,
    aws_secret_access_key=aws_secret_key
)

# Function to download a video from S3
def download_video_from_s3(s3_url, output_path):
    bucket_name = s3_url.split('/')[2].split('.')[0]  # Extract bucket name from URL
    key = '/'.join(s3_url.split('/')[3:])  # Extract object key
    s3_client.download_file(bucket_name, key, output_path)

# Function to upload a file to S3 and return its URL
def upload_file_to_s3(file_path, bucket_name, folder="processed_videos"):
    unique_filename = f"{folder}/{uuid.uuid4()}.mp4"
    s3_client.upload_file(file_path, bucket_name, unique_filename)
    file_url = f"https://{bucket_name}.s3.{aws_region}.amazonaws.com/{unique_filename}"
    print(f"Uploaded file to S3: {file_url}")
    return file_url

# Function to extract audio from video and save as MP3
def extract_audio(video_path, output_folder):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)
    
    try:
        clip = VideoFileClip(video_path)
        audio_path = os.path.join(output_folder, f"{os.path.splitext(os.path.basename(video_path))[0]}.mp3")
        clip.audio.write_audiofile(audio_path)
        clip.close()
        print(f"Audio extracted and saved to {audio_path}")
    except Exception as e:
        print(f"Error extracting audio: {e}")

def speech_to_text(mp3_path):
    audio_file = open(mp3_path, "rb")
    transcription = client.audio.transcriptions.create(
        model="whisper-1",
        file=audio_file,
        response_format='verbose_json',
        timestamp_granularities=['word']
    )
    print("The transcription text is", transcription.text)
    return transcription

def create_se_object(transcription_text):
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "The words you give will be used in a text to sound effects model"},
            {"role": "user", "content": f"Your job is to extract the word and the respective time stamp from {transcription_text} which have a very distinct sound associated with the word.  Limit the list to a maximum of 5-7 highly relevant words. Please give your response in this format" + " - {'word1': 'time1', 'word2': 'time2'} and so on. Please don't include any other text in the response. "}
        ]
    )
    response = completion.choices[0].message.content
    print("The Sound effects object is ", response)
    return response

def generate_sound_effect(word):
    unique_filename = f"{uuid.uuid4()}.mp3"
    folder_path = "text-to-se"
    os.makedirs(folder_path, exist_ok=True)
    output_path = os.path.join(folder_path, unique_filename)
    
    print(f"Generating sound effect for '{word}'...")
    result = elevenlabs.text_to_sound_effects.convert(
        text=word,
        duration_seconds=1,
        prompt_influence=0.3,
    )

    with open(output_path, "wb") as f:
        for chunk in result:
            f.write(chunk)
    print(f"Audio saved to {output_path}")

    return word, unique_filename

def insert_sound_effects_from_s3(s3_url, se_object, word_to_audio_mapping, sound_effects_folder, output_path, temp_video_path="temp_video_se.mp4"):
    try:
        # Download the video from S3
        bucket_name = s3_url.split('/')[2].split('.')[0]
        key = '/'.join(s3_url.split('/')[3:])
        s3_client.download_file(bucket_name, key, temp_video_path)
        print(f"Video downloaded from S3 and saved to {temp_video_path}")

        # Load the video
        video = VideoFileClip(temp_video_path)
        video_audio = video.audio

        # Combine audio clips
        audio_clips = [video_audio]
        for word, timestamp in se_object.items():
            minutes, seconds = map(float, timestamp.split(":"))
            time_in_seconds = minutes * 60 + seconds
            sound_effect_filename = word_to_audio_mapping.get(word)
            if not sound_effect_filename:
                print(f"No sound effect found for word '{word}', skipping...")
                continue
            sound_effect_path = os.path.join(sound_effects_folder, sound_effect_filename)
            if not os.path.exists(sound_effect_path):
                print(f"Sound effect file not found at {sound_effect_path}, skipping...")
                continue
            sound_effect = AudioFileClip(sound_effect_path).set_start(time_in_seconds)
            audio_clips.append(sound_effect)

        final_audio = CompositeAudioClip(audio_clips)
        final_video = video.set_audio(final_audio)
        final_video.write_videofile(output_path, codec="libx264", audio_codec="aac")
        print(f"Final video with sound effects saved to {output_path}")
        os.remove(temp_video_path)

    except Exception as e:
        print(f"Error inserting sound effects: {e}")

def clear_assets(folders):
    try:
        for folder in folders:
            if os.path.exists(folder):
                for file in os.listdir(folder):
                    file_path = os.path.join(folder, file)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                    print(f"Deleted file: {file_path}")
            else:
                os.makedirs(folder)
    except Exception as e:
        print(f"Error clearing assets: {e}")

@app.route('/process-video', methods=['POST'])
def process_video():
    try:
        # Parse the request
        data = request.get_json()
        s3_url = data.get("s3_url")
        if not s3_url:
            return jsonify({"error": "Missing 's3_url' in request."}), 400

        # Prepare folders and paths
        asset_folders = ["text-to-se", "extract_video_se"]
        clear_assets(asset_folders)
        sound_effects_folder = "text-to-se"
        output_path = "final_video_with_sound_effects.mp4"
        video_path = "temp_video.mp4"
        output_folder = "extract_video_se"

        # Download video from S3
        print("Downloading video...")
        download_video_from_s3(s3_url, video_path)

        # Extract audio and process
        print("Extracting audio...")
        extract_audio(video_path, output_folder)
        transcription = speech_to_text(os.path.join(output_folder, "temp_video.mp3"))
        print("Transcription Created")
        se_object = create_se_object(transcription.text)
        se_dict = json.loads(se_object.replace("'", '"'))

        # Generate sound effects and map words to filenames
        word_to_audio_mapping = {}
        for word in se_dict.keys():
            word, filename = generate_sound_effect(word)
            word_to_audio_mapping[word] = filename

        # Insert sound effects into the video
        insert_sound_effects_from_s3(s3_url, se_dict, word_to_audio_mapping, sound_effects_folder, output_path)

        # Upload final video to S3 and return its URL
        final_video_url = upload_file_to_s3(output_path, s3_bucket_name)
        print(f"Final video URL: {final_video_url}")

        return jsonify({"final_video_url": final_video_url}), 200

    except Exception as e:
        print(f"Error: {e}")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(debug= True, host="0.0.0.0", port=7050)
