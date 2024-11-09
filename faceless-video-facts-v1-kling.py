#Recipe
'''
User inputs a prompt and specifies - Topic, Author, Mood, Length of responses, Length of Video, Voice type

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
import os


'''Function defined ahead:
1. Upload to S3 - upload_file_to_s3
2. Text to Video using Kling - text_to_video
3. Create Fact using GPT4o-mini - create_fact
4. Generate Audio from text generated with GPT - submit_text, get_history_item_id, create_audiofile
5. Download Video helper function- download_video
6. Combine generated_audio and generated_video folders - combine_audio_video



'''



# API keys from environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")  # e.g., 'us-east-1'

openai_api_key = os.getenv("OPENAI_API_KEY")
elevenlabs_api_key = os.getenv("ELEVENLABS_API_KEY")

# Initialize the OpenAI client
client = openai.OpenAI(api_key=openai_api_key)

#Upload to S3 function
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


# Function to create a video from prompt using Kling
async def text_to_video(prompt):
    # Submit the request to create the video
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
        # Continuously check the status until it's completed
    while not result_fetched:
        status = await fal_client.status_async("fal-ai/kling-video/v1/standard/text-to-video", request_id, with_logs=True)
        print(f"Current Status: {status}")  # Print the status object for debugging
        
        # Check for various possible status states
        if "Completed" in str(status):
            print("Request completed.")
            result_fetched = True
        elif "Failed" in str(status):
            raise Exception("Request failed.")
        elif "Queued" in str(status):
            print("Request is still in queue...")
        elif "InProgress" in str(status):
            print("Request is currently running...")
    

        
        await asyncio.sleep(2)  # Wait for 2 seconds before checking again
        
    # Fetch the final result
    result = await fal_client.result_async("fal-ai/kling-video/v1/standard/image-to-video", request_id)
    video_url = result['video']['url']
    print("Video URL:", video_url)
    return video_url, result



def create_fact(topic, author, mood):

    
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You are a super intriguing fact writer"},
                {"role": "user", "content": f"Your job is to generate only 1 fact about  {topic} by author {author} in {mood}"}
            ]
        )
        response = completion.choices[0].message.content
        print("The generated fact is ", response)

        
        return response

# Function to submit text to ElevenLabs
def submit_text(generated_text):
    url = "https://api.elevenlabs.io/v1/text-to-speech/TlLWC5O5AUzxAg7ysFZB"
    headers = {
        "Content-Type": "application/json",
        "xi-api-key": elevenlabs_api_key
    }
    data = {
        "text": generated_text,
        "voice_settings": {
            "stability": 0.1,
            "similarity_boost": 0
        }
    }
    response = requests.post(url, headers=headers, data=json.dumps(data))
    if response.status_code == 200:
        print("Success:", response.content)
    else:
        print(f"Error {response.status_code}: {response.content}")

# Function to get history item ID from ElevenLabs
def get_history_item_id():
    client = ElevenLabs(api_key=elevenlabs_api_key)
    resp = client.history.get_all(page_size=1, voice_id="TlLWC5O5AUzxAg7ysFZB")
    history_item_id = resp.history[0].history_item_id
    return history_item_id
    
# Function to create audio file
def create_audiofile(history_item_id, durations):
    output_folder = "generated_audio"
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    client = ElevenLabs(api_key=elevenlabs_api_key)
    audio_generator = client.history.get_audio(history_item_id=str(history_item_id))

    unique_id = str(uuid.uuid4())
    filename = f"{unique_id}.mp3"
    file_path = os.path.join(output_folder, filename)

    with open(file_path, "wb") as audio_file:
        for chunk in audio_generator:
            audio_file.write(chunk)

    audio = AudioSegment.from_file(file_path)
    duration = len(audio) / 1000
    durations.append(duration)
    print(f"{file_path} saved successfully, duration: {duration} seconds")
    return file_path


def download_video(video_url):
    # Ensure the downloaded_videos folder exists
    folder_path = "downloaded_videos"
    os.makedirs(folder_path, exist_ok=True)
    
    # Generate a unique filename
    file_name = f"{uuid.uuid4()}.mp4"
    file_path = os.path.join(folder_path, file_name)
    
    # Download the video
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



def combine_audio_video(root_dir="/Users/amir/desktop/all_apis/lib/python3.12/site-packages"):
    audio_dir = os.path.join(root_dir, "generated_faceless_audios")
    video_dir = os.path.join(root_dir, "downloaded_videos")
    combined_dir = os.path.join(root_dir, "combined_videos")
    
    # Create combined_videos directory if it does not exist
    if not os.path.exists(combined_dir):
        os.makedirs(combined_dir)
    
    # Filter out non-media files and get sorted lists of audio and video files
    audio_files = sorted([f for f in os.listdir(audio_dir) if f.endswith(('.mp3', '.wav'))])
    video_files = sorted([f for f in os.listdir(video_dir) if f.endswith('.mp4')])
    
    # Combine files one by one
    for i, (audio_file, video_file) in enumerate(zip(audio_files, video_files)):
        audio_path = os.path.join(audio_dir, audio_file)
        video_path = os.path.join(video_dir, video_file)
        
        # Load video and audio
        try:
            video_clip = VideoFileClip(video_path)
            audio_clip = AudioFileClip(audio_path)
            
            # Set audio of the video clip
            video_with_audio = video_clip.set_audio(audio_clip)
            
            # Define output path
            output_path = os.path.join(combined_dir, f"combined_{i}.mp4")
            
            # Write the combined video
            video_with_audio.write_videofile(output_path, codec="libx264", audio_codec="aac")
            
            # Close clips to release resources
            video_clip.close()
            audio_clip.close()
        
        except Exception as e:
            print(f"Failed to process {video_file} or {audio_file}: {e}")

    print("All audio and video files have been combined and saved to 'combined_videos' folder.")




#Inputs

topic = input("Enter a topic ")
author = input("Enter an Author name ") #optional
mood = input("Enter a mood ") #optional
video_length = int(input("Enter the length of the video 5s or 10s"))
voice_type = input("Enter the voice type Male or Female")
num_facts = int(video_length/5)
durations= []
'''
topic = "Facts about the Universe"
author = "Charles Bukowski"
mood = "Sad"
video_length = 5
num_facts = int(video_length/5)
voice_type = "Male"
durations= []


'''
#Calling all functions
for j in range (num_facts):
    generated_text = create_fact(topic, author, mood) #Generating text
    print("Done with generating text")
    prompt = "Create a artistic video about "+ generated_text
    submit_text(generated_text) #Submitting text to Elevenlabs
    print("Text submitted to Elevenlabs")
    history_item_id = get_history_item_id() #Get the history of the submiited voice job
    print("The Elevenlabs histroy item id is ", history_item_id)
    audio_file_path = create_audiofile(history_item_id, durations) #creating audio file in local
    print("Audiofile created successfully at location", audio_file_path)
    video_url, video_response = asyncio.run(text_to_video(prompt))
    print("Video created successfully by Kling")
    
    #Download the video from video url
    #Combine the Audio and the video

video_file_path = download_video(video_url)
combine_audio_video()
