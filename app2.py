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
EXTERNAL_API_URL = "https://myaifactchecker.org/factcheckAPI/"

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
    print(f"Message {message_sid} status: {message_status}")  # Log or store status
    return "", 204

@app.route("/whatsapp", methods=["POST", "GET"])
def whatsapp_reply():
    incoming_message = request.form.get("Body")
    sender_number = request.form.get("From")
    
    response_text = handle_user_input(incoming_message)
    
    try:
        message = client.messages.create(
            body=response_text,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=sender_number
        )
        return jsonify({"status": "success", "message_sid": message.sid})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_user_input(incoming_message):
    choices = {"💬": "2", "✅": "1"}
    if incoming_message in choices:
        return {
            "✅": "Great! Please input your claim",
            "💬": "Thank you for your feedback! Please share your thoughts."
        }[incoming_message]
    
    api_result = call_external_api(incoming_message)
    return (
        f"{api_result['message']}\n\n"
        "👉 What would you like to do next?\n"
        "✅ Verify a Claim (Type 1) \n"
        "💬 Give us Feedback (Type 2)"
    )

def call_external_api(user_query):
    try:
        payload = {"user_input": user_query}
        response = requests.post(EXTERNAL_API_URL, json=payload, timeout=30)
        response.raise_for_status()  # Will raise HTTPError for bad status codes
        
        data = response.json()
        if 'response' in data:
            return {'message': data['response']}
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
