import os
import logging
import requests
from flask import Flask, request, jsonify
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID")
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

WHATSAPP_API_URL = f"https://graph.facebook.com/v23.0/{PHONE_NUMBER_ID}/messages"


def get_gemini_reply(user_message):
    try:
        response = model.generate_content(user_message)
        if response and hasattr(response, "text") and response.text:
            return response.text.strip()
        return "Sorry, I couldn't generate a response right now."
    except Exception as e:
        logger.error(f"Gemini API error: {e}")
        return "Sorry, something went wrong while processing your message."


def send_whatsapp_message(to_number, message_text):
    try:
        headers = {
            "Authorization": f"Bearer {WHATSAPP_TOKEN}",
            "Content-Type": "application/json",
        }
        payload = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {
                "body": message_text
            }
        }
        response = requests.post(WHATSAPP_API_URL, headers=headers, json=payload, timeout=15)
        if response.status_code not in (200, 201):
            logger.error(f"WhatsApp API error: {response.status_code} - {response.text}")
        return response
    except Exception as e:
        logger.error(f"Error sending WhatsApp message: {e}")
        return None


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    try:
        mode = request.args.get("hub.mode")
        token = request.args.get("hub.verify_token")
        challenge = request.args.get("hub.challenge")

        if mode == "subscribe" and token == VERIFY_TOKEN:
            return challenge, 200
        else:
            return "Verification failed", 403
    except Exception as e:
        logger.error(f"Webhook verification error: {e}")
        return "Error", 400


@app.route("/webhook", methods=["POST"])
def receive_message():
    try:
        data = request.get_json()

        if not data or "entry" not in data:
            return jsonify({"status": "ignored"}), 200

        for entry in data.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})

                if "messages" not in value:
                    continue

                messages = value.get("messages", [])

                for message in messages:
                    try:
                        message_type = message.get("type")
                        from_number = message.get("from")

                        if message_type != "text":
                            logger.info(f"Ignoring non-text message type: {message_type}")
                            continue

                        text_body = message.get("text", {}).get("body", "")

                        if not text_body or not from_number:
                            continue

                        logger.info(f"Received message from {from_number}: {text_body}")

                        reply_text = get_gemini_reply(text_body)
                        send_whatsapp_message(from_number, reply_text)

                    except Exception as inner_e:
                        logger.error(f"Error processing individual message: {inner_e}")
                        continue

        return jsonify({"status": "success"}), 200

    except Exception as e:
        logger.error(f"Webhook processing error: {e}")
        return jsonify({"status": "error"}), 200


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found"}), 404


@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
