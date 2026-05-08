# ResolvOps Business AI Agent

A fully autonomous Python agent that monitors your inbox, classifies incoming emails, and sends AI-generated replies — 24/7, no clicks required.

## What it does

```
Every 60 seconds:
  IMAP poll → new unseen emails?
       │
       ▼
  Claude classifies each email
  (business inquiry vs spam/skip)
       │
  ┌────┴────────┐
  │             │
SKIP          DRAFT reply with
(ignored)     Claude + business knowledge
                    │
                    ▼
              Send via SMTP
              (in-thread, with References)
                    │
                    ▼
              Log to console + agent.log
```

## Files

| File | Purpose |
|------|---------|
| `agent.py` | Main autonomous email agent loop |
| `proposal.py` | Interactive CLI proposal generator |
| `config.py` | All credentials and business knowledge |
| `agent.log` | Auto-created log of every action |

## Setup

### 1. Install Python 3.10+

No external packages required — uses Python's standard library only (`imaplib`, `smtplib`, `email`, `urllib`).

### 2. Edit `config.py`

```python
AGENT_CONFIG = {
    "anthropic_api_key": "sk-ant-YOUR-KEY-HERE",   # ← your key
    "dry_run": True,                                 # ← True = no emails sent
    "poll_interval_secs": 60,

    "imap": {
        "host":     "imap-mail.outlook.com",         # Gmail: imap.gmail.com
        "port":     993,
        "username": "you@yourdomain.com",
        "password": "YOUR-PASSWORD",
    },

    "smtp": {
        "host":     "smtp-mail.outlook.com",         # Gmail: smtp.gmail.com
        "port":     587,
        "username": "you@yourdomain.com",
        "password": "YOUR-PASSWORD",
    },
}
```

Also update `BUSINESS_KNOWLEDGE` with your real pricing and services.

### 3. Gmail users — enable App Passwords

Gmail requires an **App Password** (not your regular password):
1. Go to myaccount.google.com → Security → 2-Step Verification → App passwords
2. Create one for "Mail" and paste it into config.py

Use these Gmail hosts:
```python
"imap": { "host": "imap.gmail.com", "port": 993, "security": "tls" }
"smtp": { "host": "smtp.gmail.com",  "port": 587, "security": "starttls" }
```

### 4. Test with dry_run = True

```bash
python agent.py
```

With `dry_run: True`, the agent reads and classifies emails but prints drafts to the log instead of sending them. Verify everything looks right before going live.

### 5. Go live

Set `"dry_run": False` in `config.py` and restart the agent.

## Running continuously

### macOS / Linux — run in background with nohup

```bash
nohup python agent.py > agent.log 2>&1 &
echo $! > agent.pid   # save the process ID to stop it later
```

Stop it:
```bash
kill $(cat agent.pid)
```

### Linux — run as a systemd service (recommended for servers)

Create `/etc/systemd/system/resolvops.service`:

```ini
[Unit]
Description=ResolvOps AI Email Agent
After=network.target

[Service]
WorkingDirectory=/path/to/resolvops_agent
ExecStart=/usr/bin/python3 agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Enable and start:
```bash
sudo systemctl enable resolvops
sudo systemctl start resolvops
sudo journalctl -u resolvops -f   # live logs
```

### Windows — run as a scheduled task or background process

```bat
start /B pythonw agent.py
```

Or use Task Scheduler to run `python agent.py` at startup.

## Proposal generator

Generate a custom sales proposal interactively:

```bash
python proposal.py
```

You'll be prompted for the prospect's name, industry, pain points, and package preference. The AI generates a full proposal you can review, edit, and save.

## Stopping the agent

Press **Ctrl-C** — the agent finishes its current email cycle and shuts down cleanly.

## Log file

Every action is written to `agent.log`:

```
2026-05-01 14:32:01  INFO     ── Polling inbox ──
2026-05-01 14:32:03  INFO     IMAP: 2 unseen message(s) found.
2026-05-01 14:32:03  INFO     Processing: [5] 'Inquiry about AI answering' from 'Mike Torres <mike@…>'
2026-05-01 14:32:07  INFO       → REPLY drafted
2026-05-01 14:32:08  INFO       → SENT  (Message-ID: <resolvops.20260501143208@resolvops.ai>)
2026-05-01 14:32:08  INFO     Processing: [6] 'Win a free iPhone!' from 'promo@spam.com'
2026-05-01 14:32:10  INFO       → SKIP (classified as non-business)
```

## Customising the AI behaviour

All AI behaviour is controlled by the prompts in `agent.py`:

- **`ANALYZE_SYSTEM`** — controls email classification and reply drafting
- **`BUSINESS_KNOWLEDGE`** in `config.py` — the knowledge the AI uses for every reply

Edit these to change tone, add rules, or handle specific scenarios.
