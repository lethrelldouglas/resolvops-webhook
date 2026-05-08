"""
ResolvOps Business AI Agent
============================
A fully autonomous Python agent that:
  1. Polls your IMAP inbox on a configurable interval
  2. Classifies each unseen email (business inquiry vs spam/skip)
  3. Drafts a personalised reply using Claude + your business knowledge
  4. Sends the reply via SMTP in-thread (preserving Message-ID / References)
  5. Logs every action to the console and to agent.log

Run:
    python agent.py

Stop:
    Ctrl-C  (the agent handles SIGINT gracefully)
"""

import imaplib
import smtplib
import email
import email.policy
import email.utils
import json
import logging
import re
import signal
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path

from config import AGENT_CONFIG, BUSINESS_KNOWLEDGE


# ── Logging ──────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("resolvops")


# ── Graceful shutdown ─────────────────────────────────────────────────────────

_running = True

def _handle_signal(sig, frame):
    global _running
    log.info("Shutdown signal received — finishing current cycle then stopping.")
    _running = False

signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ── Claude API ────────────────────────────────────────────────────────────────

def call_claude(system_prompt: str, user_content: str, temperature: float = 0.4) -> str:
    """
    Calls the Anthropic Messages API using only urllib (no SDK needed).
    Reads ANTHROPIC_API_KEY from config.
    """
    api_key = AGENT_CONFIG.get("anthropic_api_key", "")
    if not api_key or api_key.startswith("sk-ant-YOUR"):
        raise ValueError(
            "No valid ANTHROPIC_API_KEY found. Edit config.py and set your key."
        )

    payload = json.dumps({
        "model": "claude-opus-4-5",
        "max_tokens": 1024,
        "temperature": temperature,
        "system": system_prompt,
        "messages": [{"role": "user", "content": user_content}],
    }).encode()

    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            body = json.loads(resp.read())
            return "".join(
                block["text"]
                for block in body.get("content", [])
                if block.get("type") == "text"
            ).strip()
    except urllib.error.HTTPError as e:
        err_body = e.read().decode()
        raise RuntimeError(f"Claude API HTTP {e.code}: {err_body}") from e


# ── Email helpers ─────────────────────────────────────────────────────────────

def _decode_header_value(raw: str) -> str:
    """Decode RFC-2047 encoded header values (e.g. =?UTF-8?B?...?=)."""
    parts = email.header.decode_header(raw or "")
    decoded = []
    for part, charset in parts:
        if isinstance(part, bytes):
            decoded.append(part.decode(charset or "utf-8", errors="replace"))
        else:
            decoded.append(part)
    return "".join(decoded)


def _extract_text_body(msg: email.message.Message) -> str:
    """Extract plain-text body from a (possibly multipart) email."""
    if msg.is_multipart():
        for part in msg.walk():
            ct = part.get_content_type()
            cd = str(part.get("Content-Disposition", ""))
            if ct == "text/plain" and "attachment" not in cd:
                charset = part.get_content_charset() or "utf-8"
                return part.get_payload(decode=True).decode(charset, errors="replace")
        # fallback: grab first text/html part and strip tags
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                charset = part.get_content_charset() or "utf-8"
                html = part.get_payload(decode=True).decode(charset, errors="replace")
                return re.sub(r"<[^>]+>", " ", html)
    else:
        payload = msg.get_payload(decode=True)
        if payload:
            charset = msg.get_content_charset() or "utf-8"
            return payload.decode(charset, errors="replace")
    return ""


def _extract_sender_address(raw_from: str) -> str:
    """Return just the email address from a 'Name <addr>' header."""
    name, addr = email.utils.parseaddr(raw_from)
    return addr.strip() or raw_from.strip()


def _build_references(msg: email.message.Message) -> list[str]:
    """Collect Message-ID chain for threading (References + In-Reply-To)."""
    refs = []
    for header in ("References", "In-Reply-To"):
        val = msg.get(header, "")
        refs.extend(re.findall(r"<[^>]+>", val))
    mid = msg.get("Message-ID", "")
    if mid and mid not in refs:
        refs.append(mid.strip())
    return refs


# ── IMAP polling ──────────────────────────────────────────────────────────────

def fetch_unseen_emails(imap_cfg: dict) -> list[dict]:
    """
    Connect to IMAP, search for UNSEEN messages, parse them,
    mark as SEEN, and return a list of dicts ready for processing.
    """
    imap = imaplib.IMAP4_SSL(imap_cfg["host"], int(imap_cfg["port"]))
    imap.login(imap_cfg["username"], imap_cfg["password"])
    imap.select(imap_cfg.get("mailbox", "INBOX"))

    _, data = imap.search(None, "UNSEEN")
    uid_list = data[0].split()
    log.info(f"IMAP: {len(uid_list)} unseen message(s) found.")

    emails = []
    for uid in uid_list:
        _, raw = imap.fetch(uid, "(RFC822)")
        raw_email = raw[0][1]
        msg = email.message_from_bytes(raw_email, policy=email.policy.compat32)

        parsed = {
            "uid": uid.decode(),
            "message_id": (msg.get("Message-ID") or "").strip(),
            "from": _decode_header_value(msg.get("From", "")),
            "subject": _decode_header_value(msg.get("Subject", "(no subject)")),
            "body": _extract_text_body(msg),
            "references": _build_references(msg),
            "date": msg.get("Date", ""),
        }
        emails.append(parsed)

        # mark as seen so we don't re-process
        imap.store(uid, "+FLAGS", "\\Seen")

    imap.logout()
    return emails


