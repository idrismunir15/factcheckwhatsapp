from flask import Flask, request, jsonify, session
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import requests
import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
import redis
from urllib.parse import urlparse
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET_KEY")

# Redis configuration with SSL
url = urlparse(os.environ.get("REDIS_URL"))
redis_client = redis.Redis(host=url.hostname, port=url.port, password=url.password, ssl=(url.scheme == "rediss"), ssl_cert_reqs=None)

# External API endpoint
EXTERNAL_API_URL = os.getenv("EXTERNAL_API")

# Twilio Credentials
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

class ChatSession:
    def __init__(self, sender_number):
        self.sender_number = sender_number
        self.last_activity = datetime.now()
        self.conversation_history = []
        self.last_message_id = None
        self.is_new_session = True
        
    def to_dict(self):
        """Convert session to a JSON-serializable dictionary"""
        return {
            "sender_number": self.sender_number,
            "last_activity": self.last_activity.isoformat(),
            "conversation_history": self.conversation_history,
            "last_message_id": self.last_message_id,
            "is_new_session": self.is_new_session
        }
    
    @staticmethod
    def from_dict(data):
        """Create session from a dictionary"""
        session = ChatSession(data["sender_number"])
        session.last_activity = datetime.fromisoformat(data["last_activity"])
        session.conversation_history = data["conversation_history"]
        session.last_message_id = data.get("last_message_id")
        session.is_new_session = False
        return session

def get_chat_session(sender_number):
    """Retrieve or create a new chat session for the sender"""
    session_key = f"chat_session:{sender_number}"
    try:
        session_data = redis_client.get(session_key)
        
        if session_data:
            # Properly decode bytes to string and parse JSON
            session_dict = json.loads(session_data.decode('utf-8'))
            session = ChatSession.from_dict(session_dict)
            
            # Check if session is expired (>24 hours)
            last_activity = datetime.fromisoformat(session_dict["last_activity"])
            if datetime.now() - last_activity > timedelta(hours=24):
                logger.info(f"Session expired for {sender_number}")
                session = ChatSession(sender_number)
        else:
            logger.info(f"Creating new session for {sender_number}")
            session = ChatSession(sender_number)
        
        return session
        
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding session data: {e}")
        return ChatSession(sender_number)
    except Exception as e:
        logger.error(f"Error getting chat session: {e}")
        return ChatSession(sender_number)

def save_chat_session(session):
    """Save chat session to Redis"""
    try:
        session_key = f"chat_session:{session.sender_number}"
        session_data = json.dumps(session.to_dict())
        redis_client.setex(
            session_key,
            timedelta(hours=24),
            session_data
        )
    except Exception as e:
        logger.error(f"Error saving chat session: {e}")

def get_greeting_message():
    """Returns appropriate greeting based on time of day"""
    hour = datetime.now().hour
    if 5 <= hour < 12:
        return "Good morning! 🌅"
    elif 12 <= hour < 17:
        return "Good afternoon! 🌞"
    else:
        return "Good evening! 🌙"

def create_welcome_message():
    """Creates a welcome message for new users or returning users after 24h"""
    greeting = get_greeting_message()
    return (
        f"{greeting} Welcome to AI Fact Checker! 🤖✨\n\n"
        "I'm here to help you verify information and check facts. "
        "Feel free to ask me any questions or share statements you'd like to fact-check.\n\n"
        "To get started, simply type your question or statement! 📝"
    )

def store_feedback(message_id, feedback_type, sender_number):
    """Store user feedback in Redis"""
    try:
        feedback_key = f"feedback:{message_id}"
        feedback_data = {
            "timestamp": datetime.now().isoformat(),
            "feedback_type": feedback_type,
            "sender_number": sender_number
        }
        redis_client.setex(
            feedback_key,
            timedelta(days=30),
            json.dumps(feedback_data)
        )
    except Exception as e:
        logger.error(f"Error storing feedback: {e}")

def is_casual_statement(response_text):
    """
    Determine if the response is a casual statement that doesn't need feedback
    """
    casual_indicators = ["Thank you", "You're welcome", "Got it", "I understand", "Thanks for", "Noted", "👍",   "🙏", "Please", "Ok"]
    
    # Check if the response is short and contains casual indicators
    is_short = len(response_text.split()) < 10
    has_casual_words = any(indicator.lower() in response_text.lower() 
                          for indicator in casual_indicators)
    
    return is_short and (has_casual_words or response_text.endswith(('!', '👋', '🙂', '😊'))
                         
def send_message_with_template(to_number, body_text, is_greeting=False):
    """Send message with or without template based on message type"""
    try:
        # First send the main message
        main_message = client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=to_number,
            body=body_text
        )
        
        # If it's not a greeting and not a casual statement, send the template
        if not is_greeting and not is_casual_statement(body_text):
            template_message = client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=to_number,
                body="Was this response helpful?",
                content_sid=os.getenv("TWILIO_TEMPLATE_SID")
            )
            return template_message  # Return the template message for tracking feedback
        return main_message
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        raise

@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    try:
        incoming_message = request.form.get("Body", "").strip()
        sender_number = request.form.get("From")
        
        # Get or create chat session for this sender
        chat_session = get_chat_session(sender_number)
        
        # Check if this is a button response
        button_text = request.form.get("ButtonText")
        if button_text:
            is_feedback, message_sid = handle_button_response(button_text, chat_session, sender_number)
            if is_feedback:
                return jsonify({"status": "success", "message_sid": message_sid})
        
        # Send welcome message for new sessions
        if chat_session.is_new_session:
            welcome_message = send_message_with_template(
                sender_number,
                create_welcome_message(),
                is_greeting=True
            )
            
            chat_session.conversation_history.append({
                "timestamp": datetime.now().isoformat(),
                "message": create_welcome_message(),
                "type": "outgoing",
                "message_id": welcome_message.sid
            })
        
        # Add incoming message to conversation history
        chat_session.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "message": incoming_message,
            "type": "incoming"
        })
        
        # Get response from API
        api_response = call_external_api(incoming_message, chat_session)
        response_text = api_response.get("message", "")
        
        # Send main response and template (if needed)
        message = send_message_with_template(sender_number, response_text)
        
        # Store the message ID for feedback
        chat_session.last_message_id = message.sid
        
        # Add response to conversation history
        chat_session.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "message": response_text,
            "type": "outgoing",
            "message_id": message.sid
        })
        
        # Update last activity and save session
        chat_session.last_activity = datetime.now()
        save_chat_session(chat_session)
        
        return jsonify({"status": "success", "message_sid": message.sid})
    except Exception as e:
        logger.error(f"Error in whatsapp_reply: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500
