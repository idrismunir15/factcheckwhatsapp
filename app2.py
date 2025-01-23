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
import time
from googletrans import Translator

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

# Multilingual Support
SUPPORTED_LANGUAGES = {
    'en': 'English',
    'es': 'Spanish',
    'fr': 'French',
    'de': 'German',
    'zh-cn': 'Chinese (Simplified)',
    'ar': 'Arabic'
}

WELCOME_MESSAGES = {
    'en': (
        "Welcome to AI Fact Checker! 🤖✨\n\n"
        "I'm here to help you verify information and check facts. "
        "Feel free to ask me any questions or share statements you'd like to fact-check.\n\n"
        "To get started, simply type your question or statement! 📝"
    ),
    'es': (
        "¡Bienvenido a Verificador de Hechos de IA! 🤖✨\n\n"
        "Estoy aquí para ayudarte a verificar información y comprobar datos. "
        "Siéntete libre de hacerme cualquier pregunta o compartir declaraciones que quieras verificar.\n\n"
        "¡Para comenzar, simplemente escribe tu pregunta o declaración! 📝"
    ),
    'fr': (
        "Bienvenue sur le Vérificateur de Faits par IA ! 🤖✨\n\n"
        "Je suis là pour vous aider à vérifier les informations et à fact-checker. "
        "N'hésitez pas à me poser des questions ou à partager des déclarations que vous souhaitez vérifier.\n\n"
        "Pour commencer, tapez simplement votre question ou déclaration ! 📝"
    ),
    'de': (
        "Willkommen beim KI-Faktenprüfer! 🤖✨\n\n"
        "Ich bin hier, um Ihnen bei der Überprüfung von Informationen zu helfen. "
        "Zögern Sie nicht, mir Fragen zu stellen oder Aussagen zur Überprüfung vorzulegen.\n\n"
        "Um zu beginnen, stellen Sie einfach Ihre Frage oder Aussage! 📝"
    ),
    'zh-cn': (
        "欢迎使用AI事实核查器！🤖✨\n\n"
        "我在这里帮助您验证信息和检查事实。"
        "随时可以向我提出问题或分享您想核实的陈述。\n\n"
        "开始吧，直接输入您的问题或陈述！📝"
    ),
    'ar': (
        "مرحبًا بك في مدقق الحقائق بالذكاء الاصطناعي! 🤖✨\n\n"
        "أنا هنا لمساعدتك في التحقق من المعلومات والتحقق من الحقائق. "
        "لا تتردد في طرح أي أسئلة أو مشاركة البيانات التي ترغب في التحقق منها.\n\n"
        "للبدء، ببساطة اكتب سؤالك أو بيانك! 📝"
    )
}

# Translator for dynamic translations
translator = Translator()

class ChatSession:
    def __init__(self, sender_number, language='en'):
        self.sender_number = sender_number
        self.last_activity = datetime.now()
        self.conversation_history = []
        self.last_message_id = None
        self.is_new_session = True
        self.language = language
        
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
        session = ChatSession(data["sender_number"], data.get("language", 'en'))
        session.last_activity = datetime.fromisoformat(data["last_activity"])
        session.conversation_history = data["conversation_history"]
        session.last_message_id = data.get("last_message_id")
        session.is_new_session = False
        return session

def generate_language_selection_message():
    message = "Please select your preferred language:\n\n"
    for code, name in SUPPORTED_LANGUAGES.items():
        message += f"{code}: {name}\n"
    return message

def translate_message(text, target_lang):
    try:
        translation = translator.translate(text, dest=target_lang)
        return translation.text
    except Exception as e:
        logger.error(f"Translation error: {e}")
        return text

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

def save_chat_session(session):
    try:
        session_key = f"chat_session:{session.sender_number}"
        session_data = json.dumps(session.to_dict())
        redis_client.setex(session_key, timedelta(hours=24), session_data)
    except Exception as e:
        logger.error(f"Error saving chat session: {e}")

def send_message_with_template(to_number, body_text, user_input, user_language='en', is_greeting=False):
    try:
        # Translate message if needed
        if user_language != 'en':
            body_text = translate_message(body_text, user_language)
        
        main_message = client.messages.create(
            from_=TWILIO_WHATSAPP_NUMBER,
            to=to_number,
            body=body_text
        )
        time.sleep(1)
        return main_message
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        raise

@app.route("/whatsapp", methods=["POST"])
def whatsapp_reply():
    try:
        incoming_message = request.form.get("Body", "").strip().lower()
        sender_number = request.form.get("From")
        
        # Retrieve or create chat session
        chat_session = get_chat_session(sender_number)
        
        # Language selection logic for new users
        if chat_session.is_new_session:
            # If the incoming message is a language code
            if incoming_message in SUPPORTED_LANGUAGES:
                # Set the language for the session
                chat_session.language = incoming_message
                chat_session.is_new_session = False
                
                # Send welcome message in selected language
                welcome_message = send_message_with_template(
                    sender_number,
                    WELCOME_MESSAGES.get(chat_session.language, WELCOME_MESSAGES['en']),
                    incoming_message,
                    chat_session.language,
                    is_greeting=True
                )
                
                chat_session.conversation_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "message": WELCOME_MESSAGES.get(chat_session.language, WELCOME_MESSAGES['en']),
                    "type": "outgoing",
                    "message_id": welcome_message.sid
                })
                
                save_chat_session(chat_session)
                return jsonify({"status": "success", "message_sid": welcome_message.sid})
            else:
                # Prompt for language selection if not a valid language code
                language_message = send_message_with_template(
                    sender_number,
                    generate_language_selection_message(),
                    incoming_message
                )
                return jsonify({"status": "language_selection", "message_sid": language_message.sid})
        
        # Regular message handling with translation support
        api_response = call_external_api(incoming_message)
        response_text = api_response.get("message", "I am unable to provide response now, please try your query again.")
        
        # Send the response in user's preferred language
        message = send_message_with_template(
            sender_number, 
            response_text, 
            incoming_message,
            chat_session.language
        )
        
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
        return jsonify({"status": "error", "message": str(e)}), 500

def call_external_api(user_query):
    try:
        payload = {"user_input": user_query}
        response = requests.post(EXTERNAL_API_URL, json=payload, timeout=600)
        response.raise_for_status()
        data = response.json()
        return {"message": data.get("result", "Unexpected API response format.")}
    except Exception as e:
        logger.error(f"Error calling external API: {e}")
        return {"message": f"An error occurred: {e}", "status": "error"}

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
