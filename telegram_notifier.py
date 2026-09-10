"""
Telegram Notifier Module for Gold & Stock Event Finders (Clean Levels & Prices)
==============================================================================
Sends Telegram notifications with Spot Gold price, Immediate Support & Resistance levels, and % gaps.
(CoinDCX link removed from Telegram as requested).
"""

import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
import yaml

from env_settings import apply_telegram_secrets

CONFIG_YML = "config.yml"
CONFIG_JSON = os.path.join("data", "gold_xauusd", "event_config.json")


def load_telegram_config() -> dict:
    conf = {
        "enable_telegram": True,
        "bot_token": "",
        "chat_id": ""
    }
    if os.path.exists(CONFIG_YML):
        try:
            with open(CONFIG_YML, "r", encoding="utf-8") as f:
                raw_yml = yaml.safe_load(f)
                if raw_yml and "telegram" in raw_yml:
                    conf.update(raw_yml["telegram"])
        except Exception:
            pass

    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                json_conf = json.load(f)
                if "telegram" in json_conf:
                    conf.update(json_conf["telegram"])
        except Exception:
            pass

    return apply_telegram_secrets(conf)


def send_telegram_message(message_text: str) -> bool:
    """Send message via Telegram Bot API using HTML parse_mode."""
    cfg = load_telegram_config()
    if not cfg.get("enable_telegram", True):
        return False

    bot_token = cfg.get("bot_token", "").strip()
    chat_id = cfg.get("chat_id", "").strip()

    if not bot_token or not chat_id:
        print("[Telegram Warning] Bot Token or Chat ID is missing.")
        return False

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True
    }

    try:
        data = urllib.parse.urlencode(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as response:
            res_json = json.loads(response.read().decode("utf-8"))
            return res_json.get("ok", False)
    except Exception as e:
        print(f"[Telegram Error] Could not send message: {e}")
        return False


def _broadcast(html_text: str,
               discord_title: str = "EventFinder Gold Alert",
               discord_color: int = 0xF39C12) -> bool:
    """Send to Telegram (if enabled) and Discord (if enabled)."""
    tg_ok = send_telegram_message(html_text)
    try:
        from discord_notifier import send_discord_html
        send_discord_html(html_text, title=discord_title, color=discord_color)
    except Exception as e:
        print(f"[Discord Broadcast Warning]: {e}")
    return tg_ok


def send_startup_summary(current_price: float, resistances: list, supports: list):
    """Message Type 1: Sent when laptop boots up and background service starts."""
    msg = (
        "🚀 <b>LAPTOP STARTED -- GOLD EVENT FINDER ACTIVE</b>\n"
        "--------------------------------------------------\n"
        f"🟡 <b>Current CoinDCX XAUUSDT</b>: <code>${current_price:,.2f}</code>\n\n"
        "📈 <b>Immediate Resistances (Above)</b>:\n"
    )

    if resistances:
        for idx, r in enumerate(resistances[:2], 1):
            msg += f"  • <b>R{idx}</b>: {r['name']} ({r['timeframe']}) @ <code>${r['price']:,.2f}</code> (+{r['gap_pct']:.2f}%)\n"
    else:
        msg += "  • None\n"

    msg += "\n📉 <b>Immediate Supports (Below)</b>:\n"
    if supports:
        for idx, s in enumerate(supports[:2], 1):
            msg += f"  • <b>S{idx}</b>: {s['name']} ({s['timeframe']}) @ <code>${s['price']:,.2f}</code> (-{s['gap_pct']:.2f}%)\n"
    else:
        msg += "  • None\n"

    return _broadcast(msg)


def send_event_trigger_alert(event_dict: dict):
    """NEAR: price entered the 0.20% band. TOUCH: price actually hit the label."""
    lname = event_dict.get("level_name", "Key Level")
    ltf = event_dict.get("timeframe", "Daily")
    lprice = event_dict.get("level_price", 0.0)
    sprice = event_dict.get("spot_price", 0.0)
    gap_pct = event_dict.get("dist_pct", 0.0)
    status = str(event_dict.get("status") or "NEAR").upper()

    if status == "TOUCH":
        msg = (
            f"✋ <b>PRICE TOUCHED THE LABEL {lname}</b>\n"
            "--------------------------------------------------\n"
            f"📍 <b>Level</b>: <b>{lname}</b> ({ltf})\n"
            f"🎯 <b>Level Price</b>: <code>${lprice:,.2f}</code>\n"
            f"🟡 <b>Spot Price</b>: <code>${sprice:,.2f}</code>\n"
            f"📏 <b>Gap</b>: <code>{gap_pct:.2f}%</code>\n"
            "⏱ Back to <b>5-minute</b> checks."
        )
        sent = _broadcast(
            msg,
            discord_title=f"PRICE TOUCHED THE LABEL {lname}",
            discord_color=0xE74C3C
        )
        schedule_30min_post_event_update()
        return sent

    msg = (
        "🎯 <b>GOLD NEAR LEVEL</b>\n"
        "--------------------------------------------------\n"
        f"📍 <b>Level</b>: <b>{lname}</b> ({ltf})\n"
        f"🎯 <b>Level Price</b>: <code>${lprice:,.2f}</code>\n"
        f"🟡 <b>Spot Price</b>: <code>${sprice:,.2f}</code>\n"
        f"📏 <b>Proximity Gap</b>: <code>{gap_pct:.2f}%</code> (Under 0.20%)\n"
        "⏱ Watching every <b>30 seconds</b> until price touches this label. "
        "If it pulls back past <b>0.30%</b>, checks go to <b>1 minute</b> until <b>0.50%</b>."
    )
    return _broadcast(
        msg,
        discord_title=f"GOLD NEAR LEVEL: {lname}",
        discord_color=0xF39C12
    )


def schedule_30min_post_event_update():
    """Message Type 3: Scheduled in background thread to run 30 minutes after an event."""
    def _post_event_job():
        print("[Telegram Scheduler] Waiting 30 minutes to send post-event updated levels...")
        time.sleep(1800)
        try:
            from xauusd_event_finder import (compute_stock_screener_levels,
                                             fetch_latest_data)
            df_daily, df_1m = fetch_latest_data()
            if not df_1m.empty:
                current_price = float(df_1m.iloc[-1]["Close"])
                levels = compute_stock_screener_levels(df_daily, df_1m, current_price)
                
                resistances = []
                supports = []
                for l in levels:
                    if l["price"] > current_price:
                        gap = ((l["price"] - current_price) / current_price) * 100
                        resistances.append({"name": l["name"], "timeframe": l["timeframe"], "price": l["price"], "gap_pct": gap})
                    elif l["price"] < current_price:
                        gap = ((current_price - l["price"]) / current_price) * 100
                        supports.append({"name": l["name"], "timeframe": l["timeframe"], "price": l["price"], "gap_pct": gap})

                resistances.sort(key=lambda x: x["price"])
                supports.sort(key=lambda x: x["price"], reverse=True)

                msg = (
                    "🔄 <b>30-MINUTE POST-EVENT LEVEL UPDATE</b>\n"
                    "--------------------------------------------------\n"
                    "Fresh updated level labels after recent price action:\n\n"
                    f"🟡 <b>Current CoinDCX XAUUSDT</b>: <code>${current_price:,.2f}</code>\n\n"
                    "📈 <b>Updated Resistances</b>:\n"
                )
                for idx, r in enumerate(resistances[:2], 1):
                    msg += f"  • <b>R{idx}</b>: {r['name']} ({r['timeframe']}) @ <code>${r['price']:,.2f}</code> (+{r['gap_pct']:.2f}%)\n"
                
                msg += "\n📉 <b>Updated Supports</b>:\n"
                for idx, s in enumerate(supports[:2], 1):
                    msg += f"  • <b>S{idx}</b>: {s['name']} ({s['timeframe']}) @ <code>${s['price']:,.2f}</code> (-{s['gap_pct']:.2f}%)\n"

                _broadcast(msg)
        except Exception as e:
            print(f"[Telegram Post-Event Error]: {e}")

    t = threading.Thread(target=_post_event_job, daemon=True)
    t.start()
