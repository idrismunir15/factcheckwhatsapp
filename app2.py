from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import requests
import os
from dotenv import load_dotenv
from pyshorteners import Shortener

load_dotenv()

app = Flask(__name__)

# External API endpoint
EXTERNAL_API_URL = "https://myapiprojects-production.up.railway.app/api/user-input/"

# Twilio Credentials
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
shortener = Shortener()

@app.route("/")
def hello():
    return "Welcome to myaifactchecker.org"

@app.route("/message_status", methods=["POST", "GET"])
def message_status():
    message_sid = request.values.get("MessageSid")
    message_status = request.values.get("MessageStatus")
    print(f"Message {message_sid} status: {message_status}")
    return "", 204

@app.route("/whatsapp", methods=["POST", "GET"])
def whatsapp_reply():
    incoming_message = request.form.get("Body", "").strip()
    sender_number = request.form.get("From")
    
    response_data = handle_user_input(incoming_message)
    
    try:
        if response_data.get("use_template", False):
            # Send message using template
            message = client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=sender_number,
                content=None,  # Must be None when using templates
                template=dict(
                    name=response_data["template_name"],
                    language=dict(code=response_data["language_code"]),
                    components=response_data["components"]
                )
            )
        else:
            # Send regular message
            message = client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=sender_number,
                body=response_data["body"]
            )
            
        return jsonify({"status": "success", "message_sid": message.sid})
    except Exception as e:
        print(f"Error sending message: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_user_input(incoming_message):
    if incoming_message.lower() in ["thumbs_up", "thumbs_down", "👍 like", "👎 dislike"]:
        return {
            "body": "Thank you for your feedback! 🙏",
            "use_template": False
        }
    else:
        # Get response from external API
        api_result = call_external_api(incoming_message)
        
        # Format the response using a template
        return {
            "use_template": True,
            "template_name": "fact_check_result",  # Your approved template name
            "language_code": "en",  # Language code
            "components": [
                {
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": api_result['message']}
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "0",
                    "parameters": [
                        {"type": "text", "text": "👍 Like"}
                    ]
                },
                {
                    "type": "button",
                    "sub_type": "quick_reply",
                    "index": "1",
                    "parameters": [
                        {"type": "text", "text": "👎 Dislike"}
                    ]
                }
            ]
        }

def call_external_api(user_query):
    try:
        payload = {"user_input": user_query}
        response = requests.post(EXTERNAL_API_URL, json=payload, timeout=30)
        response.raise_for_status()
        
        data = response.json()
        if 'result' in data:
            return {'message': data['result']}
        else:
            return {'message': "Unexpected API response format.", 'status': 'error'}
    
    except requests.exceptions.Timeout:
        return {'message': "Request timed out.", 'status': 'error'}
    except requests.exceptions.RequestException as e:
        return {'message': f"Connection error: {e}", 'status': 'error'}
    except Exception as e:
        return {'message': f"An error occurred: {e}", 'status': 'error'}

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
