"""
Web Control Dashboard for Gold & Stock Event Finders (With Telegram Settings & CoinDCX Links)
=============================================================================================
Provides a modern local web interface (http://localhost:5050) with:
  - Settings controls for Gold & Stock Event Finders
  - Telegram API configuration (Bot Token & Chat ID) + Instant Test Alert
  - Live Immediate Support & Resistance panel
  - Direct CoinDCX Gold Futures trade link (https://coindcx.com/futures/B-XAU_USDT)
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import json
import os
import sys

# Safe stdout/stderr fallback for pythonw (windowless python)
if sys.stdout is None:
    sys.stdout = open(os.path.join("utils", "logs", "dashboard.log"), "a", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.path.join("utils", "logs", "dashboard.log"), "a", encoding="utf-8")

from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
import pandas as pd
import yaml


try:
    from utils.env_settings import (apply_discord_secrets, apply_telegram_secrets,
                              save_notification_secrets)
    from gold.telegram_notifier import (load_telegram_config,
                                   send_telegram_message)
    from gold.xauusd_event_finder import (COINDCX_URL, EVENTS_CSV,
                                     DEFAULT_CONFIG as GOLD_EVENT_DEFAULTS,
                                     add_custom_label,
                                     compute_gold_levels,
                                     delete_custom_label,
                                     event_settings,
                                     fetch_latest_data,
                                     get_all_active_levels,
                                     session_high_low,
                                     _fmt_pct)
except ImportError:
    COINDCX_URL = "https://coindcx.com/futures/B-XAU_USDT"
    GOLD_EVENT_DEFAULTS = {
        "run_gold_event_finder": True,
        "show_gold_events": True,
        "gold_trigger_tol": 0.0020,
        "watch_exit_dist": 0.0040,
        "approach_dist": 0.0050,
        "session_extreme_arm": 0.01,
        "near_retrigger_sec": 0,
        "monitor_fast_sec": 30,
        "monitor_approach_sec": 60,
        "monitor_slow_sec": 300,
        "prev_day_hierarchy_tol": 0.0040,
        "run_stock_event_finder": True,
        "show_stock_events": True,
    }
    event_settings = lambda refresh=False: dict(GOLD_EVENT_DEFAULTS)
    _fmt_pct = lambda frac: f"{float(frac) * 100:.2f}"
    apply_discord_secrets = lambda c: c
    apply_telegram_secrets = lambda c: c
    save_notification_secrets = lambda **_kw: None

app = Flask(__name__)

DASHBOARD_LEVEL_LIMIT = 5

GOLD_CONFIG = os.path.join("gold", "config.yml")
STOCK_CONFIG = os.path.join("stock", "config.yml")
CONFIG_JSON = os.path.join("gold", "data", "event_config.json")

DEFAULT_CONFIG = {
    **GOLD_EVENT_DEFAULTS,
    "run_stock_event_finder": True,
    "show_stock_events": True,
    "telegram": {
        "enable_telegram": True,
        "bot_token": "",
        "chat_id": ""
    },
    "discord": {
        "enable_discord": True,
        "webhook_url": ""
    }
}


def _read_yml(path: str) -> dict:
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def load_config() -> dict:
    conf = DEFAULT_CONFIG.copy()
    conf["telegram"] = dict(DEFAULT_CONFIG["telegram"])
    conf["discord"] = dict(DEFAULT_CONFIG["discord"])
    for path in (GOLD_CONFIG, STOCK_CONFIG):
        raw_yml = _read_yml(path)
        if "event_finder" in raw_yml:
            conf.update(raw_yml["event_finder"])
        if "telegram" in raw_yml:
            conf["telegram"].update(raw_yml["telegram"])
        if "discord" in raw_yml:
            if "discord" not in conf or not isinstance(conf.get("discord"), dict):
                conf["discord"] = {"enable_discord": True, "webhook_url": ""}
            conf["discord"].update(raw_yml["discord"])

    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                json_conf = json.load(f)
                conf.update(json_conf)
        except Exception:
            pass

    if "telegram" not in conf or not isinstance(conf.get("telegram"), dict):
        conf["telegram"] = dict(DEFAULT_CONFIG["telegram"])
    if "discord" not in conf or not isinstance(conf.get("discord"), dict):
        conf["discord"] = dict(DEFAULT_CONFIG["discord"])
    apply_telegram_secrets(conf["telegram"])
    apply_discord_secrets(conf["discord"])
    return conf


def _public_json_config(conf: dict) -> dict:
    """Persist toggles only — tokens and webhook URL live in .env."""
    out = dict(conf)
    tg = dict(out.get("telegram") or {})
    tg.pop("bot_token", None)
    tg.pop("chat_id", None)
    out["telegram"] = tg
    disc = dict(out.get("discord") or {})
    disc.pop("webhook_url", None)
    out["discord"] = disc
    return out


def save_config(conf: dict):
    save_notification_secrets(
        telegram=conf.get("telegram") or {},
        discord=conf.get("discord") or {}
    )
    os.makedirs(os.path.dirname(CONFIG_JSON), exist_ok=True)
    with open(CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(_public_json_config(conf), f, indent=2)

    try:
        gold_yml = _read_yml(GOLD_CONFIG)
        existing_ef = dict(gold_yml.get("event_finder") or {})
        for key, default in GOLD_EVENT_DEFAULTS.items():
            if key in ("run_stock_event_finder", "show_stock_events"):
                continue
            existing_ef[key] = conf.get(key, existing_ef.get(key, default))
        existing_ef.pop("run_stock_event_finder", None)
        existing_ef.pop("show_stock_events", None)
        gold_yml["event_finder"] = existing_ef
        gold_yml["telegram"] = {
            "enable_telegram": (conf.get("telegram") or {}).get("enable_telegram", True)
        }
        gold_yml["discord"] = {
            "enable_discord": (conf.get("discord") or {}).get("enable_discord", True)
        }
        with open(GOLD_CONFIG, "w", encoding="utf-8") as f:
            yaml.dump(gold_yml, f, default_flow_style=False)

        stock_yml = _read_yml(STOCK_CONFIG)
        stock_ef = dict(stock_yml.get("event_finder") or {})
        stock_ef["run_stock_event_finder"] = bool(conf.get("run_stock_event_finder", True))
        stock_ef["show_stock_events"] = bool(conf.get("show_stock_events", False))
        stock_yml["event_finder"] = stock_ef
        with open(STOCK_CONFIG, "w", encoding="utf-8") as f:
            yaml.dump(stock_yml, f, default_flow_style=False)
    except Exception as e:
        print(f"Error updating config: {e}")


def get_gold_summary_data():
    try:
        df_daily, df_1m = fetch_latest_data()
        if df_1m.empty:
            if df_daily is None or df_daily.empty:
                return {"error": "No gold data"}
            date_col = df_daily.columns[0]
            latest_row = df_daily.iloc[-1]
            current_price = float(latest_row["Close"])
            time_str = str(latest_row[date_col]) + " (last weekday close)"
        else:
            dt_col = df_1m.columns[0]
            latest_row = df_1m.iloc[-1]
            current_price = float(latest_row["Close"])
            time_str = str(latest_row[dt_col])

        try:
            from gold.xauusd_event_finder import fetch_live_price
            live = float(fetch_live_price()["last"])
            if live > 0:
                current_price = live
                time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S") + " (live)"
        except Exception:
            pass

        levels = get_all_active_levels(df_daily, df_1m, current_price)
        from gold.xauusd_event_finder import (extra_display_pivots,
                                         session_arm_from_minute_bars,
                                         session_extreme_levels, _prepare_level_engine,
                                         _is_valid_px)
        s = event_settings()
        th, tl = session_high_low(df_daily, df_1m)
        if _is_valid_px(current_price):
            if _is_valid_px(th):
                th = max(float(th), float(current_price))
            if _is_valid_px(tl):
                tl = min(float(tl), float(current_price))

        armed = session_arm_from_minute_bars(df_daily, df_1m, current_price)
        armed_ids = {l["id"] for l in session_extreme_levels(th, tl, current_price, armed)}
        high_gap = ((float(th) - current_price) / float(th) * 100) if _is_valid_px(th) else None
        low_gap = ((current_price - float(tl)) / float(tl) * 100) if _is_valid_px(tl) else None
        session_range = {
            "high": round(float(th), 2) if _is_valid_px(th) else None,
            "low": round(float(tl), 2) if _is_valid_px(tl) else None,
            "high_gap_pct": round(high_gap, 2) if high_gap is not None else None,
            "low_gap_pct": round(low_gap, 2) if low_gap is not None else None,
            "high_is_level": bool(th) and f"TH_{float(th):.2f}" in armed_ids,
            "low_is_level": bool(tl) and f"TL_{float(tl):.2f}" in armed_ids,
            "arm_pct": round(s["session_extreme_arm"] * 100, 1)
        }

        extras = []
        try:
            engine = _prepare_level_engine(df_daily)
            extras = extra_display_pivots(engine, current_price, th, tl)
        except Exception:
            extras = []

        def _pick_side(side: str):
            combined = []
            seen = set()
            pool = list(levels) + list(extras)
            for l in pool:
                ltype = (l.get("type") or "").lower()
                if ltype and ltype != side:
                    continue
                lid = str(l.get("id") or "")
                if (lid.startswith("TH_") or lid.startswith("TL_") or
                        (l.get("name") or "") in ("Today's High", "Today's Low")):
                    if lid not in armed_ids:
                        continue
                if not ltype:
                    if side == "resistance" and l["price"] < current_price:
                        continue
                    if side == "support" and l["price"] > current_price:
                        continue
                key = round(float(l["price"]), 2)
                if key in seen:
                    continue
                seen.add(key)
                combined.append(l)
            if side == "resistance":
                combined.sort(key=lambda l: l["price"])
            else:
                combined.sort(key=lambda l: l["price"], reverse=True)
            picked = []
            for l in combined[:DASHBOARD_LEVEL_LIMIT]:
                if side == "support":
                    gap = ((current_price - l["price"]) / current_price) * 100
                else:
                    gap = ((l["price"] - current_price) / current_price) * 100
                picked.append({
                    "name": l["name"],
                    "timeframe": l["timeframe"],
                    "price": round(l["price"], 2),
                    "gap_pct": round(gap, 2)
                })
            return picked

        nearest_res = _pick_side("resistance")
        nearest_sup = _pick_side("support")

        events_list = []
        events_path = os.path.join("gold", "data", "gold_events_log.csv")
        if os.path.exists(events_path):
            try:
                df_evt = pd.read_csv(events_path)
                events_list = df_evt.tail(8).iloc[::-1].to_dict(orient="records")
            except Exception:
                pass

        monitor = {"interval_sec": 300, "watching": []}
        try:
            from gold.xauusd_event_finder import load_state, MONITOR_KEY
            st = load_state()
            monitor = st.get(MONITOR_KEY) or monitor
        except Exception:
            pass

        custom_list = []
        for l in levels:
            if not l.get("custom"):
                continue
            gap = ((l["price"] - current_price) / current_price) * 100
            custom_list.append({
                "id": l["id"],
                "name": l["name"],
                "price": round(l["price"], 2),
                "side": "resistance" if l["price"] > current_price else "support",
                "gap_pct": round(gap, 2)
            })
        custom_list.sort(key=lambda x: abs(x["gap_pct"]))

        return {
            "current_price": round(current_price, 2),
            "timestamp": time_str,
            "coindcx_url": COINDCX_URL,
            "nearest_resistances": nearest_res,
            "nearest_supports": nearest_sup,
            "session_range": session_range,
            "custom_labels": custom_list,
            "recent_events": events_list,
            "monitor": monitor
        }
    except Exception as e:
        return {"error": str(e)}


HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Event Finder Control Center & Telegram API</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-color: #0b0e14;
            --card-bg: #121721;
            --card-border: #1e2738;
            --accent-gold: #f39c12;
            --accent-green: #2ecc71;
            --accent-red: #e74c3c;
            --accent-blue: #3498db;
            --text-color: #e0e6ed;
            --text-muted: #8a99ad;
        }

        body {
            font-family: 'Inter', sans-serif;
            background-color: var(--bg-color);
            color: var(--text-color);
            margin: 0;
            padding: 30px 20px;
            display: flex;
            justify-content: center;
        }

        .container {
            max-width: 950px;
            width: 100%;
        }

        .header {
            text-align: center;
            margin-bottom: 30px;
        }

        .header h1 {
            font-size: 28px;
            font-weight: 700;
            color: var(--accent-gold);
            margin: 0 0 8px 0;
        }

        .header p {
            color: var(--text-muted);
            margin: 0;
            font-size: 14px;
        }

        .status-badge {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: #1c2433;
            border: 1px solid #2a374e;
            padding: 6px 14px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            margin-top: 12px;
        }

        .pulse-dot {
            width: 8px;
            height: 8px;
            background-color: var(--accent-green);
            border-radius: 50%;
            box-shadow: 0 0 10px var(--accent-green);
        }

        .card {
            background-color: var(--card-bg);
            border: 1px solid var(--card-border);
            border-radius: 12px;
            padding: 24px;
            margin-bottom: 24px;
            box-shadow: 0 10px 25px rgba(0, 0, 0, 0.4);
        }

        .card-title {
            font-size: 18px;
            font-weight: 600;
            margin-top: 0;
            margin-bottom: 20px;
            display: flex;
            align-items: center;
            justify-content: space-between;
            border-bottom: 1px solid var(--card-border);
            padding-bottom: 12px;
        }

        .price-hero {
            display: flex;
            align-items: center;
            justify-content: space-between;
            background: #1a2230;
            border: 1px solid #2b3952;
            padding: 16px 20px;
            border-radius: 8px;
            margin-bottom: 20px;
        }

        .session-range {
            display: flex;
            justify-content: space-between;
            gap: 16px;
            margin: -8px 0 18px 0;
            font-size: 13px;
            color: var(--text-muted);
        }
        .session-range span { color: var(--text-color); font-weight: 600; }
        .session-note { color: var(--text-muted); font-weight: 500; font-size: 12px; }

        .coindcx-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            background: #f39c12;
            color: #000000;
            text-decoration: none;
            font-weight: 700;
            font-size: 13px;
            padding: 8px 14px;
            border-radius: 6px;
            transition: background 0.2s ease;
        }
        .coindcx-btn:hover { background: #e67e22; }

        .levels-grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 16px;
        }

        .level-box {
            background: #161c28;
            border: 1px solid var(--card-border);
            border-radius: 8px;
            padding: 16px;
        }

        .level-box.res { border-left: 4px solid var(--accent-red); }
        .level-box.sup { border-left: 4px solid var(--accent-green); }

        .level-box h4 {
            margin: 0 0 10px 0;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }

        .level-box.res h4 { color: var(--accent-red); }
        .level-box.sup h4 { color: var(--accent-green); }

        .level-item {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 8px 0;
            border-bottom: 1px dashed rgba(255, 255, 255, 0.08);
        }
        .level-item:last-child { border-bottom: none; }

        .level-name { font-size: 14px; font-weight: 600; }
        .level-tf { font-size: 11px; color: var(--text-muted); background: #202b3c; padding: 2px 6px; border-radius: 4px; margin-left: 6px; }
        .level-val { font-size: 15px; font-weight: 700; }
        .gap-badge { font-size: 12px; margin-left: 6px; }
        .gap-badge.pos { color: var(--accent-red); }
        .gap-badge.neg { color: var(--accent-green); }

        .control-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 14px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }
        .control-row:last-child { border-bottom: none; }

        .control-info h4 { margin: 0 0 4px 0; font-size: 15px; font-weight: 600; }
        .control-info p { margin: 0; font-size: 13px; color: var(--text-muted); }

        .switch { position: relative; display: inline-block; width: 52px; height: 28px; }
        .switch input { opacity: 0; width: 0; height: 0; }
        .slider { position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #2c3e50; transition: .3s; border-radius: 28px; }
        .slider:before { position: absolute; content: ""; height: 20px; width: 20px; left: 4px; bottom: 4px; background-color: white; transition: .3s; border-radius: 50%; }
        input:checked + .slider { background-color: var(--accent-gold); }
        input:checked + .slider:before { transform: translateX(24px); }

        .number-input, .text-input {
            background-color: #1a2230;
            border: 1px solid #2a374e;
            color: #ffffff;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 14px;
            font-weight: 500;
        }

        .number-input { width: 90px; text-align: center; font-weight: 700; }
        .text-input { width: 280px; }
        .text-input-wide { width: 100%; max-width: 560px; }
        .btn-discord { background-color: #5865F2; color: #fff; }
        .btn-discord:hover { background-color: #4752c4; }

        .btn-group { display: flex; gap: 12px; margin-top: 20px; }
        .btn { flex: 1; padding: 12px 20px; border: none; border-radius: 8px; font-size: 14px; font-weight: 600; cursor: pointer; transition: all 0.2s ease; }
        .btn-primary { background-color: var(--accent-gold); color: #000; }
        .btn-primary:hover { background-color: #e67e22; }
        .btn-secondary { background-color: #2c3e50; color: #fff; }
        .btn-secondary:hover { background-color: #34495e; }
        .btn-telegram { background-color: #0088cc; color: #fff; }
        .btn-telegram:hover { background-color: #0077b5; }

        table { width: 100%; border-collapse: collapse; margin-top: 10px; }
        th, td { text-align: left; padding: 10px; font-size: 13px; border-bottom: 1px solid #1e2738; }
        th { color: var(--text-muted); font-weight: 600; background: #161c28; }
        .tag-evt { background: #e74c3c22; color: #e74c3c; padding: 3px 8px; border-radius: 4px; font-weight: 600; font-size: 11px; }

        .trade-link { color: var(--accent-gold); text-decoration: underline; font-weight: 600; }

        .hint {
            color: var(--text-muted);
            font-size: 13px;
            line-height: 1.5;
            margin: 0 0 16px 0;
        }

        .custom-add-row {
            display: flex;
            gap: 10px;
            align-items: center;
            flex-wrap: wrap;
            margin-bottom: 16px;
        }
        .custom-add-row .text-input { width: 220px; }
        .custom-add-row .number-input { width: 120px; }
        .btn-add { flex: none; padding: 9px 16px; background: var(--accent-gold); color: #000; border: none; border-radius: 8px; font-weight: 700; cursor: pointer; }
        .btn-add:hover { background: #e67e22; }
        .btn-danger { background: #7b1e1e; color: #fff; border: none; border-radius: 6px; padding: 5px 10px; font-size: 12px; font-weight: 600; cursor: pointer; }
        .btn-danger:hover { background: var(--accent-red); }
        .side-res { color: var(--accent-red); font-weight: 600; }
        .side-sup { color: var(--accent-green); font-weight: 600; }

        #toast { visibility: hidden; min-width: 250px; background-color: #2ecc71; color: #000; text-align: center; border-radius: 8px; padding: 12px; position: fixed; z-index: 1000; right: 30px; bottom: 30px; font-weight: 600; box-shadow: 0 4px 15px rgba(0,0,0,0.5); }
        #toast.show { visibility: visible; animation: fadein 0.5s, fadeout 0.5s 2.5s; }
        @keyframes fadein { from {bottom: 0; opacity: 0;} to {bottom: 30px; opacity: 1;} }
        @keyframes fadeout { from {bottom: 30px; opacity: 1;} to {bottom: 0; opacity: 0;} }
    </style>
</head>
<body>

<div class="container">
    <div class="header">
        <h1>📊 EVENT FINDER CONTROL CENTER</h1>
        <p>Live Dashboard, Telegram Alerts & Direct CoinDCX Link</p>
        <div class="status-badge">
            <div class="pulse-dot"></div>
            <span id="monitor_status_text">SYSTEM ACTIVE & MONITORING</span>
        </div>
    </div>

    <!-- LIVE SPOT GOLD PANEL -->
    <div class="card">
        <div class="card-title">
            <span>⚡ LIVE COINDCX XAUUSDT IMMEDIATE LEVELS</span>
            <div>
                <a href="https://coindcx.com/futures/B-XAU_USDT" target="_blank" class="coindcx-btn">🚀 Trade on CoinDCX</a>
                <button onclick="fetchGoldLive()" style="background: #243044; border: none; color: var(--text-color); padding: 7px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; margin-left: 6px;">🔄 Refresh</button>
            </div>
        </div>

        <div class="price-hero">
            <div>
                <span style="color: var(--text-muted); font-size: 13px; text-transform: uppercase; font-weight: 600;">CoinDCX XAUUSDT Price</span>
                <div class="price-big" id="spot_price_display">$0.00 USD</div>
            </div>
            <div style="text-align: right;">
                <span style="color: var(--text-muted); font-size: 12px;">Last Data Refresh</span>
                <div id="spot_time_display" style="font-size: 13px; font-weight: 600; color: var(--text-color); margin-top: 4px;">--:--:--</div>
            </div>
        </div>
        <div class="session-range" id="session_range_row">
            <div>Today H: <span id="session_high_display">--</span> <span class="session-note" id="session_high_note"></span></div>
            <div>Today L: <span id="session_low_display">--</span> <span class="session-note" id="session_low_note"></span></div>
        </div>

        <div class="levels-grid">
            <div class="level-box res">
                <h4>📈 Resistances (up to 5 above)</h4>
                <div id="res_list">
                    <div style="color: var(--text-muted); font-size: 13px;">Loading levels...</div>
                </div>
            </div>

            <div class="level-box sup">
                <h4>📉 Supports (up to 5 below)</h4>
                <div id="sup_list">
                    <div style="color: var(--text-muted); font-size: 13px;">Loading levels...</div>
                </div>
            </div>
        </div>
    </div>

    <!-- TELEGRAM API CONFIGURATION CARD -->
    <div class="card">
        <div class="card-title">
            <span>✈️ TELEGRAM API NOTIFICATION CONTROLS</span>
            <button onclick="sendTestTelegram()" class="btn btn-telegram" style="flex:none; padding: 6px 14px; font-size: 12px;">🧪 Send Test Telegram Alert</button>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>Enable Telegram Notifications</h4>
                <p>Sends Startup Summary, Event Trigger Alerts, and 30-min Level Updates</p>
            </div>
            <label class="switch">
                <input type="checkbox" id="enable_telegram">
                <span class="slider"></span>
            </label>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>Telegram Bot Token</h4>
                <p>Bot token from @BotFather. Stored in local <code>.env</code>, not in git.</p>
            </div>
            <div>
                <input type="text" id="tg_bot_token" class="text-input" placeholder="Paste Bot Token here">
            </div>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>Telegram Chat ID</h4>
                <p>Your Telegram User or Channel Chat ID. Stored in local <code>.env</code>.</p>
            </div>
            <div>
                <input type="text" id="tg_chat_id" class="text-input" placeholder="Paste Chat ID here">
            </div>
        </div>
    </div>

    <!-- DISCORD WEBHOOK CONFIGURATION CARD -->
    <div class="card">
        <div class="card-title">
            <span>💬 DISCORD WEBHOOK NOTIFICATION CONTROLS</span>
            <button onclick="sendTestDiscord()" class="btn btn-discord" style="flex:none; padding: 6px 14px; font-size: 12px;">🧪 Send Test Discord Alert</button>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>Enable Discord Notifications</h4>
                <p>Sends the same Startup, Event Trigger, and 30-min updates as Telegram</p>
            </div>
            <label class="switch">
                <input type="checkbox" id="enable_discord">
                <span class="slider"></span>
            </label>
        </div>

        <div class="control-row" style="flex-direction: column; align-items: stretch; gap: 8px;">
            <div class="control-info">
                <h4>Discord Webhook URL</h4>
                <p>From channel settings → Integrations → Webhooks. Saved in local <code>.env</code> as DISCORD_WEBHOOK_URL (not committed).</p>
            </div>
            <input type="text" id="discord_webhook" class="text-input text-input-wide" placeholder="Paste Discord webhook URL here">
        </div>
    </div>

    <!-- Gold Settings Card -->
    <div class="card">
        <div class="card-title">
            <span>🥇 SPOT GOLD EVENT FINDER CONTROLS</span>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>1. Run Gold Event Finder Service</h4>
                <p>Master toggle: Enable or Disable 5-minute background monitoring</p>
            </div>
            <label class="switch">
                <input type="checkbox" id="run_gold_event_finder">
                <span class="slider"></span>
            </label>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>2. Show Gold Events & Alert Popups</h4>
                <p>If OFF, service runs silently in background logging events without popups</p>
            </div>
            <label class="switch">
                <input type="checkbox" id="show_gold_events">
                <span class="slider"></span>
            </label>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>3. Max Trigger Distance / Tolerance (%)</h4>
                <p>Price proximity threshold to trigger an event (Default: 0.20%)</p>
            </div>
            <div>
                <input type="number" step="0.05" min="0.01" max="5.0" id="gold_trigger_tol_pct" class="number-input" value="0.20"> <span style="color: var(--text-muted); font-size: 14px;">%</span>
            </div>
        </div>
        <p class="hint">Sleep: <b>{{ slow_min }} min</b> normally. Inside <b>{{ approach_pct }}%</b> of a label (no alert) → <b>1 min</b> checks. Inside the trigger distance (default <b>{{ near_pct }}%</b>) → <b>one NEAR</b> alert and <b>30s</b> until <b>TOUCH</b>. No second NEAR while price stays near that label. Pull back past <b>{{ watch_pct }}%</b> re-arms NEAR. A touched label is cancelled for the rest of the day. <b>Today's High</b> is added only after price drops <b>{{ arm_pct }}%</b> from it; <b>Today's Low</b> only after price rallies <b>{{ arm_pct }}%</b> from it. After that they use the same {{ approach_pct }}% / {{ near_pct }}% / touch watch. All of these are in <b>config.yml → event_finder</b>.</p>
    </div>

    <!-- Custom Gold Labels -->
    <div class="card">
        <div class="card-title">
            <span>🎯 CUSTOM GOLD TRIGGER LABELS</span>
        </div>
        <p class="hint">
            Add any prices you want watched. Same rules as the other gold labels:
            Same watch as the other gold labels. Inside {{ approach_pct }}% → 1-minute checks (no alert).
            NEAR at the trigger distance (default {{ near_pct }}%) starts 30-second checks; TOUCH sends
            “price touched the label”. Past {{ watch_pct }}% re-arms NEAR. Sitting near the label
            does not send another NEAR.
            The label is removed only when price trades through it.
        </p>
        <div class="custom-add-row">
            <input type="text" id="custom_label_name" class="text-input" placeholder="Name (optional)">
            <input type="number" id="custom_label_price" class="number-input" step="0.01" min="0.01" placeholder="Price">
            <button class="btn-add" onclick="addCustomLabel()">+ Add Label</button>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Name</th>
                    <th>Price</th>
                    <th>Side</th>
                    <th>Gap</th>
                    <th></th>
                </tr>
            </thead>
            <tbody id="custom_labels_body">
                <tr><td colspan="5" style="color: var(--text-muted);">No custom labels yet.</td></tr>
            </tbody>
        </table>
    </div>

    <!-- Stock Settings Card -->
    <div class="card">
        <div class="card-title">
            <span>📈 STOCK MARKET EVENT FINDER CONTROLS</span>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>4. Run Stock Event Finder Service</h4>
                <p>Enable or Disable stock market level screener runs</p>
            </div>
            <label class="switch">
                <input type="checkbox" id="run_stock_event_finder">
                <span class="slider"></span>
            </label>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>5. Show Stock Event Notifications</h4>
                <p>Show Windows notifications when stock levels are hit</p>
            </div>
            <label class="switch">
                <input type="checkbox" id="show_stock_events">
                <span class="slider"></span>
            </label>
        </div>
    </div>

    <!-- Recent Triggered Events Log Table -->
    <div class="card">
        <div class="card-title">
            <span>📜 RECENT TRIGGERED EVENTS LOG</span>
        </div>
        <table>
            <thead>
                <tr>
                    <th>Timestamp</th>
                    <th>Status</th>
                    <th>Level Name</th>
                    <th>Timeframe</th>
                    <th>Level Price</th>
                    <th>Spot Price</th>
                    <th>Gap</th>
                    <th>Trade Link</th>
                </tr>
            </thead>
            <tbody id="events_table_body">
                <tr><td colspan="8" style="color: var(--text-muted);">No events logged yet today.</td></tr>
            </tbody>
        </table>
    </div>

    <!-- Save & Run Buttons -->
    <div class="btn-group">
        <button class="btn btn-primary" onclick="saveSettings()">💾 SAVE CONFIGURATION</button>
        <button class="btn btn-secondary" onclick="runManualCheck()">⚡ RUN MANUAL CHECK NOW</button>
    </div>
</div>

<div id="toast">Settings Saved Successfully!</div>

<script>
    async function fetchConfig() {
        try {
            const res = await fetch('/api/config');
            const data = await res.json();
            
            document.getElementById('run_gold_event_finder').checked = data.run_gold_event_finder;
            document.getElementById('show_gold_events').checked = data.show_gold_events;
            document.getElementById('gold_trigger_tol_pct').value = (data.gold_trigger_tol * 100).toFixed(2);
            document.getElementById('run_stock_event_finder').checked = data.run_stock_event_finder;
            document.getElementById('show_stock_events').checked = data.show_stock_events;

            if (data.telegram) {
                document.getElementById('enable_telegram').checked = data.telegram.enable_telegram !== false;
                document.getElementById('tg_bot_token').value = data.telegram.bot_token || '';
                document.getElementById('tg_chat_id').value = data.telegram.chat_id || '';
            }
            if (data.discord) {
                document.getElementById('enable_discord').checked = data.discord.enable_discord !== false;
                document.getElementById('discord_webhook').value = data.discord.webhook_url || '';
            }
        } catch (e) {
            console.error("Error fetching config:", e);
        }
    }

    async function fetchGoldLive() {
        try {
            const res = await fetch('/api/gold_summary');
            const data = await res.json();
            if (data.error) return;

            document.getElementById('spot_price_display').innerText = '$' + data.current_price.toLocaleString() + ' USD';
            document.getElementById('spot_time_display').innerText = data.timestamp;

            const sr = data.session_range || {};
            const arm = sr.arm_pct != null ? sr.arm_pct : 2;
            if (sr.high != null) {
                document.getElementById('session_high_display').innerText = '$' + Number(sr.high).toLocaleString();
                document.getElementById('session_high_note').innerText = sr.high_is_level
                    ? `(${sr.high_gap_pct}% below — level, price already dropped ${arm}% off this high)`
                    : `(${sr.high_gap_pct}% below — not a level until price is ${arm}% below this high)`;
            }
            if (sr.low != null) {
                document.getElementById('session_low_display').innerText = '$' + Number(sr.low).toLocaleString();
                document.getElementById('session_low_note').innerText = sr.low_is_level
                    ? `(${sr.low_gap_pct}% above — level, price already rallied ${arm}% off this low)`
                    : `(${sr.low_gap_pct}% above — not a level until price is ${arm}% above this low)`;
            }

            let resHtml = '';
            data.nearest_resistances.forEach((r, idx) => {
                resHtml += `
                    <div class="level-item">
                        <div>
                            <span class="level-name">R${idx+1}: ${r.name}</span>
                            <span class="level-tf">${r.timeframe}</span>
                        </div>
                        <div>
                            <span class="level-val">$${r.price.toLocaleString()}</span>
                            <span class="gap-badge pos">+${r.gap_pct}%</span>
                        </div>
                    </div>`;
            });
            document.getElementById('res_list').innerHTML = resHtml || '<div style="color:var(--text-muted); font-size:13px;">No resistance found</div>';

            let supHtml = '';
            data.nearest_supports.forEach((s, idx) => {
                supHtml += `
                    <div class="level-item">
                        <div>
                            <span class="level-name">S${idx+1}: ${s.name}</span>
                            <span class="level-tf">${s.timeframe}</span>
                        </div>
                        <div>
                            <span class="level-val">$${s.price.toLocaleString()}</span>
                            <span class="gap-badge neg">-${s.gap_pct}%</span>
                        </div>
                    </div>`;
            });
            document.getElementById('sup_list').innerHTML = supHtml || '<div style="color:var(--text-muted); font-size:13px;">No support found</div>';

            renderCustomLabels(data.custom_labels || []);

            const mon = data.monitor || {};
            const watching = mon.watching || [];
            const approaching = mon.approaching || [];
            const monEl = document.getElementById('monitor_status_text');
            if (monEl) {
                const sec = Number(mon.interval_sec);
                if (watching.length && sec <= 30) {
                    monEl.textContent = '30s WATCH: ' + watching.join(', ');
                } else if (approaching.length || sec === 60) {
                    monEl.textContent = '1m APPROACH: ' + (approaching.join(', ') || watching.join(', '));
                } else {
                    monEl.textContent = 'SYSTEM ACTIVE & MONITORING (5 min)';
                }
            }

            if (data.recent_events && data.recent_events.length > 0) {
                let evtHtml = '';
                data.recent_events.forEach(e => {
                    const status = (e.status || 'NEAR').toString().toUpperCase();
                    evtHtml += `
                        <tr>
                            <td>${e.timestamp}</td>
                            <td><strong>${status}</strong></td>
                            <td><strong>${e.level_name}</strong></td>
                            <td>${e.timeframe}</td>
                            <td>$${e.level_price}</td>
                            <td>$${e.spot_price}</td>
                            <td>${e.dist_pct}%</td>
                            <td><a href="https://coindcx.com/futures/B-XAU_USDT" target="_blank" class="trade-link">🚀 Open CoinDCX</a></td>
                        </tr>`;
                });
                document.getElementById('events_table_body').innerHTML = evtHtml;
            }
        } catch (e) {
            console.error("Error fetching live gold summary:", e);
        }
    }

    async function saveSettings() {
        const payload = {
            run_gold_event_finder: document.getElementById('run_gold_event_finder').checked,
            show_gold_events: document.getElementById('show_gold_events').checked,
            gold_trigger_tol: parseFloat(document.getElementById('gold_trigger_tol_pct').value) / 100.0,
            run_stock_event_finder: document.getElementById('run_stock_event_finder').checked,
            show_stock_events: document.getElementById('show_stock_events').checked,
            telegram: {
                enable_telegram: document.getElementById('enable_telegram').checked,
                bot_token: document.getElementById('tg_bot_token').value.trim(),
                chat_id: document.getElementById('tg_chat_id').value.trim()
            },
            discord: {
                enable_discord: document.getElementById('enable_discord').checked,
                webhook_url: document.getElementById('discord_webhook').value.trim()
            }
        };

        try {
            const res = await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            });
            if (res.ok) {
                showToast("Configuration Saved!");
                fetchGoldLive();
            }
        } catch (e) {
            alert("Error saving settings: " + e);
        }
    }

    async function sendTestTelegram() {
        await saveSettings();
        showToast("Sending Test Telegram Message...");
        try {
            const res = await fetch('/api/test_telegram', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                showToast("✅ Test Telegram Sent Successfully!");
            } else {
                alert("Telegram Failed: " + data.message);
            }
        } catch (e) {
            alert("Error sending test telegram: " + e);
        }
    }

    async function sendTestDiscord() {
        await saveSettings();
        showToast("Sending Test Discord Message...");
        try {
            const res = await fetch('/api/test_discord', { method: 'POST' });
            const data = await res.json();
            if (data.status === 'success') {
                showToast("✅ Discord sent. Open your SERVER channel (not DMs).");
                if (data.jump_url) {
                    window.open(data.jump_url, '_blank');
                }
            } else {
                alert("Discord Failed: " + data.message);
            }
        } catch (e) {
            alert("Error sending test Discord: " + e);
        }
    }

    async function runManualCheck() {
        showToast("Running Manual Check...");
        try {
            const res = await fetch('/api/run_check', { method: 'POST' });
            const data = await res.json();
            showToast(data.message);
            setTimeout(fetchGoldLive, 3000);
        } catch (e) {
            alert("Error running check: " + e);
        }
    }

    function esc(s) {
        return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }

    function renderCustomLabels(labels) {
        const body = document.getElementById('custom_labels_body');
        if (!labels || labels.length === 0) {
            body.innerHTML = '<tr><td colspan="5" style="color: var(--text-muted);">No custom labels yet.</td></tr>';
            return;
        }
        let html = '';
        labels.forEach(l => {
            const side = l.side === 'resistance' ? '<span class="side-res">Resistance (above)</span>' : '<span class="side-sup">Support (below)</span>';
            const gap = (l.gap_pct >= 0 ? '+' : '') + l.gap_pct + '%';
            html += `
                <tr>
                    <td><strong>${esc(l.name)}</strong></td>
                    <td>$${Number(l.price).toLocaleString()}</td>
                    <td>${side}</td>
                    <td>${gap}</td>
                    <td><button class="btn-danger" onclick="deleteCustomLabel('${esc(l.id)}')">Remove</button></td>
                </tr>`;
        });
        body.innerHTML = html;
    }

    async function addCustomLabel() {
        const name = document.getElementById('custom_label_name').value.trim();
        const price = parseFloat(document.getElementById('custom_label_price').value);
        if (!price || price <= 0) {
            alert('Enter a valid gold price for the custom label.');
            return;
        }
        try {
            const res = await fetch('/api/custom_labels', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, price })
            });
            const data = await res.json();
            if (!res.ok || data.status === 'error') {
                alert(data.message || 'Could not add custom label.');
                return;
            }
            document.getElementById('custom_label_name').value = '';
            document.getElementById('custom_label_price').value = '';
            showToast('Custom label added');
            fetchGoldLive();
        } catch (e) {
            alert('Error adding custom label: ' + e);
        }
    }

    async function deleteCustomLabel(id) {
        try {
            const res = await fetch('/api/custom_labels/' + encodeURIComponent(id), { method: 'DELETE' });
            const data = await res.json();
            if (!res.ok || data.status === 'error') {
                alert(data.message || 'Could not remove custom label.');
                return;
            }
            showToast('Custom label removed');
            fetchGoldLive();
        } catch (e) {
            alert('Error removing custom label: ' + e);
        }
    }

    function showToast(msg) {
        const toast = document.getElementById("toast");
        toast.innerText = msg;
        toast.className = "show";
        setTimeout(() => { toast.className = toast.className.replace("show", ""); }, 3000);
    }

    fetchConfig();
    fetchGoldLive();
    setInterval(fetchGoldLive, 10000);
</script>

</body>
</html>
"""


