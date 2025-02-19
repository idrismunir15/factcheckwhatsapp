# Fact Check WhatsApp

## Overview

Fact Check WhatsApp is a Flask web application designed to interact with WhatsApp users via Twilio's API. The application processes incoming messages, including text and voice notes, and responds with fact-checked information. 
It supports multiple languages and uses external APIs for fact-checking.

## Features

- **Multi-language Support**: Detects and translates messages to and from various languages.
- **Voice Message Processing**: Transcribes voice messages using OpenAI's API.
- **Session Management**: Manages user sessions using Redis.
- **Feedback Mechanism**: Users can rate responses with thumbs up/down.

## Requirements

- Python 3.x
- Flask
- Twilio
- Requests
- Redis
- Googletrans
- Pydub
- OpenAI
- dotenv

## Environment Variables

Create a `.env` file in the root directory and add the following variables:
- FLASK_SECRET_KEY=your_flask_secret_key 
- REDIS_URL=your_redis_url 
- EXTERNAL_API=your_external_api_url 
- TWILIO_WHATSAPP_NUMBER=your_twilio_whatsapp_number 
- TWILIO_ACCOUNT_SID=your_twilio_account_sid 
- TWILIO_AUTH_TOKEN=your_twilio_auth_token 
- OPENAI_API_KEY=your_openai_api_key

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/idrismunir15/factcheckwhatsapp.git
   cd factcheckwhatsapp
   
2. Create a virtual environment and activate it:
   python -m venv venv
   source venv/bin/activate  # On Windows use `venv\Scripts\activate`
   
3. Install the dependencies:
   pip install -r requirements.txt

4. Set up the environment variables as described above.

## Running the Application
To run the Flask application, execute the following command:

python app2.py

## Contributing
Feel free to open issues or submit pull requests if you find any bugs or have suggestions for improvements.

## License
This project is licensed under the MIT License. See the LICENSE file for details.
You can edit the [README.md](https://github.com/idrismunir15/factcheckwhatsapp/edit/main/README.md) file to include this formatted documentation.

   

   

