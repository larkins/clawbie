# Local Email API Reference

## Overview

This is the HTTP API for the Python/PostgreSQL mail server. It provides SMTP sending/receiving via a REST API.

## Server

- **Base URL:** Set via `EMAIL_SERVER` env var (e.g. `http://192.168.4.41:5003`)
- **Swagger UI:** `/docs`
- **API spec:** `/api/spec.json`

## Authentication

### Login

```
POST /auth/login
Content-Type: application/json

{"email": "user@example.com", "password": "your_password"}
```

**Response:**
```json
{"token": "..."}
```

Use the returned token as `Authorization: Bearer <token>` header for subsequent requests.

## Endpoints

| Method | Path | Description |
|--------|-------|-------------|
| `GET` | `/api/emails` | List mailbox contents |
| `GET` | `/api/emails/{id}` | Read one email by ID |
| `GET` | `/api/search?q=...` | Search mailbox |
| `POST` | `/api/emails` | Send a plain text email |
| `POST` | `/api/emails/mime` | Send a MIME email (multipart) |
| `GET` | `/api/emails/{id}/delivery-status` | Check outbound delivery status |
| `DELETE` | `/api/emails/{id}` | Delete a received email |

## Environment Variables

Set these in your `.env` or shell environment:

| Variable | Description | Example |
|----------|-------------|---------|
| `EMAIL_SERVER` | Mail server base URL | `http://192.168.4.41:5003` |
| `EMAIL_ADDRESS` | Sender/recipient email | `evie@example.com` |
| `EMAIL_PASSWORD` | Account password | `your_password` |
| `EMAIL_TO` | Default recipient for send | `user@example.com` |

## Usage with the Skill

The skill script (`mail_api.py`) handles auth automatically. Just set env vars and run:

```bash
python skills/local-email/scripts/mail_api.py list --limit 20
python skills/local-email/scripts/mail_api.py search --query "subject:order"
python skills/local-email/scripts/mail_api.py read --id 123
python skills/local-email/scripts/mail_api.py send --to "user@example.com" --subject "Hello" --body "Message"
```

## Operational Notes

- Search by subject first for fast retrieval of API keys or reports
- Avoid dumping full HTML email bodies unless needed
- When sending mail for tests, prefer small plain-text messages
- The server stores inbound mail in PostgreSQL; outbound is relayed via SMTP
