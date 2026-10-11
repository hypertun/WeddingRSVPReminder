# Wedding RSVP Reminder

Dispatches wedding RSVP confirmation messages to guests via **WhatsApp** and **Telegram**, driven by a CSV guest list. Designed for one-off bulk sends with dry-run preview, per-recipient delays, and auto-resume so an interrupted run never double-messages a guest.

---

## File Structure

```
WeddingRSVPReminder/
├── send_rsvp_messages.py        # Main script — CLI orchestrator & all dispatchers
├── run_rsvp.sh                  # Wrapper that runs the script using the local venv/
├── requirements.txt             # Python dependencies
├── .env.example                 # Template for all configuration (copy to .env)
├── .env                         # Your real credentials — git-ignored, never commit
├── .gitignore
├── README.md
│
├── venv/                        # Virtual environment — git-ignored
├── __pycache__/                 # Python cache — git-ignored
│
├── rsvp_send_log.csv            # Send log (created on first run) — git-ignored
│                                #   Columns: Timestamp, Party Name, Phone, Channel, Status, Details
│                                #   Used by --resume to skip already-sent (Party, Channel) pairs
│
├── INF-INITY & FOREVER RSVP (Responses) - Messsage List.csv
│                                # Input guest list — git-ignored (contains personal data)
│                                #   Required columns: Party Name | Number to send | Customised Message
├── INF-INITY & FOREVER RSVP (Responses) - Cons. Data.csv
│                                # Raw RSVP responses export — git-ignored
└── Reguler vs Charter (Evan).xlsx
                                 # Guest categorization sheet — git-ignored
```

Files created **outside** the repo on first run:

| Path | Purpose |
|---|---|
| `~/.whatsapp_playwright_profile/` | Persistent Chromium profile (keeps you logged into WhatsApp Web) |
| `~/.telegram_session` (+ `.session`) | Telethon session — avoids re-login on subsequent runs |

> ✅ **Default paths:** the CSV and log default to files **inside this repo** (resolved relative to the script, so it works from any working directory). Override with `--csv` / `--log-file` if your guest list lives elsewhere.

---

## Requirements

