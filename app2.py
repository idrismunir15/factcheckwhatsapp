from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import requests
from requests.exceptions import Timeout, RequestException
import os
import json
from dotenv import load_dotenv
from datetime import datetime, timedelta
import redis
from urllib.parse import urlparse
import logging
import time
from googletrans import Translator
from pydub import AudioSegment  # For processing audio files
#import speech_recognition as sr  # For transcribing voice messages
import openai
import re


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

openai.api_key = os.getenv("OPENAI_API_KEY")

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)
translator = Translator()
#recognizer = sr.Recognizer()  # Initialize the speech recognizer

class ChatSession:
    def __init__(self, sender_number):
        self.sender_number = sender_number
        self.last_activity = datetime.now()
        self.conversation_history = []
        self.last_message_id = None
        self.is_new_session = True
        self.language = "en"  # Default language is English
        
    def to_dict(self):
        return {
            "sender_number": self.sender_number,
            "last_activity": self.last_activity.isoformat(),
            "conversation_history": self.conversation_history,
            "last_message_id": self.last_message_id,
            "is_new_session": self.is_new_session,
            "language": self.language
        }
    
    @staticmethod
    def from_dict(data):
        session = ChatSession(data["sender_number"])
        session.last_activity = datetime.fromisoformat(data["last_activity"])
        session.conversation_history = data["conversation_history"]
        session.last_message_id = data.get("last_message_id")
        session.is_new_session = False
        session.language = data.get("language", "en")
        return session


def translate_text(text, dest_language):
    if dest_language=="en":
        return text
        
    try:
        # Regular expression to find URLs in the text
        url_pattern = re.compile(r'(https?://\S+)')
        urls = re.findall(url_pattern, text)
        
        # Unique placeholder format
        placeholder_format = '__URL_PLACEHOLDER_{}__'
        
        # Replace URLs with placeholders
        for i, url in enumerate(urls):
            placeholder = placeholder_format.format(i)
            text = text.replace(url, placeholder)
        
        # Translate the text without URLs
        translated = translator.translate(text, dest=dest_language).text
        
        # Replace placeholders with original URLs
        for i, url in enumerate(urls):
            placeholder = placeholder_format.format(i)
            translated = translated.replace(placeholder, url)
        
        return translated
    except Exception as e:
        logger.error(f"Error translating text: {e}")
        return text  # Return original text if translation fails


def needs_rating(response_text):
    # Responses that don't need rating
    casual_patterns = [
        "thank you", "thanks", "you're welcome", "noted",
        "got it", "understood", "👍", "🙏", "nice","bravo","amazing","impressive",
        "sorry", "please", "hi", "hello", "hey", "good morning", "good afternoon", 
        "good evening", "thanks", "thank you", "bye", "goodbye", "cool","yeah","yah","alright",
        "oh","oops","ok","yes"
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
            if datetime.now() - last_activity > timedelta(hours=2):
                session = ChatSession(sender_number)
        else:
            session = ChatSession(sender_number)
        return session
    except Exception as e:
        logger.error(f"Error getting chat session: {e}")
        return ChatSession(sender_number)

def save_chat_session(session):
    try:
        session_key = f"chat_session:{session.sender_number}"
        session_data = json.dumps(session.to_dict())
        redis_client.setex(session_key, timedelta(hours=24), session_data)
    except Exception as e:
        logger.error(f"Error saving chat session: {e}")

def get_greeting_message(language="en"):
    
    hour = datetime.now().hour
    if 5 <= hour < 12:
        greeting = translate_text("Good morning! 🌅", language)
    elif 12 <= hour < 17:
        greeting = translate_text("Good afternoon! 🌞", language)
    else:
        greeting = translate_text("Good evening! 🌙", language)
    return greeting

def create_welcome_message(profile_name, language="en"):
    greeting = get_greeting_message(language)
    
    # Get the user's WhatsApp profile name
    name = f"{profile_name}!" if profile_name else "User!"
    
    welcome_text = translate_text(
        "Welcome to AI Fact Checker! 🤖✨\n\n"
        "I'm here to help you verify information and check facts. "
        "Feel free to ask me any questions or share statements you'd like to fact-check.\n\n"
        "To get started, simply type your question or statement! 📝",
        language
    )
    return f"{greeting} {name} \n {welcome_text}"

def store_feedback(message_id, feedback_type, sender_number):
    try:
        feedback_key = f"feedback:{message_id}"
        feedback_data = {
            "timestamp": datetime.now().isoformat(),
            "feedback_type": feedback_type,
            "sender_number": sender_number
        }
        redis_client.setex(feedback_key, timedelta(days=30), json.dumps(feedback_data))
    except Exception as e:
        logger.error(f"Error storing feedback: {e}")

def send_message_with_template(to_number, body_text, user_input, is_greeting=False, language="en"):
    try:
        translated_body = translate_text(body_text, language)
        main_message = client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=to_number,
            body=translated_body
        )
        time.sleep(1)
        if not is_greeting and needs_rating(user_input):
            template_message = client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=to_number,
                body=translate_text("Was this response helpful? Reply with 👍 for Yes or 👎 for No.", language)
            )
            return translate_text(template_message,language)
        return main_message
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        raise

