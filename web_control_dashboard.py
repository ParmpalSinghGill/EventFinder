"""
Web Control Dashboard for Gold & Stock Event Finders (With Telegram Settings & CoinDCX Links)
=============================================================================================
Provides a modern local web interface (http://localhost:5050) with:
  - Settings controls for Gold & Stock Event Finders
  - Telegram API configuration (Bot Token & Chat ID) + Instant Test Alert
  - Live Immediate Support & Resistance panel
  - Direct CoinDCX Gold Futures trade link (https://coindcx.com/futures/B-XAU_USDT)
"""

import json
import os
import sys

# Safe stdout/stderr fallback for pythonw (windowless python)
if sys.stdout is None:
    sys.stdout = open(os.path.join("data", "dashboard.log"), "a", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.path.join("data", "dashboard.log"), "a", encoding="utf-8")

from datetime import datetime
from flask import Flask, jsonify, render_template_string, request
import pandas as pd
import yaml


sys.path.append(os.getcwd())
try:
    from telegram_notifier import (load_telegram_config,
                                   send_telegram_message)
    from xauusd_event_finder import (COINDCX_URL, EVENTS_CSV,
                                     compute_stock_screener_levels,
                                     fetch_latest_data)
except ImportError:
    COINDCX_URL = "https://coindcx.com/futures/B-XAU_USDT"

app = Flask(__name__)

CONFIG_YML = "config.yml"
CONFIG_JSON = os.path.join("data", "gold_xauusd", "event_config.json")

DEFAULT_CONFIG = {
    "run_gold_event_finder": True,
    "show_gold_events": True,
    "gold_trigger_tol": 0.0020,
    "run_stock_event_finder": True,
    "show_stock_events": True,
    "telegram": {
        "enable_telegram": True,
        "bot_token": "",
        "chat_id": ""
    }
}


def load_config() -> dict:
    conf = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_YML):
        try:
            with open(CONFIG_YML, "r", encoding="utf-8") as f:
                raw_yml = yaml.safe_load(f)
                if raw_yml:
                    if "event_finder" in raw_yml:
                        conf.update(raw_yml["event_finder"])
                    if "telegram" in raw_yml:
                        conf["telegram"].update(raw_yml["telegram"])
        except Exception:
            pass

    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                json_conf = json.load(f)
                conf.update(json_conf)
        except Exception:
            pass

    return conf


def save_config(conf: dict):
    os.makedirs(os.path.dirname(CONFIG_JSON), exist_ok=True)
    with open(CONFIG_JSON, "w", encoding="utf-8") as f:
        json.dump(conf, f, indent=2)

    try:
        raw_yml = {}
        if os.path.exists(CONFIG_YML):
            with open(CONFIG_YML, "r", encoding="utf-8") as f:
                raw_yml = yaml.safe_load(f) or {}

        raw_yml["event_finder"] = {
            "run_gold_event_finder": conf.get("run_gold_event_finder", True),
            "show_gold_events": conf.get("show_gold_events", True),
            "gold_trigger_tol": conf.get("gold_trigger_tol", 0.0020),
            "run_stock_event_finder": conf.get("run_stock_event_finder", True),
            "show_stock_events": conf.get("show_stock_events", True)
        }
        raw_yml["telegram"] = conf.get("telegram", {})

        with open(CONFIG_YML, "w", encoding="utf-8") as f:
            yaml.dump(raw_yml, f, default_flow_style=False)
    except Exception as e:
        print(f"Error updating config.yml: {e}")


