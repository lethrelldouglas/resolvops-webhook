import os
import json
import base64
import requests
from datetime import datetime
from flask import Flask, request, jsonify
import gspread
from google.oauth2.service_account import Credentials

app = Flask(__name__)

SHEET_ID = "1eNWGM4Ga1hJVyR-Nq95rkVeDcQweu1ju38yQZ8iO4a4"
SCOPES   = ["https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive"]

RESEND_API_KEY  = os.environ.get("RESEND_API_KEY")
SENDER_EMAIL    = "aria@resolvops.ai"
NOTIFY_EMAIL    = "resolvops@gmail.com"


def get_sheet():
    raw = os.environ.get("GOOGLE_CREDS", "")
    creds_dict = json.loads(base64.b64decode(raw).decode("utf-8"))
    creds = Credentials.from_service_account_info(creds_dict, scopes=SCOPES)
    client = gspread.authorize(creds)
    return client.open_by_key(SHEET_ID).worksheet("Inbound Calls")


def log_to_sheets(data):
    try:
        sheet = get_sheet()
        now   = datetime.now()
        sheet.append_row([
            now.strftime("%Y-%m-%d"),
            data.get("caller_name", ""),
            data.get("business_name", ""),
            format_phone(data.get("phone_number", "")),
            data.get("email", ""),
            format_phone(data.get("phone_number", "")),
            data.get("interested_in", ""),
            data.get("lead_quality", ""),
            "Yes" if str(data.get("booked_demo", "")).lower() == "true" else "No",
            data.get("call_summary", ""),
        ])
        print(f"Sheet row added for {data.get('caller_name', 'unknown')}")
    except Exception as e:
        print(f"Sheets Error: {type(e).__name__}: {e}")


def format_phone(raw):
    digits = "".join(filter(str.isdigit, str(raw)))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) == 10:
        return f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
    return raw


def send_lead_alert(data):
    body = f"""New inbound call — ResolvOps

Name:        {data.get('caller_name', 'Unknown')}
Business:    {data.get('business_name', 'Unknown')}
Phone:       {format_phone(data.get('phone_number', ''))}
Email:       {data.get('email', 'Not provided')}
Interested:  {data.get('interested_in', '')}
Lead Quality:{data.get('lead_quality', '')}
Demo Booked: {'Yes' if str(data.get('booked_demo', '')).lower() == 'true' else 'No'}
Summary:     {data.get('call_summary', '')}

Calendly: https://calendly.com/resolvops/free-resolvops-demo
"""
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": SENDER_EMAIL,
                "to": [NOTIFY_EMAIL],
                "subject": f"New Lead: {data.get('caller_name', 'Unknown')} — ResolvOps",
                "text": body,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            print(f"Lead alert sent to {NOTIFY_EMAIL}")
        else:
            print(f"Email Error: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Email Error: {type(e).__name__}: {e}")


def send_booking_email(to_email, caller_name):
    name = caller_name if caller_name else "there"
    body = f"""Hi {name},

Thanks for calling ResolvOps!

Here is your link to book a free demo call:
https://calendly.com/resolvops/free-resolvops-demo

Simply pick a time that works for you and we'll walk you through everything live.

Looking forward to connecting!

— Lethrell Douglas
Founder, ResolvOps
resolvops.ai
"""
    try:
        resp = requests.post(
            "https://api.resend.com/emails",
            headers={
                "Authorization": f"Bearer {RESEND_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "from": SENDER_EMAIL,
                "to": [to_email],
                "subject": "Your Free ResolvOps Demo Link",
                "text": body,
            },
            timeout=10,
        )
        if resp.status_code in (200, 201):
            print(f"Booking email sent to {to_email}")
        else:
            print(f"Booking Email Error: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"Booking Email Error: {type(e).__name__}: {e}")


@app.route("/", methods=["GET", "POST"])
def webhook():
    if request.method == "GET":
        return jsonify({"status": "ResolvOps webhook running"}), 200

    try:
        body        = request.get_json(force=True) or {}
        call        = body.get("call", {})
        analysis    = call.get("call_analysis", {})
        custom_data = analysis.get("custom_analysis_data", {})

        email = custom_data.get("email", "").strip()
        name  = custom_data.get("caller_name", "").strip()

        start_ts = call.get("start_timestamp")
        end_ts   = call.get("end_timestamp")
        if start_ts and end_ts:
            secs     = int((end_ts - start_ts) / 1000)
            duration = f"{secs // 60}m {secs % 60}s"
        else:
            duration = ""

        log_data = {
            "caller_name":    name,
            "business_name":  custom_data.get("Business_name", ""),
            "phone_number":   call.get("from_number", custom_data.get("Phone_number", "")),
            "email":          email,
            "interested_in":  custom_data.get("Interested_in", ""),
            "lead_quality":   custom_data.get("lead_quality", ""),
            "booked_demo":    custom_data.get("booked_demo", ""),
            "follow_up":      custom_data.get("Follow_up_needed", ""),
            "duration":       duration,
            "call_summary":   analysis.get("call_summary", ""),
        }

        print(f"Call received — NAME: {name} | EMAIL: {email}")
        log_to_sheets(log_data)
        send_lead_alert(log_data)
        if email:
            send_booking_email(email, name)

        return jsonify({"status": "ok"}), 200

    except Exception as e:
        print(f"Webhook Error: {type(e).__name__}: {e}")
        return jsonify({"error": str(e)}), 500


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