def handle_button_response(user_response, chat_session, previous, sender_number):
    try:
        if user_response in ["👍", "👎"]:
            feedback_type = "positive" if user_response == "👍" else "negative"
            if chat_session.last_message_id:
                store_feedback(chat_session.last_message_id, feedback_type, sender_number)
                message = client.messages.create(
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=sender_number,
                    body=translate_text("Thank you for your feedback! 🙏.\n Would you like to verify another claim?", previous)
                )
                return True, message.sid
        return False, None
        
    except Exception as e:
        logger.error(f"Error handling button response: {e}")
        return False, None

def call_external_api(user_query, chat_session):
    try:
        payload = {"user_input": user_query}
        response = requests.post(EXTERNAL_API_URL, json=payload, timeout=600)
        response.raise_for_status()
        data = response.json()
        return {"message": data.get("result", "Unexpected API response format.")}
    except Timeout:
        logger.error("External API request timed out.")
        return {"message": "The request to the external API timed out.", "status": "error"}
    except Exception as e:
        logger.error(f"Error calling external API: {e}")
        return {"message": f"An error occurred: {e}", "status": "error"}

def transcribe_voice_message(audio_url,chat_session):
    try:
        # Download the audio file
        response = requests.get(audio_url)
        response.raise_for_status()
        
        # Save the audio file temporarily
        with open("temp_audio.ogg", "wb") as f:
            f.write(response.content)
        
        # Convert .ogg to .wav using pydub
        audio = AudioSegment.from_file("temp_audio.ogg", format="ogg")
        audio.export("temp_audio.wav", format="wav")
        
        # Transcribe the audio using speech_recognition
        #with sr.AudioFile("temp_audio.wav") as source:
        #    audio_data = recognizer.record(source)
        #    text = recognizer.recognize_google(audio_data)

        # Step 3: Transcribe the audio using Whisper API
        with open("temp_audio.wav", "rb") as audio_file:
            transcription = openai.Audio.transcribe(
                file=audio_file,
                model="whisper-1",
                response_format="text"
            )
        print(transcription)

        detected_language = translator.detect(transcription).lang
        chat_session.language = detected_language

        # Clean up temporary files
        os.remove("temp_audio.ogg")
        os.remove("temp_audio.wav")
        
        return transcription
    except Exception as e:
        logger.error(f"Error transcribing voice message: {e}")
        return None

@celery.task
def process_whatsapp_message(sender_number, profile_name, incoming_message, chat_session_dict):
    try:
        chat_session = ChatSession.from_dict(chat_session_dict)

        # Previous Language
        previous = chat_session.language

        # Detect language from the incoming message
        detected_language = translator.detect(incoming_message).lang
        chat_session.language = detected_language

        # Handle feedback (thumbs up/down)
        if incoming_message in ["👍", "👎"]:
            is_feedback, message_sid = handle_button_response(incoming_message, chat_session, previous, sender_number)
            if is_feedback:
                return

        if chat_session.is_new_session:
            welcome_message = send_message_with_template(
                sender_number,
                create_welcome_message(profile_name, chat_session.language),
                incoming_message,
                is_greeting=True,
                language=chat_session.language
            )
            chat_session.conversation_history.append({
                "timestamp": datetime.now().isoformat(),
                "message": create_welcome_message(profile_name, chat_session.language),
                "type": "outgoing",
                "message_id": welcome_message.sid
            })

        chat_session.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "message": incoming_message,
            "type": "incoming"
        })

        # Send a processing message for text inputs
        if needs_rating(incoming_message):
            processing_message = client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=sender_number,
                body=translate_text("Processing your request. ⏳", chat_session.language)
            )

        api_response = call_external_api(incoming_message, chat_session)
        response_text = api_response.get("message", "I am unable to provide a response now. Please try your query again.")

        print(response_text)

        message = send_message_with_template(sender_number, response_text, incoming_message, language=chat_session.language)
        chat_session.last_message_id = message.sid

        chat_session.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "message": response_text,
            "type": "outgoing",
            "message_id": message.sid
        })

        chat_session.last_activity = datetime.now()
        save_chat_session(chat_session)
    except Exception as e:
        logger.error(f"Error in process_whatsapp_message: {str(e)}")


