import fal_client
import asyncio




def on_queue_update(update):
    if isinstance(update, fal_client.InProgress):
        for log in update.logs:
           print(log["message"])

def create_image(prompt):
    result = fal_client.subscribe(
        "fal-ai/recraft-v3",
        arguments={
            "prompt": prompt
        },
        with_logs=True,
        on_queue_update=on_queue_update,
    )

    image_url = result['images'][0]['url']
    print("Image URL:", image_url)
    return image_url

# Function to create a video from the image URL
async def image_to_video(image_url):
    # Submit the request to create the video
    handler = await fal_client.submit_async(
        "fal-ai/kling-video/v1/standard/image-to-video",
        arguments={
            "prompt": "Add motion to the image",
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



#Calling all functions
background_extra = "create an image where at the top there is a text with white background saying "
underneath_extra = "And underneath is an image of "
text = input("Enter text which will be written on the video")
image_text = input("How do you want your video to look like?")
prompt= background_extra+ text+ underneath_extra+ image_text
image_url = create_image(prompt)
print("The image url is ", image_url)


# Run the image_to_video function and retrieve the video URL
video_url, video_response = asyncio.run(image_to_video(image_url))
print("The final video URL is:", video_url)
print("The full response object is:", video_response)


#Final Logs
'''
Current Status: InProgress(logs=[])
Request is currently running...
Current Status: Completed(logs=[], metrics={'inference_time': 271.5913758277893})
Request completed.
Video URL: https://v3.fal.media/files/elephant/hpGcOZAwT3PSh3o9cHEYO_output.mp4
The final video URL is: https://v3.fal.media/files/elephant/hpGcOZAwT3PSh3o9cHEYO_output.mp4
The full response object is: {'video': {'url': 'https://v3.fal.media/files/elephant/hpGcOZAwT3PSh3o9cHEYO_output.mp4', 'content_type': 'video/mp4', 'file_name': 'output.mp4', 'file_size': 6237389}}
'''


#Also accept aspect ratio from user

