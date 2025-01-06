#Flask WhatsApp Chat Application with Session Management

from flask import Flask, request, jsonify, session
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import requests
import os
import json
from dotenv import load_dotenv
from pyshorteners import Shortener
from datetime import datetime, timedelta
import redis
from redis.connection import ConnectionPool
from redis.retry import Retry
from redis.backoff import ExponentialBackoff
from redis.exceptions import ConnectionError, TimeoutError
import logging
import ssl

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET_KEY")

# Redis configuration with SSL
REDIS_URL = os.getenv("REDIS_URL")
retry = Retry(ExponentialBackoff(), 3)

# Create SSL context
ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
ssl_context.check_hostname = False
ssl_context.verify_mode = ssl.CERT_NONE

# Create a connection pool with SSL settings
redis_pool = ConnectionPool.from_url(
    REDIS_URL,
    max_connections=10,
    socket_timeout=5,
    socket_connect_timeout=2,
    retry_on_timeout=True,
    retry=retry,
    ssl=True,
    ssl_cert_reqs=None  # Don't verify SSL certificates
)

# Initialize global Redis client
redis_client = redis.Redis(connection_pool=redis_pool, decode_responses=True)

# External API endpoint
EXTERNAL_API_URL = os.getenv("EXTERNAL_API")

# Twilio Credentials
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
shortener = Shortener()

class ChatSession:
    def __init__(self, sender_number):
        self.sender_number = sender_number
        self.last_activity = datetime.now()
        self.conversation_history = []
        
    def to_dict(self):
        return {
            'sender_number': self.sender_number,
            'last_activity': self.last_activity.isoformat(),
            'conversation_history': self.conversation_history
        }
    
    @staticmethod
    def from_dict(data):
        session = ChatSession(data['sender_number'])
        session.last_activity = datetime.fromisoformat(data['last_activity'])
        session.conversation_history = data['conversation_history']
        return session

def get_chat_session(sender_number):
    """Retrieve or create a new chat session for the sender"""
    session_key = f"chat_session:{sender_number}"
    session_data = redis_client.get(session_key)
    
    if session_data:
        # Convert JSON string to dictionary and create ChatSession object
        session_dict = eval(session_data)  # Note: In production, use proper JSON parsing
        session = ChatSession.from_dict(session_dict)
    else:
        session = ChatSession(sender_number)
    
    return session

def save_chat_session(session):
    """Save chat session to Redis"""
    session_key = f"chat_session:{session.sender_number}"
    redis_client.setex(
        session_key,
        timedelta(hours=24),  # Session expires after 24 hours of inactivity
        str(session.to_dict())
    )

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
    
    # Get or create chat session for this sender
    chat_session = get_chat_session(sender_number)
    
    # Update last activity
    chat_session.last_activity = datetime.now()
    
    # Add incoming message to conversation history
    chat_session.conversation_history.append({
        'timestamp': datetime.now().isoformat(),
        'message': incoming_message,
        'type': 'incoming'
    })
    
    # Handle the message
    response_data = handle_user_input(incoming_message, chat_session)
    
    # Add response to conversation history
    chat_session.conversation_history.append({
        'timestamp': datetime.now().isoformat(),
        'message': response_data.get('body', ''),
        'type': 'outgoing'
    })
    
    # Save updated session
    save_chat_session(chat_session)
    
    try:
        # Send message
        message = client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=sender_number,
            body=response_data.get('body', '')
        )
        
        return jsonify({"status": "success", "message_sid": message.sid})
    except Exception as e:
        print(f"Error sending message: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

def handle_user_input(incoming_message, chat_session):
    if incoming_message.lower() in ["thumbs_up", "thumbs_down", "👍 like", "👎 dislike"]:
        return {
            "body": "Thank you for your feedback! 🙏"
        }
    else:
        # Get response from external API
        api_result = call_external_api(incoming_message, chat_session)
        
        return {
            "body": api_result['message']
        }

def call_external_api(user_query, chat_session):
    try:
        # Include conversation history in API call if needed
        payload = {
            "user_input": user_query,
            #"conversation_history": chat_session.conversation_history[-5:]  # Send last 5 messages for context
        }
        
        response = requests.post(EXTERNAL_API_URL, json=payload, timeout=60)
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