@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    try:
        print(request.form)
        sender_number = request.form.get("From")
        chat_session = get_chat_session(sender_number)

        # Get the user's WhatsApp profile name
        profile_name = request.form.get("ProfileName", "User")

        # Check if the message is a voice note
        num_media = int(request.form.get("NumMedia", 0))
        if num_media > 0:
            media_url = request.form.get("MediaUrl0")
            media_type = request.form.get("MediaContentType0", "")

            # Check if the media is a voice note (audio/ogg)
            if media_type == "audio/ogg":
                # Send a processing message
                processing_message = client.messages.create(
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=sender_number,
                    body=translate_text("Processing your voice note... ⏳", chat_session.language)
                )

                # Transcribed Text
                transcribed_text = transcribe_voice_message(media_url, chat_session)
                if transcribed_text:
                    incoming_message = transcribed_text
                else:
                    incoming_message = translate_text("Sorry, I couldn't process the voice note.", chat_session.language)
            else:
                incoming_message = translate_text("Unsupported media type. Please send a voice note.", chat_session.language)
        else:
            incoming_message = request.form.get("Body", "").strip()

        # Queue the task for asynchronous processing
        process_whatsapp_message.delay(sender_number, profile_name, incoming_message, chat_session.to_dict())

        return jsonify({"status": "success", "message": "Processing your request."}), 200
    except Exception as e:
        logger.error(f"Error in whatsapp_reply: {str(e)}")
        error_message = translate_text("An error occurred. Please try again later.", chat_session.language)
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=sender_number,
            body=error_message
        )
        return jsonify({"status": "error", "message": str(e)}), 500
        
"""
@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    try:
        print(request.form)
        sender_number = request.form.get("From")
        chat_session = get_chat_session(sender_number)

        # Get the user's WhatsApp profile name
        profile_name = request.form.get("ProfileName","User")
        
        
        # Check if the message is a voice note
        num_media = int(request.form.get("NumMedia", 0))
        if num_media > 0:
            media_url = request.form.get("MediaUrl0")
            media_type = request.form.get("MediaContentType0", "")
            
            # Check if the media is a voice note (audio/ogg)
            if media_type == "audio/ogg":
                # Send a processing message
                processing_message = client.messages.create(
                    from_=TWILIO_WHATSAPP_NUMBER,
                    to=sender_number,
                    body=translate_text("Processing your voice note... ⏳",chat_session.language)
                )

                #Transcribed Text
                transcribed_text = transcribe_voice_message(media_url,chat_session)
                if transcribed_text:
                    incoming_message = transcribed_text
                else:
                    incoming_message = translate_text("Sorry, I couldn't process the voice note.", chat_session.language)
            else:
                incoming_message = translate_text("Unsupported media type. Please send a voice note.", chat_session.language)
        else:
            incoming_message = request.form.get("Body", "").strip()

        #Previous Language
        previous=chat_session.language
        
        # Detect language from the incoming message
        detected_language = translator.detect(incoming_message).lang
        chat_session.language = detected_language
        
        
        # Handle feedback (thumbs up/down)
        if incoming_message in ["👍", "👎"]:
        #if button_text:
            is_feedback, message_sid = handle_button_response(incoming_message, chat_session, previous, sender_number)
            if is_feedback:
                return jsonify({"status": "success", "message_sid": message_sid})
        
        if chat_session.is_new_session:
            welcome_message = send_message_with_template(
                sender_number,
                create_welcome_message(profile_name, chat_session.language),
                incoming_message,
                is_greeting=True,
                language=chat_session.language
            )
            chat_session.conversation_history.append({
                "timestamp": datetime.now().isoformat(),
                "message": create_welcome_message(profile_name, chat_session.language),
                "type": "outgoing",
                "message_id": welcome_message.sid
            })
        
        chat_session.conversation_history.append({
            "timestamp": datetime.now().isoformat(),
            "message": incoming_message,
            "type": "incoming"
        })

        # Send a processing message for text inputs
        if num_media == 0 and needs_rating(incoming_message):
            processing_message = client.messages.create(
                from_=TWILIO_WHATSAPP_NUMBER,
                to=sender_number,
                body=translate_text("Processing your request. ⏳",chat_session.language)
            )
            
        api_response = call_external_api(incoming_message, chat_session)
        response_text = api_response.get("message", "I am unable to provide a response now. Please try your query again.")

        print(response_text)
        
        message = send_message_with_template(sender_number, response_text, incoming_message, language=chat_session.language)
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
        logger.error(f"Error in whatsapp_reply: {str(e)}")
        error_message = translate_text("An error occurred. Please try again later.", chat_session.language)
        client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=sender_number,
            body=error_message
        )
        return jsonify({"status": "error", "message": str(e)}), 500
"""
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
