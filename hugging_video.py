import os
import boto3
from PIL import Image
import requests
from io import BytesIO
import asyncio
import fal_client

# AWS credentials and S3 bucket details from environment variables
aws_access_key = os.getenv("AWS_ACCESS_KEY")
aws_secret_key = os.getenv("AWS_SECRET_KEY")
s3_bucket_name = os.getenv("S3_BUCKET_NAME")
aws_region = os.getenv("AWS_REGION")  # e.g., 'us-east-1'

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

def combine_images_and_upload(url1, url2):
    # Load images from URLs
    response1 = requests.get(url1)
    response2 = requests.get(url2)
    img1 = Image.open(BytesIO(response1.content))
    img2 = Image.open(BytesIO(response2.content))
    
    # Ensure both images are RGBA to handle transparency
    img1 = img1.convert("RGBA")
    img2 = img2.convert("RGBA")
    
    # Create a new image with a transparent background for horizontal layout
    width = img1.width + img2.width
    height = max(img1.height, img2.height)
    combined_image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    
    # Paste images side by side
    combined_image.paste(img1, (0, 0))
    combined_image.paste(img2, (img1.width, 0))
    
    # Save the combined image locally
    combined_image_path = "combined_image.png"
    combined_image.save(combined_image_path, "PNG")
    
    # Upload to S3
    s3_filename = "combined_image.png"
    combined_image_url = upload_file_to_s3(combined_image_path, s3_bucket_name, s3_filename)
    
    return combined_image_url

# Function to create a video from the image URL
async def image_to_video(image_url):
    # Submit the request to create the video
    handler = await fal_client.submit_async(
        "fal-ai/kling-video/v1/standard/image-to-video",
        arguments={
            "prompt": "there are two people in the image, make them hug",
            "image_url": image_url
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
    

combined_image_url = combine_images_and_upload("https://img.freepik.com/free-photo/handsome-confident-smiling-man-with-hands-crossed-chest_176420-18743.jpg", "https://media.istockphoto.com/id/1388206850/photo/beauty-woman-face-skin-care-beautiful-woman-portrait-with-full-lips-and-long-eyelashes-over.jpg?s=612x612&w=0&k=20&c=zHWXRNO8DcLUYaII_T3oS5iu6FElv1ibLQHRQQXlj2Q=")


'''
combined_image_url= "https://mygenerateddatabucket.s3.eu-north-1.amazonaws.com/combined_image.png"
'''
# Run the image_to_video function and retrieve the video URL
video_url, video_response = asyncio.run(image_to_video(combined_image_url))
print("The final video URL is:", video_url)
print("The full response object is:", video_response)


'''
Request completed.
Video URL: https://v3.fal.media/files/tiger/d-0bN21MyFE17XCu9wgVZ_output.mp4
The final video URL is: https://v3.fal.media/files/tiger/d-0bN21MyFE17XCu9wgVZ_output.mp4
The full response object is: {'video': {'url': 'https://v3.fal.media/files/tiger/d-0bN21MyFE17XCu9wgVZ_output.mp4', 'content_type': 'video/mp4', 'file_name': 'output.mp4', 'file_size': 6167904}}
'''

#Subjects are not hugging change prompt
