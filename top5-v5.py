# Importing all libraries
import openai
import os
import json
import ast
from io import BytesIO
import requests
import cv2
import numpy as np
from moviepy.editor import ImageClip, concatenate_videoclips
from moviepy.video.fx.all import resize, crop
from moviepy.editor import VideoFileClip, AudioFileClip
import fal_client

# Accepting all environment variables
openai_api_key = os.getenv("OPENAI_API_KEY")

# Initialize the OpenAI client
client = openai.OpenAI(api_key=openai_api_key)

# Defining Azure file upload to s3 helper function
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

# Generating 10 subject words and metrics using OpenAI GPT-4 API
def generate_text(topic, num_frames):
    completion = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "You generate an object only according to topic"},
            {"role": "user", "content": f"This is the topic {topic}. We are making top {num_frames} list." + " In this list there is a subject and there is a respective discrete (number) metric. For example, if the topic is fastest animals the subjects will be Cheetah, Tiger, Deer and so on and the metrics will be their top speed. So you have to finally only return an object which looks like {'Cheetah' : 'Top Speed : 110', 'Tiger': 'Top Speed : 90'} and so on. Make sure the subjects have max two words and the metric is preferably a number, specific and trustable. Please only return the final object and nothing else "}
        ]
    )
    response = completion.choices[0].message.content
    return ast.literal_eval(response)

def generate_casual_image(subjects, casual_subjects):
    for subject in subjects:
        resp = client.images.generate(
            model="dall-e-3",
            prompt=f"Create a realistic image of this {subject} in a natural location",
            n=1,
            size="1024x1024"
        )
        image_url = resp.data[0].url
        print("The image url is ", image_url)
        casual_subjects.append(image_url)
    return casual_subjects

def generate_action_image(subjects, action_subjects):
    for subject in subjects:
        resp = client.images.generate(
            model="dall-e-3",
            prompt=f"Create a realistic image of this {subject} in action",
            n=1,
            size="1024x1024"
        )
        image_url = resp.data[0].url
        print("The image url is ", image_url)
        action_subjects.append(image_url)
    return action_subjects

# Using OpenCV to add numbers to images
# Modified function to add number and subject name to images
def add_number_and_name_to_image_cv2(url, number, subject_name):
    output_folder = "images_with_text"
    os.makedirs(output_folder, exist_ok=True)

    response = requests.get(url)
    image_data = np.asarray(bytearray(response.content), dtype="uint8")
    img = cv2.imdecode(image_data, cv2.IMREAD_COLOR)

    font_scale = min(img.shape[1], img.shape[0]) / 500
    font_thickness = 2
    text = f"{number}. {subject_name}"
    text_size = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)[0]
    x = (img.shape[1] - text_size[0]) // 2
    y = int(img.shape[0] * 0.25)

    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
    cv2.imwrite(os.path.join(output_folder, f"image_with_number_{number}.png"), img)
    print(f"Image with number {number} and subject '{subject_name}' saved.")

# Using OpenCV to add metrics to images
def add_metric_to_image_cv2(url, metric):
    output_folder = "action_images_with_metrics"
    os.makedirs(output_folder, exist_ok=True)

    response = requests.get(url)
    image_data = np.asarray(bytearray(response.content), dtype="uint8")
    img = cv2.imdecode(image_data, cv2.IMREAD_COLOR)

    font_scale = min(img.shape[1], img.shape[0]) / 800
    font_thickness = 2
    text_size = cv2.getTextSize(metric, cv2.FONT_HERSHEY_SIMPLEX, font_scale, font_thickness)[0]
    x = (img.shape[1] - text_size[0]) // 2
    y = img.shape[0] - text_size[1] - 20

    cv2.putText(img, metric, (x, y), cv2.FONT_HERSHEY_SIMPLEX, font_scale, (255, 255, 255), font_thickness)
    cv2.imwrite(os.path.join(output_folder, f"action_image_with_metric_{metric.replace(' ', '_')}.png"), img)
    print(f"Image with metric '{metric}' saved.")

# Function to create an image based on user topic using fal_client
def create_topic_image(topic):
    def on_queue_update(update):
        if isinstance(update, fal_client.InProgress):
            for log in update.logs:
                print(log["message"])

    result = fal_client.subscribe(
        "fal-ai/recraft-v3",
        arguments={"prompt": topic},
        with_logs=True,
        on_queue_update=on_queue_update,
    )
    return result['images'][0]['url']

