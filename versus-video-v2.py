from flask import Flask, request, jsonify
import openai
import os
import json
import ast
from io import BytesIO
import requests
import cv2
import numpy as np
from moviepy.editor import ImageClip, concatenate_videoclips, VideoFileClip, AudioFileClip
from moviepy.video.fx.all import resize, crop
import boto3
from botocore.exceptions import NoCredentialsError
from PIL import Image
from urllib.request import urlopen, urlretrieve  # Import urlretrieve here
from moviepy.editor import ImageClip, VideoFileClip, concatenate_videoclips


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
    folders = ["images_with_text", "action_images_with_metrics"]
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
def generate_text(topic, num_frames):
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Your job is to generate names of enemies/competitors/adversaries for the relevant prompt"},
            {"role": "user", "content": f"This is the topic {topic}. We are making an object which is  {num_frames} long." + " This object will have the names of enemies/adversaries/competitors relevant to the topic and a who will win in a one on one. For example, if the topic is Leopard, then the object will look something like this {'snake': 'win', 'deer': 'win', 'dog': 'win', 'lion': 'lose', 'tiger': 'lose'}. Give this object in python. Don't give any other text in the response except this object. No need for any other text like ```python etc"}
        ]
    )
    response = completion.choices[0].message.content
    return ast.literal_eval(response)

# Generating casual images
def generate_topic_image(topic):

    resp = client.images.generate(
            model="dall-e-3",
            prompt=f"Create a realistic image of {topic} in a natural setting",
            n=1,
            size="1024x1024"
        )
    image_url = resp.data[0].url
    print("The image url is ", image_url)

    return image_url


# Generating casual images
def generate_enemy_images(enemy_object, enemy_images):
    for index, (enemy, battle_outcome) in enumerate(enemy_object.items()):

        resp = client.images.generate(
            model="dall-e-3",
            prompt=f"Create a realistic image of {enemy} in a natural setting",
            n=1,
            size="1024x1024"
        )
        image_url = resp.data[0].url
        print("The image url is ", image_url)
        enemy_images.append(image_url)
    return enemy_images

# Generating action images
def generate_topic_winning(topic, enemy_object, winning_images):
    for index, (enemy, battle_outcome) in enumerate(enemy_object.items()):
        resp = client.images.generate(
            model="dall-e-3",
            prompt=f"Create a realistic image of {topic} {battle_outcome}ing against {enemy} in a dramatic setting. The image should clearly show that winner has won over the loser",
            n=1,
            size="1024x1024"
        )
        image_url = resp.data[0].url
        print("The image url is ", image_url)
        winning_images.append(image_url)
    return winning_images


def create_cropped_combined_battle_images(topic_image_url, final_enemy_images):
    # Folder to save combined images
    output_folder = "combined_battle_images"
    os.makedirs(output_folder, exist_ok=True)
    
    # List to store combined image paths
    combined_images = []

    # Target dimensions for 9:16 aspect ratio (e.g., 1080x1920 for portrait)
    target_width = 1080
    target_height = 1920
    half_height = target_height // 2  # Each image gets half height (960px)

    # Load the topic image
    with urlopen(topic_image_url) as response:
        topic_image = Image.open(response)

    for idx, enemy_image_url in enumerate(final_enemy_images):
        # Load the enemy image
        with urlopen(enemy_image_url) as response:
            enemy_image = Image.open(response)

        # Crop images to maintain the aspect ratio
        topic_image_cropped = crop_to_aspect_ratio(topic_image, target_width, half_height)
        enemy_image_cropped = crop_to_aspect_ratio(enemy_image, target_width, half_height)

        # Create a blank image for the combined portrait
        combined_image = Image.new("RGB", (target_width, target_height))
        
        # Paste images into the combined image
        combined_image.paste(enemy_image_cropped, (0, 0))  # Top half
        combined_image.paste(topic_image_cropped, (0, half_height))  # Bottom half
        
        # Save the combined image
        output_path = os.path.join(output_folder, f"combined_image_{idx + 1}.jpg")
        combined_image.save(output_path)
        combined_images.append(output_path)
    
    return combined_images

