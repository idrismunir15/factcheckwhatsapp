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
import speech_recognition as sr
from pydub import AudioSegment
import tempfile
import urllib.request

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv("FLASK_SECRET_KEY")

url = urlparse(os.environ.get("REDIS_URL"))
redis_client = redis.Redis(
    host=url.hostname,
    port=url.port,
    password=url.password,
    ssl=(url.scheme == "rediss"),
    ssl_cert_reqs=None
)

EXTERNAL_API_URL = os.getenv("EXTERNAL_API")
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
        return {
            "sender_number": self.sender_number,
            "last_activity": self.last_activity.isoformat(),
            "conversation_history": self.conversation_history,
            "last_message_id": self.last_message_id,
            "is_new_session": self.is_new_session
        }
    
    @staticmethod
    def from_dict(data):
        session = ChatSession(data["sender_number"])
        session.last_activity = datetime.fromisoformat(data["last_activity"])
        session.conversation_history = data["conversation_history"]
        session.last_message_id = data.get("last_message_id")
        session.is_new_session = False
        return session

def process_voice_message(media_url):
    try:
        # Create a temporary directory for audio processing
        with tempfile.TemporaryDirectory() as temp_dir:
            # Download the audio file
            audio_path = os.path.join(temp_dir, "voice.ogg")
            wav_path = os.path.join(temp_dir, "voice.wav")
            
            # Download the audio file from Twilio
            urllib.request.urlretrieve(media_url, audio_path)
            
            # Convert OGG to WAV using pydub
            audio = AudioSegment.from_ogg(audio_path)
            audio.export(wav_path, format="wav")
            
            # Initialize speech recognizer
            recognizer = sr.Recognizer()
            
            # Load the audio file and convert to text
            with sr.AudioFile(wav_path) as source:
                audio_data = recognizer.record(source)
                text = recognizer.recognize_google(audio_data)
                return text
                
    except Exception as e:
        logger.error(f"Error processing voice message: {e}")
        return None

def needs_rating(response_text):
    # Responses that don't need rating
    casual_patterns = [
        "thank you", "thanks", "you're welcome", "noted",
        "got it", "understood", "👍", "🙏", "nice","bravo","amazing","impressive",
        "sorry", "please", "hi", "hello", "hey", "good morning", "good afternoon", 
        "good evening", "thanks", "thank you", "bye", "goodbye", "cool","yeah","yah","alright",
        "oh","oops","ok"
    ]
    
    text = response_text.lower().strip()
    
    # Check conditions
    is_short = len(text.split()) < 10
    is_casual = any(pattern in text for pattern in casual_patterns)
    is_error = "error" in text or "an error occurred" in text
    has_emoji_ending = text.endswith(('!', '👋', '🙂', '😊'))
    
    return not (is_short and (is_casual or has_emoji_ending or is_error))

def get_chat_session(sender_number):
    session_key = f"chat_session:{sender_number}"
    try:
        session_data = redis_client.get(session_key)
        if session_data:
            session_dict = json.loads(session_data.decode('utf-8'))
            session = ChatSession.from_dict(session_dict)
            last_activity = datetime.fromisoformat(session_dict["last_activity"])
            if datetime.now() - last_activity > timedelta(hours=24):
                session = ChatSession(sender_number)
        else:
            session = ChatSession(sender_number)
        return session
    except Exception as e:
        logger.error(f"Error getting chat session: {e}")
        return ChatSession(sender_number)

def handle_incoming_message(sender_number, chat_session, message_type="text", content=None):
    try:
        if message_type == "voice":
            # Process voice message
            transcribed_text = process_voice_message(content)
            if not transcribed_text:
                return jsonify({
                    "status": "error",
                    "message": "Could not process voice message. Please try again."
                }), 400
            
            # Send confirmation of voice message receipt
            client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=sender_number,
                body=f"Voice message received and transcribed:\n\n\"{transcribed_text}\"\n\nProcessing your request..."
            )
            
            incoming_message = transcribed_text
        else:
            incoming_message = content

        if chat_session.is_new_session:
            welcome_message = send_message_with_template(
                sender_number,
                create_welcome_message(),
                incoming_message,
                is_greeting=True
            )
            chat_session.conversation_history.append({
                "timestamp": datetime.now().isoformat(),
                "message": create_welcome_message(),
                "type": "outgoing",
                "message_id": welcome_message.sid
            })
        
        chat_session.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "message": incoming_message,
            "type": "incoming",
            "message_type": message_type
        })
        
        api_response = call_external_api(incoming_message, chat_session)
        response_text = api_response.get("message", "I am unable to provide response now, please try your query again.")
        
        message = send_message_with_template(sender_number, response_text, incoming_message)
        chat_session.last_message_id = message.sid
        
        chat_session.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "message": response_text,
            "type": "outgoing",
            "message_id": message.sid
        })
        
        chat_session.last_activity = datetime.now()
        save_chat_session(chat_session)
        
        return jsonify({"status": "success", "message_sid": message.sid})
    
    except Exception as e:
        logger.error(f"Error handling incoming message: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500

@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    try:
        sender_number = request.form.get("From")
        chat_session = get_chat_session(sender_number)
        
        # Check for button feedback first
        button_text = request.form.get("ButtonText")
        if button_text:
            is_feedback, message_sid = handle_button_response(button_text, chat_session, sender_number)
            if is_feedback:
                return jsonify({"status": "success", "message_sid": message_sid})
        
        # Check for voice message
        num_media = int(request.form.get("NumMedia", 0))
        if num_media > 0:
            media_type = request.form.get("MediaContentType0", "")
            if media_type.startswith("audio/"):
                media_url = request.form.get("MediaUrl0")
                return handle_incoming_message(sender_number, chat_session, "voice", media_url)
        
        # Handle text message
        incoming_message = request.form.get("Body", "").strip()
        return handle_incoming_message(sender_number, chat_session, "text", incoming_message)
    
    except Exception as e:
        logger.error(f"Error in whatsapp_reply: {str(e)}")
        return jsonify({"status": "error", "message": str(e)}), 500

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
