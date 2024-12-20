from flask import Flask, request, redirect, jsonify
from twilio.twiml.messaging_response import MessagingResponse
from twilio.rest import Client
import requests
import time
from dotenv import load_dotenv
import os
from pyshorteners import Shortener


s = Shortener()

load_dotenv()


app = Flask(__name__)


# External API endpoint
EXTERNAL_API_URL = "https://myaifactchecker.org/factcheckAPI/"

# Twilio Credentials
TWILIO_WHATSAPP_NUMBER = os.getenv("TWILIO_WHATSAPP_NUMBER")  # Replace with your Twilio WhatsApp number
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")        # Replace with your Account SID
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")            # Replace with your Auth Token

client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@app.route("/") 
def hello(): 
    return "Welcome to myaifactchecker.org"


@app.route("/message_status", methods=["POST","GET"])
def message_status():
    message_sid = request.values.get("MessageSid")
    message_status = request.values.get("MessageStatus")
    print(f"Message {message_sid} status: {message_status}")  # Log or store status
    return "", 204  # Return an empty response with 204 No Content


# Route to handle incoming WhatsApp messages
@app.route("/whatsapp", methods=["POST","GET"])
def whatsapp_reply():
    # Parse the incoming message from Twilio
    incoming_message = request.form.get("Body")
    sender_number = request.form.get("From")
    
    # Check if the user is responding with a choice
    keys={"💬":"2", "✅":"1"}
    if incoming_message == keys["✅"]:
        response_text = "Great! Please input your claim"
    elif incoming_message == keys["💬"]:
        response_text = "Thank you for your feedback! Please share your thoughts."
    else:
        # Call the external API for other input
        result = call_external_api(incoming_message)
        response_text = (
            f"{result['message']}\n\n"
            "👉 What would you like to do next?\n"
            "✅ Verify a Claim (Type 1) \n"
            "💬 Give us Feedback (Type 2)\n"
        )
    
    try:
        # Send the response message
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
        
        
        
    
    #return str(message)


# Function to call external API
def call_external_api(user_query):
    try:
        payload = {"user_input": user_query}
        headers = {"Content-Type": "application/json"}
        
        # Make the POST request to the external API
        response = requests.post(EXTERNAL_API_URL, json=payload, timeout=300)
        

        # Check for a successful response
        if response.status_code in (200, 201): 
            data = response.json() 

            """
            #convert links to shortlinks
            url1=[s.tinyurl.short(url) for url in data['genuine_urls']]
            url2=[s.tinyurl.short(url) for url in data['non_authentic_urls']]
            
            url=""
            if len(url1)!=0:
                url1.extend(url2)
                url="SOURCES \n" + "\n".join(url1)
            """  
        
            if 'fresult' in data:
                return {'message': data['fresult']}  # Return a dictionary
                #return {'message': data['fresult']+ "\n\n"  + url, 'status': 'success'}  # Return a dictionary
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


# Run the Flask app
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000, debug=True)
    #app.run()
