"""
Automatic Telegram Chat ID Finder
=================================
Run this script to automatically detect your Telegram User ID or Channel ID!
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import json
import os
import sys
import time
import urllib.parse
import urllib.request
import yaml

from utils.env_settings import TELEGRAM_BOT_TOKEN, env_get, save_notification_secrets

CONFIG_YML = os.path.join("gold", "config.yml")
CONFIG_JSON = os.path.join("gold", "data", "event_config.json")


def _bot_token() -> str:
    return env_get(TELEGRAM_BOT_TOKEN)


def save_detected_chat_id(chat_id_str: str):
    print(f"\n[SUCCESS] Detected Telegram Chat ID: {chat_id_str}")
    token = _bot_token()
    save_notification_secrets(telegram={"bot_token": token, "chat_id": chat_id_str})
    print("  [Saved] -> .env")

    try:
        conf = {}
        if os.path.exists(CONFIG_JSON):
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                conf = json.load(f)
        if "telegram" not in conf:
            conf["telegram"] = {}
        conf["telegram"]["enable_telegram"] = True
        conf["telegram"].pop("bot_token", None)
        conf["telegram"].pop("chat_id", None)
        os.makedirs(os.path.dirname(CONFIG_JSON), exist_ok=True)
        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(conf, f, indent=2)
        print(f"  [Saved] -> {CONFIG_JSON}")
    except Exception as e:
        print(f"Error saving JSON: {e}")

    try:
        raw_yml = {}
        if os.path.exists(CONFIG_YML):
            with open(CONFIG_YML, "r", encoding="utf-8") as f:
                raw_yml = yaml.safe_load(f) or {}
        if "telegram" not in raw_yml:
            raw_yml["telegram"] = {}
        raw_yml["telegram"]["enable_telegram"] = True
        raw_yml["telegram"].pop("bot_token", None)
        raw_yml["telegram"].pop("chat_id", None)
        with open(CONFIG_YML, "w", encoding="utf-8") as f:
            yaml.dump(raw_yml, f, default_flow_style=False)
        print(f"  [Saved] -> {CONFIG_YML}")
    except Exception as e:
        print(f"Error saving YAML: {e}")

    try:
        from gold.telegram_notifier import send_telegram_message
        send_telegram_message("🎉 *TELEGRAM CONNECTED SUCCESSFULLY!*\nYour Chat ID has been saved.")
        print("  [Sent] -> Confirmation message sent to your Telegram!")
    except Exception as e:
        print(f"Error sending confirmation: {e}")


def listen_for_chat_id():
    token = _bot_token()
    print("=" * 70)
    print(" TELEGRAM CHAT ID AUTO-DETECTOR")
    print("=" * 70)
    if not token:
        print(" Missing TELEGRAM_BOT_TOKEN in .env")
        return None
    print(f" Bot Token: {token[:8]}...")
    print("\nINSTRUCTIONS:")
    print(" 1. Open Telegram on your Phone or Computer.")
    print(" 2. Open your Bot chat and press 'START' or send ANY message (e.g. 'hi').")
    print(" 3. Waiting for your message... (press Ctrl+C to cancel)\n")

    start_time = time.time()
    last_update_id = 0

    while time.time() - start_time < 300:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={last_update_id + 1}&timeout=5"
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                results = data.get("result", [])

                for item in results:
                    last_update_id = item["update_id"]

                    if "message" in item:
                        chat = item["message"]["chat"]
                        cid = str(chat["id"])
                        cname = chat.get("first_name", chat.get("title", "User"))
                        print(f" -> Found Message from: {cname} (ID: {cid})")
                        save_detected_chat_id(cid)
                        return cid

                    elif "channel_post" in item:
                        chat = item["channel_post"]["chat"]
                        cid = str(chat["id"])
                        ctitle = chat.get("title", "Channel")
                        print(f" -> Found Channel Post in: {ctitle} (ID: {cid})")
                        save_detected_chat_id(cid)
                        return cid

        except Exception:
            pass

        time.sleep(1)

    print("\n[Timeout] No message received within 5 minutes.")
    return None


if __name__ == "__main__":
    listen_for_chat_id()