def crop_to_aspect_ratio(image, target_width, target_height):
    """Crop the center of an image to the desired aspect ratio."""
    original_width, original_height = image.size
    aspect_ratio = target_width / target_height

    # Determine the cropping box
    if original_width / original_height > aspect_ratio:
        # Wider than target aspect ratio; crop width
        new_width = int(original_height * aspect_ratio)
        offset = (original_width - new_width) // 2
        box = (offset, 0, offset + new_width, original_height)
    else:
        # Taller than target aspect ratio; crop height
        new_height = int(original_width / aspect_ratio)
        offset = (original_height - new_height) // 2
        box = (0, offset, original_width, offset + new_height)

    return image.crop(box).resize((target_width, target_height))

def download_images(image_urls, output_folder):
    """Download images from URLs into the specified folder."""
    os.makedirs(output_folder, exist_ok=True)
    image_paths = []
    for idx, url in enumerate(image_urls):
        output_path = os.path.join(output_folder, f"image_{idx + 1}.jpg")
        urlretrieve(url, output_path)
        image_paths.append(output_path)
    return image_paths

def create_video_from_image(image_path, duration, output_path):
    """Create a video from a single image."""
    clip = ImageClip(image_path, duration=duration)
    clip.write_videofile(output_path, fps=24, codec="libx264")
    return output_path



def compile_final_video(combined_battle_images, winning_images, final_video_path):
    """Create the final compiled video."""
    clips = []

    for battle_image, winning_image in zip(combined_battle_images, winning_images):
        # Create video from combined battle image
        battle_video_path = f"{os.path.splitext(battle_image)[0]}_video.mp4"
        create_video_from_image(battle_image, 1.5, battle_video_path)
        clips.append(VideoFileClip(battle_video_path))  # Use VideoFileClip here

        # Create video from winning image
        winning_video_path = f"{os.path.splitext(winning_image)[0]}_video.mp4"
        create_video_from_image(winning_image, 1.5, winning_video_path)
        clips.append(VideoFileClip(winning_video_path))  # Use VideoFileClip here

    # Concatenate all video clips
    final_clip = concatenate_videoclips(clips, method="compose")
    final_clip.write_videofile(final_video_path, fps=24, codec="libx264")




# Adding audio to video
def add_audio_to_video(video_path, output_path):
    video = VideoFileClip(video_path)
    audio_path = "sample.mp3"  # Directly set to the current directory file
    
    if not os.path.isfile(audio_path):
        raise FileNotFoundError(f"Audio file {audio_path} not found in the current directory.")

    audio = AudioFileClip(audio_path)
    
    if audio.duration > video.duration:
        audio = audio.subclip(0, video.duration)

    video = video.set_audio(audio)
    video.write_videofile(output_path, codec="libx264", audio_codec="aac")
    video.close()
    audio.close()



#Input
topic = "Snow Leopard"
num_frames = 3
'''
enemy_images = []
winning_images = []

#Create topic image
topic_image = generate_topic_image(topic)

#Create enemy object using GPT
enemy_object = generate_text(topic, num_frames)
print("The enemy object is ", enemy_object)

#Create Final Enemy Images using Dalle3
final_enemy_images = generate_enemy_images(enemy_object, enemy_images)
print("The final enemy images are ", final_enemy_images)

#Create Final Winning Images using Dalle3
final_winning_images = generate_topic_winning(topic, enemy_object, winning_images)
print(" The final winning images are ", final_winning_images)
'''
topic_image = 'https://oaidalleapiprodscus.blob.core.windows.net/private/org-IJLNdPbQswPXmkv4mFbx70h9/user-CAmDUFOATURBpfayYNaz0K35/img-qNuMuswDmyy1q5Cm99ocGUnv.png?st=2024-11-20T18%3A43%3A31Z&se=2024-11-20T20%3A43%3A31Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=d505667d-d6c1-4a0a-bac7-5c84a87759f8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2024-11-20T19%3A28%3A54Z&ske=2024-11-21T19%3A28%3A54Z&sks=b&skv=2024-08-04&sig=RRIxGLqZDObeCbL1G%2BbhiwJmuT766mHIZjUUMFLFjpU%3D'

