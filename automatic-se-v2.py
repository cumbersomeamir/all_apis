import os
import boto3
from moviepy.editor import VideoFileClip
import openai
import json
from elevenlabs import ElevenLabs
from moviepy.editor import VideoFileClip, AudioFileClip, CompositeAudioClip
import uuid

elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Load environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME", "mygenerateddatabucket")
aws_region = os.getenv("AWS_REGION", "eu-north-1")


openai_api_key = os.getenv("OPENAI_API_KEY")
elevenlabs = ElevenLabs(api_key=os.getenv("ELEVENLABS_API_KEY"))

# Initialize the OpenAI client
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

# Function to extract audio from video and save as MP3
def extract_audio(video_path, output_folder):
    # Ensure output folder exists
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
    print("The transciption text is", transcription.text)
    return transcription  # Return the full transcription for further processing

def create_se_object(transcription_text):

    
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "The words you give will be used in a text to sound effects model"},
                {"role": "user", "content": f"Your job is to extract the word and the respective time stamp from {transcription_text} which have a very distinct sound associated with the word.  Limit the list to a maximum of 5-7 highly relevant words. Please give your response in this format" + " - {'word1': 'time1', 'word2': 'time2'} and so on. Please dont include any other text in the response. "
                }
            ]
        )
        response = completion.choices[0].message.content
        print("The Sound effects object is ", response)

        
        return response




def generate_sound_effect(word):
    # Generate a unique filename using UUID
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

    # Return the mapping of the word to its file path
    return word, unique_filename


    





def insert_sound_effects_from_s3(s3_url, se_object, word_to_audio_mapping, sound_effects_folder, output_path, temp_video_path="temp_video_se.mp4"):
    """
    Downloads a video from S3, inserts sound effects into it based on the timestamps in the se_object,
    and saves the final video with sound effects.

    Args:
        s3_url (str): URL of the video file in S3.
        se_object (dict): Dictionary with words as keys and timestamps as values (e.g., {'word1': '0:01', 'word2': '0:05'}).
        word_to_audio_mapping (dict): Dictionary mapping words to their generated sound effect filenames.
        sound_effects_folder (str): Folder containing the generated sound effects.
        output_path (str): Path to save the final video with sound effects.
        temp_video_path (str): Path to temporarily save the downloaded video from S3 (default: temp_video.mp4).

    Returns:
        None
    """
    try:
        # Step 1: Download the video from S3
        bucket_name = s3_url.split('/')[2].split('.')[0]  # Extract bucket name from URL
        key = '/'.join(s3_url.split('/')[3:])  # Extract object key
        s3_client.download_file(bucket_name, key, temp_video_path)
        print(f"Video downloaded from S3 and saved to {temp_video_path}")

        # Step 2: Load the downloaded video
        video = VideoFileClip(temp_video_path)
        video_audio = video.audio

        # Step 3: Prepare the list of audio clips (original video + sound effects)
        audio_clips = [video_audio]

        # Step 4: Insert sound effects at the specified timestamps
        for word, timestamp in se_object.items():
            # Parse the timestamp into seconds
            minutes, seconds = map(float, timestamp.split(":"))
            time_in_seconds = minutes * 60 + seconds

            # Get the correct sound effect filename from the mapping
            sound_effect_filename = word_to_audio_mapping.get(word)
            if not sound_effect_filename:
                print(f"No sound effect found for word '{word}', skipping...")
                continue

            # Construct the full path to the sound effect file
            sound_effect_path = os.path.join(sound_effects_folder, sound_effect_filename)
            if not os.path.exists(sound_effect_path):
                print(f"Sound effect file not found at {sound_effect_path}, skipping...")
                continue

            # Load the sound effect audio
            sound_effect = AudioFileClip(sound_effect_path)

            # Set the start time for the sound effect
            sound_effect = sound_effect.set_start(time_in_seconds)

            # Add the sound effect to the list
            audio_clips.append(sound_effect)

        # Step 5: Combine the original audio with all sound effects
        final_audio = CompositeAudioClip(audio_clips)

        # Step 6: Set the new audio to the video
        final_video = video.set_audio(final_audio)

        # Step 7: Write the final video to the output path
        final_video.write_videofile(output_path, codec="libx264", audio_codec="aac")

        print(f"Final video with sound effects saved to {output_path}")

        # Step 8: Clean up temporary video file
        os.remove(temp_video_path)

    except Exception as e:
        print(f"Error inserting sound effects: {e}")

def clear_assets(folders):
    """
    Clears all files in the specified folders.

    Args:
        folders (list): List of folder paths to clear.
    """
    try:
        for folder in folders:
            if os.path.exists(folder):
                for file in os.listdir(folder):
                    file_path = os.path.join(folder, file)
                    if os.path.isfile(file_path):
                        os.remove(file_path)
                    print(f"Deleted file: {file_path}")
            else:
                os.makedirs(folder)  # Create folder if it doesn't exist
                print(f"Created folder: {folder}")
    except Exception as e:
        print(f"Error clearing assets: {e}")



def main():
    # Clear relevant folders
    asset_folders = ["text-to-se", "extract_video_se"]
    print("Clearing assets...")
    clear_assets(asset_folders)

    s3_url = "https://mygenerateddatabucket.s3.eu-north-1.amazonaws.com/final_video_with_captions.mp4"
    sound_effects_folder = "text-to-se"
    output_path = "final_video_with_sound_effects.mp4"

    try:
        video_path = "temp_video.mp4"
        output_folder = "extract_video_se"

        # Download video from S3
        print("Downloading video...")
        download_video_from_s3(s3_url, video_path)

        # Extract audio
        print("Extracting audio...")
        extract_audio(video_path, output_folder)

        # Creating Transcription
        transcription = speech_to_text("/Users/amir/Desktop/all_apis/lib/python3.12/site-packages/extract_video_se/temp_video.mp3")
        print("Transcription Created")
        se_object = create_se_object(transcription.text)
        se_dict = json.loads(se_object.replace("'", '"'))  # Ensure valid JSON format

        # Generate sound effects and map words to filenames
        word_to_audio_mapping = {}
        for word in se_dict.keys():
            word, filename = generate_sound_effect(word)
            word_to_audio_mapping[word] = filename

        # Insert sound effects into the video
        insert_sound_effects_from_s3(s3_url, se_dict, word_to_audio_mapping, sound_effects_folder, output_path)

        # Clean up temporary video file
        os.remove(video_path)
        print("Process completed successfully.")

    except Exception as e:
        print(f"Error: {e}")

        
        

if __name__ == "__main__":
    main()
