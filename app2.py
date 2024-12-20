from flask import Flask, request, jsonify
from twilio.twiml.messaging_response import MessagingResponse

app = Flask(__name__)

@app.route('/whatsapp', methods=['POST'])
def whatsapp_reply():
    """Handle incoming messages and respond with buttons."""
    incoming_msg = request.form.get('Body').strip().lower()
    response = MessagingResponse()
    message = response.message()

    if incoming_msg == 'hello':
        message.body("Hi there! Choose an option below:")
        message.add_button("Option 1", "http://example.com/option1")
        message.add_button("Option 2", "http://example.com/option2")
    else:
        message.body("I'm sorry, I didn't understand that. Type 'hello' to see options.")

    return str(response)

if __name__ == '__main__':
    app.run(debug=True)