final_enemy_images = ['https://oaidalleapiprodscus.blob.core.windows.net/private/org-IJLNdPbQswPXmkv4mFbx70h9/user-CAmDUFOATURBpfayYNaz0K35/img-1tw5YLMGkvbkW4yqkyYCgTCu.png?st=2024-11-20T18%3A43%3A45Z&se=2024-11-20T20%3A43%3A45Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=d505667d-d6c1-4a0a-bac7-5c84a87759f8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2024-11-20T19%3A12%3A25Z&ske=2024-11-21T19%3A12%3A25Z&sks=b&skv=2024-08-04&sig=TFmWjH8/TEYNxpvywUbtA2UXZEUa/Z1mwpDkog4AMXg%3D', 'https://oaidalleapiprodscus.blob.core.windows.net/private/org-IJLNdPbQswPXmkv4mFbx70h9/user-CAmDUFOATURBpfayYNaz0K35/img-ih9s8JEnZMVv5NM8gXkHK0RX.png?st=2024-11-20T18%3A43%3A57Z&se=2024-11-20T20%3A43%3A57Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=d505667d-d6c1-4a0a-bac7-5c84a87759f8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2024-11-20T19%3A11%3A26Z&ske=2024-11-21T19%3A11%3A26Z&sks=b&skv=2024-08-04&sig=Ac5dw777MHxhkwYhSwQ65WTJmoYZwOO3ZpnlWlzO9m8%3D', 'https://oaidalleapiprodscus.blob.core.windows.net/private/org-IJLNdPbQswPXmkv4mFbx70h9/user-CAmDUFOATURBpfayYNaz0K35/img-uoIrcRbaYtVLQKIrXXRooq2m.png?st=2024-11-20T18%3A44%3A10Z&se=2024-11-20T20%3A44%3A10Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=d505667d-d6c1-4a0a-bac7-5c84a87759f8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2024-11-20T19%3A11%3A17Z&ske=2024-11-21T19%3A11%3A17Z&sks=b&skv=2024-08-04&sig=hwrFj2wqW/PT3/RU4cPVAznPKdhJdf3sZlxBKT7jfUg%3D']

final_winning_images = [ 'https://oaidalleapiprodscus.blob.core.windows.net/private/org-IJLNdPbQswPXmkv4mFbx70h9/user-CAmDUFOATURBpfayYNaz0K35/img-5pFNJILkinsEhiJPQy86GDHF.png?st=2024-11-20T18%3A44%3A23Z&se=2024-11-20T20%3A44%3A23Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=d505667d-d6c1-4a0a-bac7-5c84a87759f8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2024-11-20T19%3A13%3A53Z&ske=2024-11-21T19%3A13%3A53Z&sks=b&skv=2024-08-04&sig=XGfmhjNHk%2BhNVCPspuqM2ADAyGpcvsKY7HjmLQ2VH3s%3D', 'https://oaidalleapiprodscus.blob.core.windows.net/private/org-IJLNdPbQswPXmkv4mFbx70h9/user-CAmDUFOATURBpfayYNaz0K35/img-bkkhy3VsUQUrsDkh9ki5j2ti.png?st=2024-11-20T18%3A44%3A37Z&se=2024-11-20T20%3A44%3A37Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=d505667d-d6c1-4a0a-bac7-5c84a87759f8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2024-11-20T19%3A13%3A18Z&ske=2024-11-21T19%3A13%3A18Z&sks=b&skv=2024-08-04&sig=KkgPsOywwr5KA/l6n4ecSCTkCPogRazg65nDaQHO6rE%3D', 'https://oaidalleapiprodscus.blob.core.windows.net/private/org-IJLNdPbQswPXmkv4mFbx70h9/user-CAmDUFOATURBpfayYNaz0K35/img-Z7r0sftVeI90TelkboCHpCJt.png?st=2024-11-20T18%3A44%3A48Z&se=2024-11-20T20%3A44%3A48Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=d505667d-d6c1-4a0a-bac7-5c84a87759f8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2024-11-20T19%3A12%3A47Z&ske=2024-11-21T19%3A12%3A47Z&sks=b&skv=2024-08-04&sig=PQjg/1qSubg7rGsOuFoGOvcB2eeuIQL1/JZCRjVbDLc%3D']

# Call the function
combined_images = create_cropped_combined_battle_images(topic_image, final_enemy_images)

# Output the paths of the combined images
print("Combined images saved at:")
print(combined_images)

# Define the folder path explicitly
combined_battle_images_folder = "combined_battle_images"

combined_battle_images = sorted(
        [os.path.join(combined_battle_images_folder, f) for f in os.listdir(combined_battle_images_folder) if f.endswith(".jpg")]
    )

# Download winning images
winning_images_folder = "winning_images"
winning_images = download_images(final_winning_images, winning_images_folder)

# Create the final compiled video
final_video_path = "final_combined_video.mp4"
compile_final_video(combined_battle_images, winning_images, final_video_path)
print(f"Final video created: {final_video_path}")