@app.route("/")
def index():
    s = event_settings(refresh=True)
    return render_template_string(
        HTML_TEMPLATE,
        near_pct=_fmt_pct(s["gold_trigger_tol"]),
        watch_pct=_fmt_pct(s["watch_exit_dist"]),
        approach_pct=_fmt_pct(s["approach_dist"]),
        arm_pct=_fmt_pct(s["session_extreme_arm"]),
        slow_min=max(1, int(s["monitor_slow_sec"]) // 60),
    )


@app.route("/api/config", methods=["GET"])
def get_config_api():
    return jsonify(load_config())


@app.route("/api/config", methods=["POST"])
def post_config_api():
    new_conf = request.json
    conf = load_config()
    conf.update(new_conf)
    save_config(conf)
    return jsonify({"status": "success", "config": conf})


@app.route("/api/gold_summary", methods=["GET"])
def get_gold_summary_api():
    return jsonify(get_gold_summary_data())


@app.route("/api/test_telegram", methods=["POST"])
def test_telegram_api():
    try:
        from gold.telegram_notifier import send_telegram_message
        msg = (
            "🧪 <b>TELEGRAM BOT API TEST SUCCESSFUL!</b>\n"
            "--------------------------------------------------\n"
            "Your Event Finder Telegram notifications are active."
        )
        ok = send_telegram_message(msg)
        if ok:
            return jsonify({"status": "success", "message": "Test Telegram message sent!"})
        else:
            return jsonify({"status": "error", "message": "Could not send message. Please check your Bot Token and Chat ID."})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/api/test_discord", methods=["POST"])
def test_discord_api():
    try:
        from discord_notifier import send_discord_message_detailed, html_to_discord
        msg = html_to_discord(
            "🧪 <b>DISCORD WEBHOOK TEST SUCCESSFUL!</b>\n"
            "--------------------------------------------------\n"
            "Look in this **server text channel** (not Discord DMs, not the Developer Portal).\n"
            "The sender name is **EventFinder**."
        )
        ok, detail = send_discord_message_detailed(msg)
        if ok:
            return jsonify({
                "status": "success",
                "message": "Test Discord message sent! Open your Discord server channel — not DMs.",
                "jump_url": detail if str(detail).startswith("http") else ""
            })
        return jsonify({"status": "error", "message": detail}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



@app.route("/api/run_check", methods=["POST"])
def run_check_api():
    import subprocess
    try:
        subprocess.Popen(
            [sys.executable, str(_ROOT / "gold" / "xauusd_event_finder.py")],
            cwd=str(_ROOT),
        )
        return jsonify({"status": "success", "message": "Manual Event Check Triggered!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


@app.route("/api/custom_labels", methods=["POST"])
def add_custom_label_api():
    payload = request.json or {}
    try:
        price = float(payload.get("price", 0))
    except (TypeError, ValueError):
        return jsonify({"status": "error", "message": "Enter a valid price."}), 400

    name = str(payload.get("name", "")).strip()
    current_price = today_high = today_low = None
    try:
        df_daily, df_1m = fetch_latest_data()
        if df_1m is not None and not df_1m.empty:
            current_price = float(df_1m.iloc[-1]["Close"])
        elif df_daily is not None and not df_daily.empty:
            current_price = float(df_daily.iloc[-1]["Close"])
        today_high, today_low = session_high_low(df_daily, df_1m)
    except Exception:
        pass

    try:
        label = add_custom_label(
            price,
            name=name,
            current_price=current_price,
            today_high=today_high,
            today_low=today_low
        )
        return jsonify({"status": "success", "label": label})
    except ValueError as e:
        return jsonify({"status": "error", "message": str(e)}), 400
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/api/custom_labels/<label_id>", methods=["DELETE"])
def delete_custom_label_api(label_id):
    try:
        if delete_custom_label(label_id):
            return jsonify({"status": "success"})
        return jsonify({"status": "error", "message": "Label not found."}), 404
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == "__main__":
    print("=" * 70)
    print(" STARTING EVENT FINDER WEB DASHBOARD SERVER")
    print(" Dashboard URL: http://localhost:5050")
    print(" CoinDCX Link: https://coindcx.com/futures/B-XAU_USDT")
    print("=" * 70)
    app.run(host="0.0.0.0", port=5050, debug=False)
