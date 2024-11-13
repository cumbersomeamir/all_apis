from flask import Flask, request, jsonify
import requests

app = Flask(__name__)

external_ip = os.getenv("EXTERNAL_IP", "34.123.67.37")

@app.route('/video-story-didyouknow', methods=['POST'])
def video_story_proxy():
    # Default value for num_frames
    default_num_frames = 4
    injection = " Give Did you know style responses about "
    
    # Get JSON data from the request
    data = request.get_json()
    
    # Ensure the 'topic' field is present
    if not data or 'topic' not in data:
        return jsonify({"error": "Missing 'topic' parameter"}), 400

    # Add the injection to the topic
    topic_with_injection = data['topic'] + injection
    num_frames = data.get('num_frames', default_num_frames)

    # Prepare the request payload with injected topic
    url = f"http://{external_ip}:7004/video-story"
    headers = {"Content-Type": "application/json"}
    payload = {
        "topic": topic_with_injection,
        "num_frames": num_frames
    }

    # Send the request to the original API and capture the response
    response = requests.post(url, headers=headers, json=payload)
    
    # Check for successful response and return JSON or handle error
    if response.status_code == 200:
        return jsonify(response.json()), 200
    else:
        # Log for debugging and return error response
        print("Error Response:", response.status_code, response.text)
        return jsonify({"error": "Failed to retrieve data", "status_code": response.status_code, "details": response.text}), response.status_code

# Run the Flask app on port 7029
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=7029)
