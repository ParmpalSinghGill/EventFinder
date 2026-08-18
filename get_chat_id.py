"""
Automatic Telegram Chat ID Finder
=================================
Run this script to automatically detect your Telegram User ID or Channel ID!
"""

import json
import os
import sys
import time
import urllib.parse
import urllib.request
import yaml

BOT_TOKEN = "8952946545:AAFLYnADSfcF7PEwkpLPh-0oOj4Md1bIExE"
CONFIG_YML = "config.yml"
CONFIG_JSON = os.path.join("data", "gold_xauusd", "event_config.json")
ENV_FILE = ".env"


def save_detected_chat_id(chat_id_str: str):
    print(f"\n[SUCCESS] Detected Telegram Chat ID: {chat_id_str}")

    # 1. Save in .env
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        f.write(f"TELEGRAM_BOT_TOKEN={BOT_TOKEN}\n")
        f.write(f"TELEGRAM_CHAT_ID={chat_id_str}\n")
    print(f"  [Saved] -> {ENV_FILE}")

    # 2. Save in event_config.json
    try:
        conf = {}
        if os.path.exists(CONFIG_JSON):
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                conf = json.load(f)
        if "telegram" not in conf:
            conf["telegram"] = {}
        conf["telegram"]["enable_telegram"] = True
        conf["telegram"]["bot_token"] = BOT_TOKEN
        conf["telegram"]["chat_id"] = chat_id_str
        with open(CONFIG_JSON, "w", encoding="utf-8") as f:
            json.dump(conf, f, indent=2)
        print(f"  [Saved] -> {CONFIG_JSON}")
    except Exception as e:
        print(f"Error saving JSON: {e}")

    # 3. Save in config.yml
    try:
        raw_yml = {}
        if os.path.exists(CONFIG_YML):
            with open(CONFIG_YML, "r", encoding="utf-8") as f:
                raw_yml = yaml.safe_load(f) or {}
        if "telegram" not in raw_yml:
            raw_yml["telegram"] = {}
        raw_yml["telegram"]["enable_telegram"] = True
        raw_yml["telegram"]["bot_token"] = BOT_TOKEN
        raw_yml["telegram"]["chat_id"] = chat_id_str
        with open(CONFIG_YML, "w", encoding="utf-8") as f:
            yaml.dump(raw_yml, f, default_flow_style=False)
        print(f"  [Saved] -> {CONFIG_YML}")
    except Exception as e:
        print(f"Error saving YAML: {e}")

    # 4. Send Confirmation Test Telegram Message
    try:
        from telegram_notifier import send_telegram_message
        send_telegram_message("🎉 *TELEGRAM CONNECTED SUCCESSFULLY!*\nYour Chat ID has been saved.")
        print("  [Sent] -> Confirmation message sent to your Telegram!")
    except Exception as e:
        print(f"Error sending confirmation: {e}")


def listen_for_chat_id():
    print("=" * 70)
    print(" TELEGRAM CHAT ID AUTO-DETECTOR")
    print("=" * 70)
    print(f" Bot Token: {BOT_TOKEN}")
    print("\nINSTRUCTIONS:")
    print(" 1. Open Telegram on your Phone or Computer.")
    print(" 2. Open your Bot chat and press 'START' or send ANY message (e.g. 'hi').")
    print(" 3. Waiting for your message... (press Ctrl+C to cancel)\n")

    start_time = time.time()
    last_update_id = 0

    while time.time() - start_time < 300:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates?offset={last_update_id + 1}&timeout=5"
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
