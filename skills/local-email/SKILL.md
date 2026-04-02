---
name: local-email
description: Access a local Python/PostgreSQL mail server API for mailbox login, inbox listing, email read/search, send, and delivery-status checks. Use when retrieving API keys or messages from the inbox, sending mail via the local server, checking delivery, or debugging email-server auth/API behavior.
version: 1.0.0
metadata:
  openclaw:
    requires:
      env:
        - EMAIL_SERVER
        - EMAIL_ADDRESS
        - EMAIL_PASSWORD
      bins: []
    primaryEnv: EMAIL_ADDRESS
    emoji: "\U0001F4E7"
    homepage: https://github.com/larkins/py_pg_email
    tags:
      - email
      - imap
      - smtp
      - mailbox
---

# Local Email Skill

Use this skill to interact with a Python/PostgreSQL mail server via its HTTP API.

## Requirements

Configure these environment variables (or in `.env`):

| Variable | Description | Example |
|----------|-------------|---------|
| `EMAIL_SERVER` | Base URL of the mail server | `http://192.168.4.41:5003` |
| `EMAIL_ADDRESS` | Email account to send from | `evie@yourdomain.com` |
| `EMAIL_PASSWORD` | Account password | `your_password` |
| `EMAIL_TO` | Default recipient (optional) | `user@domain.com` |

## Quick start

```bash
# List inbox
python skills/local-email/scripts/mail_api.py list --limit 20

# Search inbox
python skills/local-email/scripts/mail_api.py search --query "subject:order"

# Read a specific email
python skills/local-email/scripts/mail_api.py read --id 880

# Send a plain email
python skills/local-email/scripts/mail_api.py send \
  --to "recipient@example.com" \
  --subject "Hello" \
  --body "Message text"
```

## Commands

### list — List mailbox contents

```bash
python skills/local-email/scripts/mail_api.py list --limit 20
```

### search — Search mailbox

```bash
python skills/local-email/scripts/mail_api.py search --query "coinglass api key"
```

### read — Read a specific email

```bash
python skills/local-email/scripts/mail_api.py read --id 880
```

### send — Send an email

```bash
python skills/local-email/scripts/mail_api.py send \
  --to "recipient@example.com" \
  --subject "Subject line" \
  --body "Email body text"
```

### status — Check delivery status of a sent email

```bash
python skills/local-email/scripts/mail_api.py status --id 1251
```

### login — Test mailbox authentication

```bash
python skills/local-email/scripts/mail_api.py login
```

## API Reference

See `references/api.md` for the full endpoint documentation.

## Notes

- The mail server must be running and reachable at `EMAIL_SERVER`
- Authentication is per-account — each email address is a separate mailbox
- Inbound mail is stored in PostgreSQL; outbound is relayed via SMTP
- Do not print secrets, passwords, bearer tokens, or API keys into chat unless the user explicitly asks
