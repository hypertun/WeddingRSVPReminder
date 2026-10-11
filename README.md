# Wedding RSVP Reminder

Dispatches wedding RSVP confirmation messages to guests via **WhatsApp** and **Telegram**, loaded from a CSV guest list.

## Features

- Multi-channel dispatch: WhatsApp (Twilio / Meta Cloud API / Green API / browser automation) and Telegram (Telethon)
- `--dry-run` mode to preview messages without sending
- Send to a single party (`--party "Name"`), limit rows (`--limit N`), or full dispatch with auto-resume (`--resume`)
- Per-recipient delay to avoid rate limits, with a send log (`rsvp_send_log.csv`) for tracking

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium   # only needed for the playwright WhatsApp method
```

Copy the example config and fill in your credentials:

```bash
cp .env.example .env
```

## Usage

```bash
# Dry run — preview without sending
./run_rsvp.sh --dry-run

# Test a single party
./run_rsvp.sh --party "Agnes Yeo"

# Send to first 3 rows
./run_rsvp.sh --limit 3

# Full dispatch with auto-resume
./run_rsvp.sh --resume
```

(`run_rsvp.sh` uses the local `venv`; alternatively run `python3 send_rsvp_messages.py <flags>` directly.)

## Configuration

All configuration lives in `.env` (never committed). See `.env.example` for all options:

- `CHANNELS` — which channels to send on (`whatsapp,telegram`)
- `DISPATCH_DELAY` — seconds between recipients
- `TELEGRAM_*` — API credentials from [my.telegram.org](https://my.telegram.org)
- `WHATSAPP_METHOD` — `api` or `playwright`, plus provider credentials (Twilio / Meta / Green API)

## Data files

The guest CSV list and send logs contain personal data and are git-ignored. Keep them out of version control.