# Function to convert image to a short video clip
def create_short_video_from_image(image_url, output_path, duration=0.1):
    response = requests.get(image_url)
    image_data = np.asarray(bytearray(response.content), dtype="uint8")
    img = cv2.imdecode(image_data, cv2.IMREAD_COLOR)
    cv2.imwrite("temp_image.png", img)
    
    clip = ImageClip("temp_image.png").set_duration(duration)
    clip.write_videofile(output_path, fps=24)

# Function to add pan and zoom effect on individual images
def add_pan_zoom_effect(image_path, duration=1.5, zoom_factor=1.1):
    clip = ImageClip(image_path).set_duration(duration)
    w, h = clip.size
    new_w, new_h = int(w * zoom_factor), int(h * zoom_factor)

    zoomed_clip = clip.resize(newsize=(new_w, new_h))

    def pan_zoom(get_frame, t):
        frame = get_frame(t)
        h, w, _ = frame.shape
        x_shift = int((new_w - w) * (t / duration))
        y_shift = int((new_h - h) * (t / duration))
        return frame[y_shift:y_shift + h, x_shift:x_shift + w]

    return zoomed_clip.fl(pan_zoom)

# Function to create alternating final video
def create_alternating_video(casual_folder, action_folder, output_video_path, duration=1.5):
    clips = []
    casual_images = sorted([f for f in os.listdir(casual_folder) if f.endswith((".png", ".jpg", ".jpeg"))])
    action_images = sorted([f for f in os.listdir(action_folder) if f.endswith((".png", ".jpg", ".jpeg"))])
    
    for casual_img, action_img in zip(casual_images, action_images):
        casual_path = os.path.join(casual_folder, casual_img)
        action_path = os.path.join(action_folder, action_img)
        
        casual_clip = add_pan_zoom_effect(casual_path, duration)
        action_clip = add_pan_zoom_effect(action_path, duration)
        
        clips.append(casual_clip)
        clips.append(action_clip)

    final_video = concatenate_videoclips(clips, method="compose")
    final_video.write_videofile(output_video_path, codec="libx264", fps=24)

# Function to add audio to video
def add_audio_to_video(video_path, audio_path, output_path):
    video = VideoFileClip(video_path)
    audio = AudioFileClip(audio_path)

    if audio.duration > video.duration:
        audio = audio.subclip(0, video.duration)

    video = video.set_audio(audio)
    video.write_videofile(output_path, codec="libx264", audio_codec="aac")
    video.close()
    audio.close()

# Main script execution
topic = input("Enter the topic ")
num_frames = input("Please enter 5 or 10 ")
casual_subjects = []
action_subjects = []

# Generate text and images based on topic and frames
final_object = generate_text(topic, num_frames)
print(final_object)

subjects = list(final_object.keys())
metrics = list(final_object.values())

subjects.reverse()
metrics.reverse()

final_casual_subjects = generate_casual_image(subjects, casual_subjects)
final_action_subjects = generate_action_image(subjects, action_subjects)

for i, (url, subject) in enumerate(zip(final_casual_subjects, subjects), start=1):
    add_number_and_name_to_image_cv2(url, i, subject)

for url, metric in zip(final_action_subjects, metrics):
    add_metric_to_image_cv2(url, metric)

# Create topic image and short video
topic_image_url = create_topic_image(topic)
create_short_video_from_image(topic_image_url, "intro_video.mp4", duration=0.3)

# Create final video with pan and zoom effects
casual_images_folder = "images_with_text"
action_images_folder = "action_images_with_metrics"
create_alternating_video(casual_images_folder, action_images_folder, "main_video.mp4", duration=1.5)

# Concatenate intro video with main video
intro_video = VideoFileClip("intro_video.mp4")
main_video = VideoFileClip("main_video.mp4")
final_compiled_video = concatenate_videoclips([intro_video, main_video], method="compose")
final_compiled_video.write_videofile("final_compiled_video_with_intro.mp4", codec="libx264", fps=24)

# Add audio to final video
add_audio_to_video("final_compiled_video_with_intro.mp4", "sample.mp3", "final_video_with_audio.mp4")

print("Final Video with Audio created")
