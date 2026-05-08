import os
from flask import Flask, request, jsonify
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import Mail

app = Flask(__name__)

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SENDER_EMAIL = os.environ.get("SENDER_EMAIL")


def send_booking_email(to_email, caller_name):

    body = f"""
Hi {caller_name},

Thanks for speaking with us today about ResolvOps!

BOOK YOUR FREE DEMO:
https://calendly.com/resolvops/free-resolvops-demo

WHAT WE OFFER
- Starter: $497/month
- Growth: $797/month
- Pro: $1,497/month
- Setup fee: $497 one-time

Looking forward to connecting!

Lethrell Douglas
ResolvOps
"""

    message = Mail(
        from_email=SENDER_EMAIL,
        to_emails=to_email,
        subject="Your Free ResolvOps Demo Link",
        plain_text_content=body
    )

    try:
        sg = SendGridAPIClient(SENDGRID_API_KEY)
        response = sg.send(message)

        print(f"Email sent successfully: {response.status_code}")

    except Exception as e:
        print(f"SendGrid Error: {e}")


@app.route("/", methods=["GET", "POST"])
def webhook():

    if request.method == "GET":
        return jsonify({"status": "ResolvOps webhook running"}), 200

    try:
        body = request.get_json()

        call = body.get("call", {})
        analysis = call.get("call_analysis", {})
        custom_data = analysis.get("custom_analysis_data", {})

        email = custom_data.get("email", "")
        name = custom_data.get("caller_name", "there")

        print("EMAIL:", email)
        print("NAME:", name)

        if email:
            send_booking_email(email, name)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("Webhook Error:", str(e))
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)