from twilio.rest import Client

# Your Account SID and Auth Token from twilio.com/console
account_sid = 'your_account_sid'
auth_token = 'your_auth_token'
client = Client(account_sid, auth_token)

# The phone number of the WhatsApp user
to_whatsapp_number = 'whatsapp:+1234567890'
# Your Twilio WhatsApp number
from_whatsapp_number = 'whatsapp:+1234567891'

# Name of your pre-approved WhatsApp template
template_name = 'your_template_name'

# Language code for the template
language = 'en_US'

# The actual body of the message where you might have placeholders for buttons
message_body = 'This is a sample message with buttons.'

# Components for interactive buttons (Quick Reply example)
components = [
    {
        "type": "button",
        "sub_type": "quick_reply",
        "index": 0,
        "parameters": [
            {
                "type": "payload",
                "payload": "Option 1"
            }
        ]
    },
    {
        "type": "button",
        "sub_type": "quick_reply",
        "index": 1,
        "parameters": [
            {
                "type": "payload",
                "payload": "Option 2"
            }
        ]
    }
]

try:
    message = client.messages.create(
        body=message_body,
        from_=from_whatsapp_number,
        to=to_whatsapp_number,
        template_name=template_name,
        language=language,
        components=components
    )
    print(message.sid)
except Exception as e:
    print(f"An error occurred: {e}")
