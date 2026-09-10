"""
Discord webhook notifier for Gold Event Finder alerts.
Sends the same event types as Telegram: startup, trigger, and 30-min update.
"""

import json
import os
import urllib.error
import urllib.request
import yaml

from env_settings import apply_discord_secrets

CONFIG_YML = "config.yml"
CONFIG_JSON = os.path.join("data", "gold_xauusd", "event_config.json")


def load_discord_config() -> dict:
    conf = {
        "enable_discord": True,
        "webhook_url": ""
    }
    if os.path.exists(CONFIG_YML):
        try:
            with open(CONFIG_YML, "r", encoding="utf-8") as f:
                raw_yml = yaml.safe_load(f)
                if raw_yml and "discord" in raw_yml:
                    conf.update(raw_yml["discord"])
        except Exception:
            pass

    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                json_conf = json.load(f)
                if "discord" in json_conf:
                    conf.update(json_conf["discord"])
        except Exception:
            pass

    return apply_discord_secrets(conf)


def html_to_discord(text: str) -> str:
    t = (text or "")
    t = t.replace("<b>", "**").replace("</b>", "**")
    t = t.replace("<code>", "`").replace("</code>", "`")
    return t


def _wait_url(webhook_url: str) -> str:
    if "wait=" in webhook_url:
        return webhook_url
    return webhook_url + ("&" if "?" in webhook_url else "?") + "wait=true"


def _webhook_base(webhook_url: str) -> str:
    return webhook_url.split("?")[0].strip()


def _webhook_location(webhook_url: str) -> tuple:
    """Return (guild_id, channel_id) from a webhook GET."""
    try:
        req = urllib.request.Request(
            _webhook_base(webhook_url),
            headers={"User-Agent": "Mozilla/5.0 EventFinder"},
            method="GET"
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8", errors="replace"))
            return str(data.get("guild_id") or ""), str(data.get("channel_id") or "")
    except Exception:
        return "", ""


def send_discord_message_detailed(message_text: str,
                                  title: str = "EventFinder Gold Alert",
                                  color: int = 0xF39C12) -> tuple:
    """Return (ok, detail). detail is a jump URL on success, or an error string."""
    cfg = load_discord_config()
    if not cfg.get("enable_discord", True):
        return False, "Discord notifications are turned OFF in the dashboard."

    webhook_url = str(cfg.get("webhook_url", "")).strip()
    if not webhook_url:
        return False, "Webhook URL is missing."

    payload = json.dumps({
        "username": "EventFinder",
        "embeds": [{
            "title": title or "EventFinder Gold Alert",
            "description": (message_text or "")[:4096],
            "color": int(color)
        }]
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            _wait_url(webhook_url),
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 EventFinder"
            },
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=15) as response:
            raw = response.read().decode("utf-8", errors="replace")
            jump = ""
            if raw:
                try:
                    data = json.loads(raw)
                    guild_id = str(data.get("guild_id") or "")
                    channel_id = str(data.get("channel_id") or "")
                    message_id = str(data.get("id") or "")
                    if not guild_id:
                        g2, c2 = _webhook_location(webhook_url)
                        guild_id = guild_id or g2
                        channel_id = channel_id or c2
                    if guild_id and channel_id and message_id:
                        jump = f"https://discord.com/channels/{guild_id}/{channel_id}/{message_id}"
                    elif guild_id and channel_id:
                        jump = f"https://discord.com/channels/{guild_id}/{channel_id}"
                except Exception:
                    pass
            if 200 <= response.status < 300:
                if not jump:
                    g2, c2 = _webhook_location(webhook_url)
                    if g2 and c2:
                        jump = f"https://discord.com/channels/{g2}/{c2}"
                return True, jump or "sent"
            return False, f"Discord returned HTTP {response.status}"
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")[:400]
        return False, f"HTTP {e.code}: {err or e.reason}"
    except Exception as e:
        return False, str(e)


def send_discord_message(message_text: str,
                         title: str = "EventFinder Gold Alert",
                         color: int = 0xF39C12) -> bool:
    ok, detail = send_discord_message_detailed(message_text, title=title, color=color)
    if not ok:
        print(f"[Discord Error] {detail}")
    return ok


def send_discord_html(html_text: str,
                      title: str = "EventFinder Gold Alert",
                      color: int = 0xF39C12) -> bool:
    return send_discord_message(html_to_discord(html_text), title=title, color=color)
