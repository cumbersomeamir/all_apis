'''
Recipe:
1. Accept top 5 or top 10 and the topic
2. 3. According to the topic generate 10 words (subject of the topic) and also get the discrete number metric for each topic. Get it in the form of an object like {'subject1': 'metric1', 'subject2': 'metric2', and so on
3. Generate 2 images about the same subject. 1 can be the subject in a casual setting and the other can be the subject relating to the topic. Save both in 2 different list casual_subject , action_subject
4. Insert a text in the middle a bit above for numbering all casual_subject list will go from 1 top 5 or 10
5. Insert the text metrics on drop_subjects list similar location

6. Convert Image to Videos (extending by 1.5s each), and join all videos sequentially

7. Insert audio (given)

'''
#Importing all libraries
import openai
import os
import json
import ast
from PIL import Image, ImageDraw, ImageFont
import requests
from io import BytesIO

#Accepting all environment variables
openai_api_key = os.getenv("OPENAI_API_KEY")


# Initialize the OpenAI client
client = openai.OpenAI(api_key=openai_api_key)





#Defining Azure file upload to s3 helper function
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

#Generating 10 subject words and 10 respective metric using OpenAI GPT40 API
def generate_text(topic, num_frames):

    
        completion = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You generate an object only according to topic"},
                {"role": "user", "content": f"This is the topic {topic}. We are making top {num_frames} list." + " In this list there is a subject and there is a respective discrete (number) metric. For example, if the topic is fastest animals the subjects will be Cheetah, Tiger, Deer and so on and the metrics will be there top speed. So you have to finally only return an object which looks like {'Cheetah' : 'Top Speed : 110', 'Tiger': 'Top Speed : 90'} and so on. Make sure the subject have max two words and the metric is preferably a number, specific and trustable. Please only return the final object and nothing else "}
            ]
        )
        response = completion.choices[0].message.content
        return ast.literal_eval(response)
        


def generate_casual_image(subjects, casual_subjects):
    for subject in subjects:
        # Function to generate image

        resp = client.images.generate(
            model="dall-e-3",
            prompt= f"Create a realistic image of this {subject} in natural location",
            n=1,
            size="1024x1024"
        )
        image_url = resp.data[0].url
        print("The image url is ", image_url)
        casual_subjects.append(image_url)
        
    return casual_subjects
        

def generate_action_image(subjects, action_subjects):
    for subject in subjects:
        # Function to generate image

        resp = client.images.generate(
            model="dall-e-3",
            prompt= f"Create a realistic image of this {subject} in action",
            n=1,
            size="1024x1024"
        )
        image_url = resp.data[0].url
        print("The image url is ", image_url)
        action_subjects.append(image_url)
        
    return action_subjects
        


def add_number_to_image(url, number):
    # Create folder if it doesn't exist
    output_folder = "images_with_text"
    os.makedirs(output_folder, exist_ok=True)

    response = requests.get(url)
    img = Image.open(BytesIO(response.content))

    # Font size
    font_size = int(min(img.size) * 0.15)  # Adjust to desired size
    font = ImageFont.truetype("ARIAL.TTF", font_size)

    draw = ImageDraw.Draw(img)

    # Text to be added
    text = f"{number}."

    # Calculate text position for centering
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width, text_height = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (img.width - text_width) / 2
    y = (img.height * 0.25) - (text_height / 2)  # Adjust position if needed

    # Draw the main text in white without any background
    draw.text((x, y), text, font=font, fill="white")

    # Save image in the output folder
    img.save(os.path.join(output_folder, f"image_with_number_{number}.png"))


'''
#Inputs
topic = input("Enter the topic ")
num_frames = input("Please enter 5 or 10 ")
casual_subjects = []
action_subjects = []


#Calling all functions
final_object = generate_text(topic, num_frames)
print(final_object)

# Converting to subjects (keys) and metrics (values) lists
subjects = list(final_object.keys())
metrics = list(final_object.values())




subjects = ['Cheetah', 'Pronghorn Antelope']#Temporary
metrics = ['Top Speed : 110', 'Top Speed : 55'] #Temporary


final_casual_subjects = generate_casual_image(subjects, casual_subjects)
print("The final casual list is ", final_casual_subjects)
#final_action_subjects = generate_action_image(subjects, action_subjects)
'''
final_casual_subjects = ['https://oaidalleapiprodscus.blob.core.windows.net/private/org-IJLNdPbQswPXmkv4mFbx70h9/user-CAmDUFOATURBpfayYNaz0K35/img-nvq45ted76l485SI9RyBZm4F.png?st=2024-11-06T08%3A44%3A42Z&se=2024-11-06T10%3A44%3A42Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=d505667d-d6c1-4a0a-bac7-5c84a87759f8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2024-11-05T20%3A17%3A14Z&ske=2024-11-06T20%3A17%3A14Z&sks=b&skv=2024-08-04&sig=7DpTi462zUyPZWy%2Bve5kFkWr0J/qpXUMrmUFchrBwLI%3D', 'https://oaidalleapiprodscus.blob.core.windows.net/private/org-IJLNdPbQswPXmkv4mFbx70h9/user-CAmDUFOATURBpfayYNaz0K35/img-eX3t405KcPHmMTlR7yNP1upU.png?st=2024-11-06T08%3A44%3A52Z&se=2024-11-06T10%3A44%3A52Z&sp=r&sv=2024-08-04&sr=b&rscd=inline&rsct=image/png&skoid=d505667d-d6c1-4a0a-bac7-5c84a87759f8&sktid=a48cca56-e6da-484e-a814-9c849652bcb3&skt=2024-11-05T20%3A21%3A11Z&ske=2024-11-06T20%3A21%3A11Z&sks=b&skv=2024-08-04&sig=l7g1AWKP3c1YLSUtNA%2BupMkktmchln/vHli4tbFzLkI%3D']
# Iterate over each image URL and add a number
for i, url in enumerate(final_casual_subjects, start=1):
    add_number_to_image(url, i)
