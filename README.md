# railway-f1-webhook

Deploys `f1_external_telegram_webhook.py` to Railway.

## Required env vars
- TELEGRAM_BOT_TOKEN
- F1_APPROVAL_EVENT_URL

## Health check
- GET /health

## Callback endpoint
- POST /telegram/callback