# ── AI orchestration ──────────────────────────────────────────────────────────

ANALYZE_SYSTEM = """You are a professional business assistant for ResolvOps, an AI Front Desk & Business Automation company.

Your job is to analyze incoming emails and draft replies.

## Your Business Knowledge
{knowledge}

## Instructions
1. Determine if this email is a genuine business inquiry (sales, support, pricing question, partnership, etc.)
2. If it is spam, a newsletter, an auto-reply, or clearly not a business inquiry → reply with ONLY the single word: SKIP
3. If it IS a business inquiry → draft a warm, professional, helpful reply that:
   - Addresses their specific questions directly
   - References relevant services and pricing where appropriate  
   - Ends with a clear call to action (schedule a call, reply with more info, etc.)
   - Is signed "The ResolvOps Team"
4. Output ONLY the reply body text — no subject line, no headers, just the email body.
"""

def classify_and_draft(em: dict) -> str | None:
    """
    Returns a draft reply string, or None if the email should be skipped.
    """
    system = ANALYZE_SYSTEM.format(knowledge=BUSINESS_KNOWLEDGE)
    user_content = (
        f"From: {em['from']}\n"
        f"Subject: {em['subject']}\n"
        f"Date: {em['date']}\n\n"
        f"Body:\n{em['body'][:3000]}"  # truncate very long bodies
    )
    reply = call_claude(system, user_content, temperature=0.4)
    if reply.strip().upper() == "SKIP":
        return None
    return reply.strip()


# ── SMTP sending ──────────────────────────────────────────────────────────────

def send_reply(smtp_cfg: dict, original: dict, reply_body: str) -> str:
    """
    Send a reply email in-thread via SMTP.
    Returns the Message-ID of the sent message.
    """
    to_addr = _extract_sender_address(original["from"])
    subject = f"Re: {original['subject']}"
    sent_at = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    new_message_id = f"<resolvops.{sent_at}@resolvops.ai>"

    msg = MIMEMultipart("alternative")
    msg["From"] = smtp_cfg["username"]
    msg["To"] = to_addr
    msg["Subject"] = subject
    msg["Message-ID"] = new_message_id
    msg["In-Reply-To"] = original["message_id"]
    msg["References"] = " ".join(original["references"])

    msg.attach(MIMEText(reply_body, "plain", "utf-8"))

    host = smtp_cfg["host"]
    port = int(smtp_cfg["port"])
    security = smtp_cfg.get("security", "starttls").lower()

    if security == "tls":
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
        if security == "starttls":
            server.starttls()

    server.login(smtp_cfg["username"], smtp_cfg["password"])
    server.sendmail(smtp_cfg["username"], [to_addr], msg.as_string())
    server.quit()

    return new_message_id


# ── Main agent loop ───────────────────────────────────────────────────────────

def run_agent():
    imap_cfg = AGENT_CONFIG["imap"]
    smtp_cfg = AGENT_CONFIG["smtp"]
    interval = AGENT_CONFIG.get("poll_interval_secs", 60)
    dry_run  = AGENT_CONFIG.get("dry_run", False)

    log.info("=" * 60)
    log.info("ResolvOps Business AI Agent starting")
    log.info(f"  Inbox  : {imap_cfg['username']} @ {imap_cfg['host']}")
    log.info(f"  Sender : {smtp_cfg['username']} @ {smtp_cfg['host']}")
    log.info(f"  Poll   : every {interval}s")
    log.info(f"  Dry run: {dry_run}  (no emails sent when True)")
    log.info("=" * 60)

    stats = {"processed": 0, "replied": 0, "skipped": 0, "errors": 0}

    while _running:
        cycle_start = time.time()
        log.info("── Polling inbox ──")

        try:
            emails = fetch_unseen_emails(imap_cfg)
        except Exception as exc:
            log.error(f"IMAP fetch failed: {exc}")
            stats["errors"] += 1
            emails = []

        for em in emails:
            log.info(f"Processing: [{em['uid']}] {em['subject']!r} from {em['from']!r}")
            stats["processed"] += 1

            try:
                draft = classify_and_draft(em)
            except Exception as exc:
                log.error(f"  Claude error: {exc}")
                stats["errors"] += 1
                continue

            if draft is None:
                log.info("  → SKIP (classified as non-business)")
                stats["skipped"] += 1
                continue

            log.info("  → REPLY drafted")
            log.debug(f"  Draft preview: {draft[:120]}...")

            if dry_run:
                log.info("  → DRY RUN — reply NOT sent. Draft logged below:")
                log.info("-" * 40)
                log.info(draft)
                log.info("-" * 40)
                stats["replied"] += 1
                continue

            try:
                mid = send_reply(smtp_cfg, em, draft)
                log.info(f"  → SENT  (Message-ID: {mid})")
                stats["replied"] += 1
            except Exception as exc:
                log.error(f"  SMTP send failed: {exc}")
                stats["errors"] += 1

        # summary line
        log.info(
            f"Cycle done. Total: {stats['processed']} processed, "
            f"{stats['replied']} replied, {stats['skipped']} skipped, "
            f"{stats['errors']} errors."
        )

        # sleep until next poll, checking _running flag every second
        elapsed = time.time() - cycle_start
        sleep_for = max(0, interval - elapsed)
        log.info(f"Sleeping {sleep_for:.0f}s until next poll…\n")
        deadline = time.time() + sleep_for
        while _running and time.time() < deadline:
            time.sleep(1)

    log.info("Agent stopped cleanly. Goodbye.")


if __name__ == "__main__":
    run_agent()
