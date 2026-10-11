#!/usr/bin/env python3
"""
send_rsvp_messages.py
---------------------
Dispatches wedding RSVP verification messages from the CSV to WhatsApp and Telegram
using configuration and API credentials loaded directly from a .env file.

Usage examples:
  # 1. Dry run (preview without sending anything):
  python3 send_rsvp_messages.py --dry-run

  # 2. Test sending to a single party:
  python3 send_rsvp_messages.py --party "Agnes Yeo"

  # 3. Send to first 3 rows:
  python3 send_rsvp_messages.py --limit 3

  # 4. Full dispatch with auto-resume:
  python3 send_rsvp_messages.py --resume
"""

import argparse
import csv
import os
import sys
import time
import urllib.parse
from datetime import datetime
from pathlib import Path

try:
    import nest_asyncio
    nest_asyncio.apply()
except ImportError:
    pass

# Try loading .env automatically
try:
    from dotenv import load_dotenv
    # Look for .env in current directory or script directory
    script_dir = Path(__file__).resolve().parent
    env_file = script_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=True)
    else:
        load_dotenv(override=True)
except ImportError:
    pass

# Paths (relative to this script's directory, so it works regardless of cwd)
DEFAULT_CSV_PATH = script_dir / "INF-INITY & FOREVER RSVP (Responses) - Messsage List.csv"
DEFAULT_LOG_PATH = script_dir / "rsvp_send_log.csv"


def clean_phone_number(raw_phone: str) -> str:
    """Normalize phone number to international E.164 format (e.g. +6598463882)."""
    p = raw_phone.strip().replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not p:
        return ""
    if p.startswith("+"):
        return p
    # Singapore 8-digit numbers without prefix
    if len(p) == 8 and (p.startswith("8") or p.startswith("9")):
        return f"+65{p}"
    # Standard numbers with country code but missing + (e.g. 6598463882 or 8201065487188)
    return f"+{p}"


# ---------------------------------------------------------------------------
# 1. WhatsApp Dispatchers (API vs Playwright Browser)
# ---------------------------------------------------------------------------
def send_whatsapp_twilio(phone: str, message: str) -> tuple[bool, str]:
    """Sends WhatsApp message via Twilio API without opening any browser or QR code."""
    account_sid = os.getenv("TWILIO_ACCOUNT_SID")
    auth_token = os.getenv("TWILIO_AUTH_TOKEN")
    from_wa = os.getenv("TWILIO_WHATSAPP_NUMBER", "whatsapp:+14155238886").strip()

    if not account_sid or not auth_token:
        return False, "Twilio credentials missing in .env (TWILIO_ACCOUNT_SID / TWILIO_AUTH_TOKEN)"

    if not from_wa.startswith("whatsapp:"):
        from_wa = f"whatsapp:{from_wa}"

    to_wa = f"whatsapp:{phone}"

    try:
        import requests
        url = f"https://api.twilio.com/2010-04-01/Accounts/{account_sid}/Messages.json"
        data = {"From": from_wa, "To": to_wa, "Body": message}
        resp = requests.post(url, data=data, auth=(account_sid, auth_token), timeout=20)
        if resp.status_code in (200, 201):
            sid = resp.json().get("sid", "OK")
            return True, f"Sent via Twilio WhatsApp API (SID: {sid})"
        return False, f"Twilio Error {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, f"Twilio exception: {str(e)}"


def send_whatsapp_meta_cloud(phone: str, message: str) -> tuple[bool, str]:
    """Sends WhatsApp message via Meta Cloud API without opening any browser or QR code."""
    phone_number_id = os.getenv("META_WA_PHONE_NUMBER_ID")
    access_token = os.getenv("META_WA_ACCESS_TOKEN")

    if not phone_number_id or not access_token:
        return False, "Meta Cloud API credentials missing in .env (META_WA_PHONE_NUMBER_ID / META_WA_ACCESS_TOKEN)"

    clean_digits = phone.lstrip("+")
    try:
        import requests
        url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }
        payload = {
            "messaging_product": "whatsapp",
            "to": clean_digits,
            "type": "text",
            "text": {"preview_url": False, "body": message}
        }
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        if resp.status_code in (200, 201):
            return True, "Sent via Meta WhatsApp Cloud API"
        return False, f"Meta Cloud API Error {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, f"Meta Cloud API exception: {str(e)}"


