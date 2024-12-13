from flask import Flask, request, jsonify
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse
import requests
import os
from datetime import datetime, timedelta
from pyshorteners import Shortener

from dotenv import load_dotenv
load_dotenv()

app = Flask(__name__)
s = Shortener()
# External API endpoint
EXTERNAL_API_URL = "https://www.myaifactchecker.org/api/factcheck/"

# Twilio Credentials
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # Replace with your Twilio WhatsApp number
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")        # Replace with your Account SID
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")            # Replace with your Auth Token

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
conversation = client.conversations.v1.conversations.create()
CONVERSATION_SID = conversation.sid # Replace with your Twilio Conversation SID

# Route to handle incoming WhatsApp messages
user_sessions= {}
@app.route("/", methods=["POST"])
def home():
    return "Welcome to Factcheck"
    
@app.route("/whatsapp", methods=["POST", "GET"])
def whatsapp_reply():
    incoming_message = request.form.get("Body").strip()
    sender_number = request.form.get("From")
    current_time = datetime.now()

    print(incoming_message)
    # Check if user is in session
    if sender_number not in user_sessions or (
        sender_number in user_sessions and
        current_time - user_sessions[sender_number]["last_active"] > timedelta(minutes=60)
    ):
        # New user or timed-out session
        user_sessions[sender_number] = {
            "name": None,
            "state": "getting_name",
            "last_active": current_time
        }
        response_text = "Hi! 👋 Welcome to Myaifactcheker. Could you please tell us your name?"
    else:
        # Existing session
        session = user_sessions[sender_number]
        session["last_active"] = current_time  # Update activity timestamp

        if session["state"] == "getting_name":
            # Save the user's name
            user_sessions[sender_number]["name"] = incoming_message
            user_sessions[sender_number]["state"] = "main_menu"
            response_text = (
                f"Nice to meet you, {incoming_message}! 👋\n\n"
                "👉 What would you like to do?\n"
                "✅ Verify a Claim (Type 1)\n"
                "💬 Give Feedback (Type 2)"
            )
        elif session["state"] == "main_menu":
            # Handle user choices
            if incoming_message == "1" or incoming_message == "✅":
                response_text = "Great! Please input your claim."
                user_sessions[sender_number]["state"] = "verifying_claim"
            elif incoming_message == "2" or incoming_message == "💬":
                response_text = "Thank you for choosing to provide feedback! Please share your thoughts."
                user_sessions[sender_number]["state"] = "awaiting_feedback"
            else:
                response_text = (
                    "I didn't understand your response. Please choose:\n"
                    "✅ Verify a Claim (Type 1)\n"
                    "💬 Give Feedback (Type 2)"
                )
        elif session["state"] == "verifying_claim":
            # Process claim
            result = call_external_api(incoming_message)  # Replace with actual API call logic
            response_text = (
                f"{result['message']}\n\n"
                "👉 Would you like to do something else?\n"
                "✅ Verify another Claim (Type 1)\n"
                "💬 Give Feedback (Type 2)"
            )
            user_sessions[sender_number]["state"] = "main_menu"
        elif session["state"] == "awaiting_feedback":
            # Handle feedback
            response_text = "Thank you for your feedback! We appreciate your input. 🙏"
            user_sessions[sender_number]["state"] = "main_menu"

    # Send response to the user
    try:
        message = client.messages.create(
            body=response_text,
            from_=TWILIO_WHATSAPP_NUMBER,
            to=sender_number
        )
        
        
        print(f"Message SID: {message.sid}")
        response = {"status": "success", "message_sid": message.sid}
    except Exception as e:
        print(f"Error sending message: {e}")
        response = {"status": "error", "message": str(e)}

    return jsonify(response)
# Function to call external API
def call_external_api(user_query):
    try:
        payload = {"user_input_news": user_query}
        headers = {"Content-Type": "application/json"}
        
        # Make the POST request to the external API
        response = requests.post(EXTERNAL_API_URL, json=payload, timeout=300)
        

        # Check for a successful response
        if response.status_code in (200, 201): 
            data = response.json() 

            #convert links to shortlinks
            url1=[s.tinyurl.short(url) for url in data['genuine_urls']]
            url2=[s.tinyurl.short(url) for url in data['non_authentic_urls']]
            
            url=""
            if len(url1)!=0:
                url1.extend(url2)
                url="SOURCES \n" + "\n".join(url1)
                
        
            if 'fresult' in data:
              return {'message': data['fresult']+ "\n\n"  + url, 'status': 'success'}  # Return a dictionary
            else:
              return {'message': "Unexpected API response format.", 'status': 'error'}
        else:
            return {'message': "I am unable to answer your query. Please rephrase and try again.", 'status': 'error'}

    except requests.exceptions.Timeout:
        return {'message': "Request timed out.", 'status': 'error'}
    except requests.exceptions.RequestException as e:
        return {'message': f"Connection error: {e}", 'status': 'error'}
    except Exception as e:  # Catch other unexpected errors
        return {'message': f"An error occurred: {e}", 'status': 'error'}

if __name__ == "__main__":
    app.run(debug=True)