- Python 3.9+
- A WhatsApp sender: **Twilio**, **Meta WhatsApp Cloud API**, or **Green API** account (for the `api` method), *or* willingness to scan a QR code (for the `playwright` method)
- Telegram API credentials from [my.telegram.org](https://my.telegram.org) (optional — Telegram channel is skipped if absent)

---

## Setup

```bash
# 1. Clone
git clone https://github.com/hypertun/WeddingRSVPReminder.git
cd WeddingRSVPReminder

# 2. Create virtual environment & install dependencies
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. (Only for --whatsapp-method playwright) install the browser
playwright install chromium

# 4. Configure credentials
cp .env.example .env
# ... edit .env with your API keys ...
```

---

## Configuration (`.env`)

All secrets live in `.env` (git-ignored). Copy from `.env.example`:

### General
| Variable | Description | Default |
|---|---|---|
| `CHANNELS` | Comma-separated list: `whatsapp`, `telegram` | `whatsapp,telegram` |
| `DISPATCH_DELAY` | Seconds to wait between recipients (rate-limit safety) | `6.0` |
| `WHATSAPP_METHOD` | `api` (no browser) or `playwright` (WhatsApp Web) | `api` |

### Telegram (Telethon)
| Variable | Description |
|---|---|
| `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` | From my.telegram.org → "API development tools" |
| `TELEGRAM_PHONE` | Your phone number for first-time login (optional) |

### WhatsApp — pick **one** provider (auto-detected in this priority: Twilio → Meta → Green)
| Provider | Variables |
|---|---|
| **Twilio** (recommended, no browser) | `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_WHATSAPP_NUMBER` |
| **Meta Cloud API** | `META_WA_PHONE_NUMBER_ID`, `META_WA_ACCESS_TOKEN` |
| **Green API** (personal WhatsApp number) | `GREEN_API_INSTANCE_ID`, `GREEN_API_TOKEN` |

---

## Input CSV Format

The message-list CSV must contain these three columns:

| Column | Example |
|---|---|
| `Party Name` | `Agnes Yeo` |
| `Number to send` | `98463882` / `+6598463882` / `6598463882` |
| `Customised Message` | `Hi Agnes! Just confirming your RSVP...` |

Phone numbers are normalized automatically:
- 8-digit local numbers starting `8`/`9` → `+65...` (Singapore)
- Digits without `+` → prefixed with `+`
- Rows with a blank number are skipped

---

## Usage

Use `./run_rsvp.sh` (runs inside `venv/`) or `python3 send_rsvp_messages.py` directly.

```bash
# Defaults work out of the box — just drop your guest list in the repo folder
CSV="INF-INITY & FOREVER RSVP (Responses) - Messsage List.csv"

# 1. Dry run — preview the full dispatch plan, sends nothing
./run_rsvp.sh --dry-run

# 2. Test a single party (case-insensitive substring match on Party Name)
./run_rsvp.sh --party "Agnes Yeo"

# 3. Send to the first 3 parties only
./run_rsvp.sh --limit 3

# 4. Full dispatch with auto-resume
#    (skips any Party+Channel already logged SUCCESS in rsvp_send_log.csv)
./run_rsvp.sh --resume

# 5. Start from row 10, Telegram only, 10s delay
./run_rsvp.sh --start 10 --channels telegram --delay 10

# 6. Playwright method (scans QR code on first run)
./run_rsvp.sh --whatsapp-method playwright

# 7. Custom file locations
./run_rsvp.sh --csv "/path/to/other/list.csv" --log-file "/path/to/log.csv"
```

### All CLI flags

| Flag | Description | Default |
|---|---|---|
| `--csv PATH` | Path to the message-list CSV | `<repo>/...Messsage List.csv` |
| `--log-file PATH` | Path to the send log CSV | `<repo>/rsvp_send_log.csv` |
| `--dry-run` | Preview only — no messages sent, nothing logged | off |
| `--channels LIST` | Comma-separated: `whatsapp`, `telegram` | from `.env` |
| `--party NAME` | Filter parties (case-insensitive substring); also usable as a positional arg | all |
| `--limit N` | Process at most N parties | all |
| `--start N` | Start at row N (1-based) | `1` |
| `--delay SECONDS` | Pause between recipients | from `.env` (`6.0`) |
| `--resume` | Skip party+channel pairs already `SUCCESS` in the log | off |
| `--whatsapp-method` | `api` or `playwright` | from `.env` (`api`) |

> **Tip:** to pass a party name as a positional argument, quote it: `./run_rsvp.sh --csv "$CSV" "Agnes Yeo"`.

---

## How It Works

1. Reads every row of the CSV and normalizes the phone number.
2. For each active channel, sends the `Customised Message`:
   - **WhatsApp** → Twilio / Meta / Green API (auto-detected), or WhatsApp Web via Playwright
   - **Telegram** → Telethon. Looks up the phone in your existing contacts first; if not found, it *temporarily* imports the contact to message them, then **deletes it again** so your contact list stays untouched. If the number has no Telegram account, the row is logged as `FAILED`.
3. Every attempt is appended to `rsvp_send_log.csv` with timestamp, status, and provider details.
4. Waits `DISPATCH_DELAY` seconds before the next recipient.
5. On `Ctrl+C`, stops gracefully — rerun with `--resume` to pick up where you left off.

### Sample output

```
======================================================================
 WEDDING RSVP DISPATCHER (WHATSAPP & TELEGRAM)
======================================================================
CSV Source:       INF-INITY & FOREVER RSVP (Responses) - Messsage List.csv
Total Parties:    87
Channels:         WHATSAPP, TELEGRAM
Mode:             LIVE SENDING
WhatsApp Method:  API (TWILIO) [No browser / No QR code]
Telegram Config:  LOADED FROM .ENV
Inter-delay:      6.0s
Log File:         rsvp_send_log.csv
======================================================================

[1/87] Party: Agnes Yeo
      Phone: +6598463882
      [WHATSAPP] SUCCESS: Sent via Twilio WhatsApp API (SID: SM...)
      [TELEGRAM] SUCCESS: Sent to Telegram user Agnes (ID: 12345678)
...
======================================================================
 DISPATCH SUMMARY
======================================================================
Parties Processed: 87
  WHATSAPP Successful: 85
  TELEGRAM Successful: 80
Log written to: rsvp_send_log.csv
======================================================================
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `No WhatsApp API credentials provided in .env` | Fill in Twilio, Meta, *or* Green API keys in `.env` |
| Telegram skipped with a `[Notice]` | Fill in `TELEGRAM_API_ID` / `TELEGRAM_API_HASH` |
| `Phone ... does not have a registered Telegram account` | Guest isn't on Telegram — WhatsApp only for them |
| Messages sent twice after an interrupted run | Always rerun with `--resume` |
| Playwright "browser not installed" | Run `playwright install chromium` |
| Playwright login loop | Delete `~/.whatsapp_playwright_profile/` and rescan the QR code |

---

## Privacy

Guest data (names, phone numbers) and all API credentials are **git-ignored**. The `.csv`/`.xlsx` files, `.env`, and `venv/` will never be committed — keep it that way when contributing.