def send_whatsapp_green_api(phone: str, message: str) -> tuple[bool, str]:
    """Sends WhatsApp message via Green API without opening any browser."""
    instance_id = os.getenv("GREEN_API_INSTANCE_ID")
    token = os.getenv("GREEN_API_TOKEN")

    if not instance_id or not token:
        return False, "Green API credentials missing in .env"

    clean_digits = phone.lstrip("+")
    chat_id = f"{clean_digits}@c.us"
    try:
        import requests
        url = f"https://api.green-api.com/waInstance{instance_id}/sendMessage/{token}"
        payload = {"chatId": chat_id, "message": message}
        resp = requests.post(url, json=payload, timeout=20)
        if resp.status_code == 200:
            return True, "Sent via Green API"
        return False, f"Green API Error {resp.status_code}: {resp.text}"
    except Exception as e:
        return False, f"Green API exception: {str(e)}"


def send_whatsapp_playwright(phone: str, message: str, page) -> tuple[bool, str]:
    """Automates WhatsApp Web in persistent Chromium session using Playwright."""
    phone_digits = phone.lstrip("+")
    encoded_text = urllib.parse.quote(message)
    url = f"https://web.whatsapp.com/send?phone={phone_digits}&text={encoded_text}"
    try:
        page.goto(url, wait_until="networkidle", timeout=45000)
        send_btn = page.wait_for_selector('span[data-icon="send"], button[aria-label="Send"]', timeout=20000)
        if send_btn:
            send_btn.click()
            time.sleep(2)
            return True, "Sent via Playwright WhatsApp Web"
        return False, "Send button not found on WhatsApp Web page"
    except Exception as e:
        return False, f"Playwright WhatsApp error: {str(e)}"


# ---------------------------------------------------------------------------
# 2. Telegram Dispatcher (Telethon Client via .env)
# ---------------------------------------------------------------------------
def send_telegram_telethon(phone: str, party_name: str, message: str, client) -> tuple[bool, str]:
    """Sends message via Telegram Client API (Telethon) without altering your address book."""
    try:
        from telethon.tl.types import InputPhoneContact
        from telethon.tl.functions.contacts import ImportContactsRequest, DeleteContactsRequest

        async def _send():
            # 1. Try to find the user directly (preserves their existing contact name in your phone)
            user = None
            is_new_contact = False
            try:
                user = await client.get_entity(phone)
            except Exception:
                user = None

            # 2. If not found, temporarily import contact by phone number
            if not user:
                contact = InputPhoneContact(client_id=0, phone=phone, first_name=party_name[:30], last_name="")
                result = await client(ImportContactsRequest([contact]))
                if not result.users:
                    return False, f"Phone {phone} does not have a registered Telegram account"
                user = result.users[0]
                is_new_contact = True

            # 3. Send message
            await client.send_message(user, message)

            # 4. If this was a temporary contact, delete it from your address book
            # so your Telegram contact list remains completely clean and untouched
            if is_new_contact:
                try:
                    await client(DeleteContactsRequest(id=[user.id]))
                except Exception:
                    pass

            return True, f"Sent to Telegram user {user.first_name or ''} (ID: {user.id})"

        return client.loop.run_until_complete(_send())
    except Exception as e:
        return False, f"Telethon error: {str(e)}"