def get_gold_summary_data():
    try:
        df_daily, df_1m = fetch_latest_data()
        if df_1m.empty:
            return {"error": "No 1-minute data"}

        dt_col = df_1m.columns[0]
        latest_row = df_1m.iloc[-1]
        current_price = float(latest_row["Close"])
        time_str = str(latest_row[dt_col])

        levels = compute_stock_screener_levels(df_daily, df_1m, current_price)

        resistances = [l for l in levels if l["price"] > current_price]
        supports = [l for l in levels if l["price"] < current_price]

        resistances.sort(key=lambda l: l["price"])
        supports.sort(key=lambda l: l["price"], reverse=True)

        nearest_res = []
        for r in resistances[:2]:
            gap = ((r["price"] - current_price) / current_price) * 100
            nearest_res.append({
                "name": r["name"],
                "timeframe": r["timeframe"],
                "price": round(r["price"], 2),
                "gap_pct": round(gap, 2)
            })

        nearest_sup = []
        for s in supports[:2]:
            gap = ((current_price - s["price"]) / current_price) * 100
            nearest_sup.append({
                "name": s["name"],
                "timeframe": s["timeframe"],
                "price": round(s["price"], 2),
                "gap_pct": round(gap, 2)
            })

        events_list = []
        events_path = os.path.join("data", "gold_xauusd", "gold_events_log.csv")
        if os.path.exists(events_path):
            try:
                df_evt = pd.read_csv(events_path)
                events_list = df_evt.tail(6).iloc[::-1].to_dict(orient="records")
            except Exception:
                pass

        return {
            "current_price": round(current_price, 2),
            "timestamp": time_str,
            "coindcx_url": COINDCX_URL,
            "nearest_resistances": nearest_res,
            "nearest_supports": nearest_sup,
            "recent_events": events_list
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

        .price-big {
            font-size: 30px;
            font-weight: 700;
            color: var(--accent-gold);
        }

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
            <span>SYSTEM ACTIVE & MONITORING</span>
        </div>
    </div>

    <!-- LIVE SPOT GOLD PANEL -->
    <div class="card">
        <div class="card-title">
            <span>⚡ LIVE SPOT GOLD (XAU/USD) IMMEDIATE LEVELS</span>
            <div>
                <a href="https://coindcx.com/futures/B-XAU_USDT" target="_blank" class="coindcx-btn">🚀 Trade on CoinDCX</a>
                <button onclick="fetchGoldLive()" style="background: #243044; border: none; color: var(--text-color); padding: 7px 12px; border-radius: 6px; cursor: pointer; font-size: 12px; margin-left: 6px;">🔄 Refresh</button>
            </div>
        </div>

        <div class="price-hero">
            <div>
                <span style="color: var(--text-muted); font-size: 13px; text-transform: uppercase; font-weight: 600;">Spot Gold Current Price</span>
                <div class="price-big" id="spot_price_display">$0.00 USD</div>
            </div>
            <div style="text-align: right;">
                <span style="color: var(--text-muted); font-size: 12px;">Last Data Refresh</span>
                <div id="spot_time_display" style="font-size: 13px; font-weight: 600; color: var(--text-color); margin-top: 4px;">--:--:--</div>
            </div>
        </div>

        <div class="levels-grid">
            <div class="level-box res">
                <h4>📈 Immediate Resistances (Above)</h4>
                <div id="res_list">
                    <div style="color: var(--text-muted); font-size: 13px;">Loading levels...</div>
                </div>
            </div>

            <div class="level-box sup">
                <h4>📉 Immediate Supports (Below)</h4>
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
                <p>Bot token from @BotFather (e.g. 123456789:ABCdefGHI...)</p>
            </div>
            <div>
                <input type="text" id="tg_bot_token" class="text-input" placeholder="Paste Bot Token here">
            </div>
        </div>

        <div class="control-row">
            <div class="control-info">
                <h4>Telegram Chat ID</h4>
                <p>Your Telegram User or Channel Chat ID (e.g. 987654321)</p>
            </div>
            <div>
                <input type="text" id="tg_chat_id" class="text-input" placeholder="Paste Chat ID here">
            </div>
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
                    <th>Level Name</th>
                    <th>Timeframe</th>
                    <th>Level Price</th>
                    <th>Spot Price</th>
                    <th>Gap</th>
                    <th>Trade Link</th>
                </tr>
            </thead>
            <tbody id="events_table_body">
                <tr><td colspan="7" style="color: var(--text-muted);">No events logged yet today.</td></tr>
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

            if (data.recent_events && data.recent_events.length > 0) {
                let evtHtml = '';
                data.recent_events.forEach(e => {
                    evtHtml += `
                        <tr>
                            <td>${e.timestamp}</td>
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
    return render_template_string(HTML_TEMPLATE)


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
        from telegram_notifier import send_telegram_message
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



@app.route("/api/run_check", methods=["POST"])
def run_check_api():
    import subprocess
    try:
        subprocess.Popen([sys.executable, "xauusd_event_finder.py"])
        return jsonify({"status": "success", "message": "Manual Event Check Triggered!"})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)})


if __name__ == "__main__":
    print("=" * 70)
    print(" STARTING EVENT FINDER WEB DASHBOARD SERVER")
    print(" Dashboard URL: http://localhost:5050")
    print(" CoinDCX Link: https://coindcx.com/futures/B-XAU_USDT")
    print("=" * 70)
    app.run(host="0.0.0.0", port=5050, debug=False)
