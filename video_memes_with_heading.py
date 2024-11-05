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

        # Continuously check the status until it's completed
    while True:
        status = await fal_client.status_async("fal-ai/kling-video/v1/standard/text-to-video", request_id, with_logs=True)
        print(f"Current Status: {status}")  # Print the status object for debugging
        
        # Check for various possible status states
        if hasattr(status, "status") and status.status == "completed":
            break
        elif hasattr(status, "status") and status.status == "failed":
            raise Exception("Request failed.")
        elif hasattr(status, "status") and status.status == "queued":
            print("Request is still in queue...")
        elif hasattr(status, "status") and status.status == "running":
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
