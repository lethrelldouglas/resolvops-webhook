import os
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

SHEET_ID = "1eNWGM4Ga1hJVyR-Nq95rkVeDcQweu1ju38yQZ8iO4a4"
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]


SMTP_USER = os.environ.get("SMTP_USER")
SMTP_PASS = os.environ.get("SMTP_PASS")


def get_sheet():
    raw = os.environ.get("GOOGLE_CREDS", "")
    creds_dict = json.loads(raw)
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).sheet1


def log_to_sheets(data):
    try:
        sheet = get_sheet()

        # Add header row if sheet is empty
        if sheet.row_count == 0 or sheet.cell(1, 1).value is None:
            sheet.append_row([
                "Date", "Time", "Caller Name", "Business Name",
                "Phone Number", "Email", "Interested In",
                "Lead Quality", "Demo Booked", "Follow-Up Needed",
                "Call Duration", "Call Successful"
            ])

        now = datetime.now()
        sheet.append_row([
            now.strftime("%Y-%m-%d"),
            now.strftime("%I:%M %p"),
            data.get("caller_name", ""),
            data.get("business_name", ""),
            format_phone(data.get("phone_number", "")),
            data.get("email", ""),
            data.get("interested_in", ""),
            data.get("lead_quality", ""),
            "Yes" if str(data.get("booked_demo", "")).lower() == "true" else "No",
            "Yes" if str(data.get("follow_up_needed", "")).lower() == "true" else "No",
            data.get("duration", ""),
            data.get("call_successful", ""),
        ])
        print("Logged to Google Sheets successfully")
    except Exception as e:
        print(f"Sheets Error: {e}")


def format_phone(raw):
    digits = "".join(filter(str.isdigit, str(raw)))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw

def send_booking_email(to_email, caller_name):
    body = f"""Hi {caller_name},

Thanks for speaking with us today!

Here is your free demo booking link:
https://calendly.com/resolvops/free-resolvops-demo

WHAT WE OFFER
- Starter: $397/month + $550 setup
- Growth: $647/month + $697 setup
- Pro: $997/month + $997 setup

Looking forward to connecting!

Lethrell Douglas
Founder, ResolvOps
resolvops.ai
"""
    msg = MIMEMultipart("alternative")
    msg["From"] = SMTP_USER
    msg["To"] = to_email
    msg["Subject"] = "Your Free ResolvOps Demo Link"
    msg.attach(MIMEText(body, "plain"))

    try:
        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.starttls()
        server.login(SMTP_USER, SMTP_PASS)
        server.sendmail(SMTP_USER, to_email, msg.as_string())
        server.quit()
        print(f"Email sent to {to_email}")
    except Exception as e:
        print(f"Email Error: {e}")


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

        # Calculate duration in readable format
        start_ts = call.get("start_timestamp")
        end_ts = call.get("end_timestamp")
        if start_ts and end_ts:
            secs = int((end_ts - start_ts) / 1000)
            duration = f"{secs // 60}m {secs % 60}s"
        else:
            duration = ""

        log_data = {
            "caller_name": custom_data.get("caller_name", ""),
            "business_name": custom_data.get("Business_name", ""),
            "phone_number": call.get("from_number", custom_data.get("Phone_number", "")),
            "email": email,
            "interested_in": custom_data.get("Interested_in", ""),
            "lead_quality": custom_data.get("lead_quality", ""),
            "booked_demo": custom_data.get("booked_demo", ""),
            "follow_up_needed": custom_data.get("Follow_up_needed", ""),
            "duration": duration,
            "call_successful": analysis.get("call_successful", ""),
        }

        print("EMAIL:", email)
        print("NAME:", name)

        log_to_sheets(log_data)

        if email:
            send_booking_email(email, name)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print("Webhook Error:", str(e))
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)