from flask import Flask, request, redirect, Response
#from flask_ngrok import run_with_ngrok 
#from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import requests
import time
from dotenv import load_dotenv
import os
import json
import sqlite3
from datetime import datetime, timedelta
#from pyshorteners import Shortener


#s = Shortener()

load_dotenv()

app = Flask(__name__)

# External API endpoint
EXTERNAL_API_URL = "https://www.myaifactchecker.org/api/factcheck/"

# Twilio Credentials
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # Replace with your Twilio WhatsApp number
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")        # Replace with your Account SID
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")            # Replace with your Auth Token

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


# Your Account SID and Auth Token from twilio.com/console
account_sid = TWILIO_ACCOUNT_SID
auth_token = TWILIO_AUTH_TOKEN
client = Client(account_sid, auth_token)

# The phone number of the WhatsApp user
#to_whatsapp_number = 'whatsapp:+2347086584615'
# Your Twilio WhatsApp number
from_whatsapp_number = 'whatsapp:+18434381502'

conn = sqlite3.connect('users.db')
c = conn.cursor()

#Create a database
def create_db():
    # Create table to store user information
    c.execute('''CREATE TABLE IF NOT EXISTS users
                (whatsapp_id TEXT PRIMARY KEY, conversation_sid TEXT, last_message_time DATETIME)''')
    conn.commit()


#Check User: Determine if the user is new or needs a new conversation due to the 24-hour rule.
def check_user(whatsapp_id):
    c.execute("SELECT * FROM users WHERE whatsapp_id = ?", (whatsapp_id,))
    user = c.fetchone()
    
    if not user:
        return "new", None
    else:
        last_message_time = datetime.strptime(user[2], '%Y-%m-%d %H:%M:%S')
        if datetime.now() - last_message_time > timedelta(hours=24):
            return "refresh", user[1]  # User exists but conversation needs refresh
        return "existing", user[1]  # User exists, conversation continues


def update_user(whatsapp_id, conversation_sid):
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    c.execute("INSERT OR REPLACE INTO users (whatsapp_id, conversation_sid, last_message_time) VALUES (?, ?, ?)",
              (whatsapp_id, conversation_sid, now))
    conn.commit()
    

#Create or Retrieve Conversation:
def handle_conversation(whatsapp_id):
    user_status, old_conversation_sid = check_user(whatsapp_id)
    
    if user_status == "new" or user_status == "refresh":
        # Create new conversation
        conversation = client.conversations.v1.conversations.create(
            friendly_name=f"Chat with {whatsapp_id}"
        )
        conversation_sid = conversation.sid
        
        # Add WhatsApp participant to the new conversation
        participant = client.conversations.v1.conversations(conversation_sid) \
            .participants \
            .create(
                identity=whatsapp_id,
                proxy_address=from_whatsapp_number,
                address=whatsapp_id
            )
        
        update_user(whatsapp_id, conversation_sid)
        print(f"New conversation created with SID: {conversation_sid}")
        return conversation_sid
    else:
        # Use existing conversation
        print(f"Continuing conversation with SID: {old_conversation_sid}")
        return old_conversation_sid


#handle webhook message

@app.route('/whatsapp', methods=['POST'])
def whatsapp_webhook():
    
    whatsapp_id = request.form.get('From')
    conversation_sid = handle_conversation(whatsapp_id)
    
    # Process the message
    payload= {"user_input": request.form.get('Body')}
    headers = {"Content-Type": "application/json"}

    try:
        # Making the API call
        response = requests.post(EXTERNAL_API_URL, headers=headers, json=payload)
        response.raise_for_status()  # Will raise an HTTPError if the HTTP request returned an unsuccessful status code
        
        # Process the response from the API if needed
        api_response = response.json()
        # Example: If the API returns a message to send back
        if 'response' in api_response:
            # Send the message back to the Twilio conversation
            client.conversations.v1.conversations(conversation_sid) \
                .messages \
                .create(
                    #author="YourSystem",
                    body=api_response['response']
                )
        
        print(f"API response: {api_response}")
    except requests.RequestException as e:
        # Log the error or handle it as needed
        print(f"API call failed: {e}")
        # Optionally, send an error message to the user
        client.conversations.v1.conversations(conversation_sid) \
            .messages \
            .create(
                #author="YourSystem",
                body="Sorry, there was an issue processing your request."
            )

    return Response(status=200)

if __name__ == "__main__":
    app.run(debug=True, port=5000)