# ---------------------------------------------------------------------------
# Logging & State Tracking
# ---------------------------------------------------------------------------
def init_log(log_path: Path):
    if not log_path.exists():
        with open(log_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Timestamp", "Party Name", "Phone", "Channel", "Status", "Details"])


def log_send(log_path: Path, party: str, phone: str, channel: str, status: str, details: str):
    with open(log_path, "a", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow([datetime.now().isoformat(), party, phone, channel, status, details])


def get_sent_set(log_path: Path) -> set[tuple[str, str]]:
    """Returns set of (party_name, channel) pairs that were already successfully SENT."""
    sent = set()
    if not log_path.exists():
        return sent
    with open(log_path, "r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for r in reader:
            if r.get("Status") == "SUCCESS":
                sent.add((r.get("Party Name", "").strip(), r.get("Channel", "").strip().lower()))
    return sent


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------
def main():
    default_channels = os.getenv("CHANNELS", "whatsapp,telegram")
    default_delay = float(os.getenv("DISPATCH_DELAY", "6.0"))
    default_wa_method = os.getenv("WHATSAPP_METHOD", "api")

    parser = argparse.ArgumentParser(description="Send wedding RSVP confirmation messages to WhatsApp and Telegram using .env config.")
    parser.add_argument("--csv", type=Path, default=DEFAULT_CSV_PATH, help="Path to Messsage List CSV file")
    parser.add_argument("--channels", type=str, default=default_channels, help="Comma-separated channels: whatsapp,telegram (default from .env)")
    parser.add_argument("--dry-run", action="store_true", help="Preview dispatch plan without sending any messages")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of parties to process")
    parser.add_argument("--start", type=int, default=1, help="Row index (1-based) to start from")
    parser.add_argument("party_pos", nargs="?", default=None, help="Filter to a specific Party Name (positional)")
    parser.add_argument("--party", dest="party_opt", type=str, default=None, help="Filter to a specific Party Name")
    parser.add_argument("--delay", type=float, default=default_delay, help="Seconds delay between party recipients (default from .env)")
    parser.add_argument("--resume", action="store_true", help="Skip (Party, Channel) already successfully logged in sent log")
    parser.add_argument("--whatsapp-method", choices=["api", "playwright"], default=default_wa_method, help="WhatsApp sending method: api (Twilio/Meta/Green) or playwright")
    parser.add_argument("--log-file", type=Path, default=DEFAULT_LOG_PATH, help="Path to CSV send log")

    args = parser.parse_args()

    active_channels = [c.strip().lower() for c in args.channels.split(",") if c.strip()]
    valid_channels = {"whatsapp", "telegram"}
    for c in active_channels:
        if c not in valid_channels:
            print(f"Error: Unknown channel '{c}'. Supported: {', '.join(sorted(valid_channels))}")
            sys.exit(1)

    if not args.csv.exists():
        print(f"Error: CSV file not found: {args.csv}")
        sys.exit(1)

    init_log(args.log_file)
    already_sent = get_sent_set(args.log_file) if args.resume else set()

    # Determine WhatsApp API provider if method is "api"
    wa_api_provider = "NONE"
    if "whatsapp" in active_channels:
        if os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN"):
            wa_api_provider = "TWILIO"
        elif os.getenv("META_WA_ACCESS_TOKEN") and os.getenv("META_WA_PHONE_NUMBER_ID"):
            wa_api_provider = "META_CLOUD"
        elif os.getenv("GREEN_API_TOKEN") and os.getenv("GREEN_API_INSTANCE_ID"):
            wa_api_provider = "GREEN_API"

    # Read CSV rows
    with open(args.csv, "r", encoding="utf-8", newline="") as f:
        reader = list(csv.DictReader(f))

    print("=" * 70)
    print(" WEDDING RSVP DISPATCHER (WHATSAPP & TELEGRAM)")
    print("=" * 70)
    print(f"CSV Source:       {args.csv.name}")
    print(f"Total Parties:    {len(reader)}")
    print(f"Channels:         {', '.join(active_channels).upper()}")
    print(f"Mode:             {'DRY RUN (Simulation)' if args.dry_run else 'LIVE SENDING'}")
    if "whatsapp" in active_channels:
        if args.whatsapp_method == "api":
            print(f"WhatsApp Method:  API ({wa_api_provider}) [No browser / No QR code]")
        else:
            print(f"WhatsApp Method:  PLAYWRIGHT (WhatsApp Web)")
    print(f"Telegram Config:  {'LOADED FROM .ENV' if os.getenv('TELEGRAM_API_ID') else 'NOT CONFIGURED IN .ENV'}")
    print(f"Inter-delay:      {args.delay}s")
    print(f"Log File:         {args.log_file}")
    print("=" * 70)

    # Initialize Playwright if requested
    pw_browser_context = None
    pw_page = None
    if not args.dry_run and "whatsapp" in active_channels and args.whatsapp_method == "playwright":
        try:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            user_data = Path.home() / ".whatsapp_playwright_profile"
            pw_browser_context = pw.chromium.launch_persistent_context(user_data_dir=user_data, headless=False)
            pw_page = pw_browser_context.new_page()
            pw_page.goto("https://web.whatsapp.com")
            print("\n[WhatsApp Playwright] WhatsApp Web opened. Waiting 15s for login/chats...")
            time.sleep(15)
        except Exception as e:
            print(f"\n[Error] Playwright initialization failed: {e}")
            sys.exit(1)

    # Initialize Telethon if requested
    tg_client = None
    if not args.dry_run and "telegram" in active_channels:
        tg_api_id = os.getenv("TELEGRAM_API_ID")
        tg_api_hash = os.getenv("TELEGRAM_API_HASH")
        if tg_api_id and tg_api_hash:
            try:
                from telethon import TelegramClient
                session_path = Path.home() / ".telegram_session"
                tg_client = TelegramClient(str(session_path), int(tg_api_id), tg_api_hash)
                tg_client.loop.run_until_complete(tg_client.connect())
                if not tg_client.loop.run_until_complete(tg_client.is_user_authorized()):
                    tg_phone = os.getenv("TELEGRAM_PHONE")
                    tg_client.start(phone=tg_phone) if tg_phone else tg_client.start()
                print("\n[Telegram Telethon] Connected successfully.")
            except Exception as e:
                print(f"\n[Warning] Telegram connection failed: {e}")
                tg_client = None
        else:
            print("\n[Notice] TELEGRAM_API_ID / TELEGRAM_API_HASH not filled in .env.")
            print("         Telegram will be skipped until credentials are provided.")

    processed = 0
    success_counts = {c: 0 for c in active_channels}

    try:
        for idx, row in enumerate(reader, start=1):
            if idx < args.start:
                continue
            if args.limit and processed >= args.limit:
                break

            party_name = row.get("Party Name", "").strip()
            raw_phone = row.get("Number to send", "").strip()
            message = row.get("Customised Message", "").strip()

            target_party = args.party_opt or args.party_pos
            if target_party and target_party.lower() not in party_name.lower():
                continue

            phone = clean_phone_number(raw_phone)
            print(f"\n[{idx}/{len(reader)}] Party: {party_name}")
            print(f"      Phone: {phone if phone else '[BLANK - NO PHONE]'}")

            if not phone:
                print("      -> SKIPPED (No contact number available)")
                continue

            processed += 1

            for ch in active_channels:
                if args.resume and (party_name, ch) in already_sent:
                    print(f"      [{ch.upper()}] SKIPPED (Already sent in previous run)")
                    continue

                if args.dry_run:
                    print(f"      [{ch.upper()}] [DRY-RUN] Would send message ({len(message)} chars)")
                    continue

                # 1. WhatsApp
                if ch == "whatsapp":
                    if args.whatsapp_method == "api":
                        if wa_api_provider == "TWILIO":
                            ok, info = send_whatsapp_twilio(phone, message)
                        elif wa_api_provider == "META_CLOUD":
                            ok, info = send_whatsapp_meta_cloud(phone, message)
                        elif wa_api_provider == "GREEN_API":
                            ok, info = send_whatsapp_green_api(phone, message)
                        else:
                            ok, info = False, "No WhatsApp API credentials provided in .env (add TWILIO or META_WA credentials)"
                    elif args.whatsapp_method == "playwright" and pw_page:
                        ok, info = send_whatsapp_playwright(phone, message, pw_page)
                    else:
                        ok, info = False, "WhatsApp sending method not configured"

                    status = "SUCCESS" if ok else "FAILED"
                    log_send(args.log_file, party_name, phone, ch, status, info)
                    print(f"      [WHATSAPP] {status}: {info}")
                    if ok:
                        success_counts[ch] += 1

                # 2. Telegram
                elif ch == "telegram":
                    if tg_client:
                        ok, info = send_telegram_telethon(phone, party_name, message, tg_client)
                    else:
                        ok, info = False, "Telegram credentials (TELEGRAM_API_ID / TELEGRAM_API_HASH) missing in .env"
                    status = "SUCCESS" if ok else "FAILED"
                    log_send(args.log_file, party_name, phone, ch, status, info)
                    print(f"      [TELEGRAM] {status}: {info}")
                    if ok:
                        success_counts[ch] += 1

            # Inter-party safety delay
            if not args.dry_run and args.delay > 0 and processed < len(reader):
                time.sleep(args.delay)

    except KeyboardInterrupt:
        print("\n[Interrupted] Script stopped by user (Ctrl+C).")
    finally:
        if pw_browser_context:
            try:
                pw_browser_context.close()
            except Exception:
                pass
        if tg_client and tg_client.is_connected():
            try:
                tg_client.disconnect()
            except Exception:
                pass

    print("\n" + "=" * 70)
    print(" DISPATCH SUMMARY")
    print("=" * 70)
    print(f"Parties Processed: {processed}")
    if not args.dry_run:
        for ch in active_channels:
            print(f"  {ch.upper()} Successful: {success_counts[ch]}")
        print(f"Log written to: {args.log_file}")
    else:
        print("Dry run completed successfully. No messages were dispatched.")
    print("=" * 70)


if __name__ == "__main__":
    main()
