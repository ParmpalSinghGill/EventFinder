"""
Spot XAU/USD Event Finder & Level Monitor (With Direct CoinDCX Trade Links)
=============================================================================
Direct CoinDCX Gold Futures Link: https://coindcx.com/futures/B-XAU_USDT
"""

import json
import os
import sys
from datetime import datetime
import pandas as pd
import yfinance as yf
import yaml

# Import exact stock label engine
sys.path.append(os.getcwd())
from find_labels import (find_labels, nearest_levels, to_2yearly, to_monthly,
                         to_weekly, to_yearly)

# Paths & Settings
CONFIG_YML = "config.yml"
CONFIG_JSON = os.path.join("data", "gold_xauusd", "event_config.json")
COINDCX_URL = "https://coindcx.com/futures/B-XAU_USDT"

TICKER_SYMBOL = "PAXG-USD"   # Spot Gold rate (matches CoinDCX & TradingView Spot XAUUSD)
DATA_DIR = os.path.join("data", "gold_xauusd")
DAILY_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1d.csv")
MINUTE_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1m_today.csv")
STATE_JSON = os.path.join(DATA_DIR, "event_state.json")
EVENTS_CSV = os.path.join(DATA_DIR, "gold_events_log.csv")

DEFAULT_CONFIG = {
    "run_gold_event_finder": True,
    "show_gold_events": True,
    "gold_trigger_tol": 0.0020,
    "run_stock_event_finder": True,
    "show_stock_events": True
}

RETRIGGER_DIST = 0.0100           # 1.00% distance required to reset/re-arm the trigger flag
PREV_DAY_HIERARCHY_TOL = 0.0040  # 0.40% threshold: suppress Prev Day level if higher TF level is within 0.40%

TIMEFRAMES = [
    ("2Y", "2-Year",  to_2yearly),
    ("1Y", "1-Year",  to_yearly),
    ("M",  "Monthly", to_monthly),
    ("W",  "Weekly",  to_weekly),
    ("D",  "Daily",   lambda df: df),
]


def load_dynamic_config() -> dict:
    conf = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_YML):
        try:
            with open(CONFIG_YML, "r") as f:
                raw_yml = yaml.safe_load(f)
                if raw_yml and "event_finder" in raw_yml:
                    conf.update(raw_yml["event_finder"])
        except Exception:
            pass

    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r") as f:
                json_conf = json.load(f)
                conf.update(json_conf)
        except Exception:
            pass

    return conf


def fetch_latest_data():
    """Fetch updated Daily and Intraday 1-minute Spot Gold data."""
    os.makedirs(DATA_DIR, exist_ok=True)
    
    df_daily = yf.download(TICKER_SYMBOL, period="max", interval="1d", progress=False)
    if isinstance(df_daily.columns, pd.MultiIndex):
        df_daily.columns = df_daily.columns.get_level_values(0)
    df_daily.reset_index(inplace=True)
    df_daily.to_csv(DAILY_CSV, index=False)

    df_1m = yf.download(TICKER_SYMBOL, period="1d", interval="1m", progress=False)
    if isinstance(df_1m.columns, pd.MultiIndex):
        df_1m.columns = df_1m.columns.get_level_values(0)
    df_1m.reset_index(inplace=True)
    df_1m.to_csv(MINUTE_CSV, index=False)
    
    return df_daily, df_1m


def compute_stock_screener_levels(df_daily: pd.DataFrame, df_1m: pd.DataFrame, current_price: float) -> list:
    """Compute active levels using stock find_labels engine + today's cancellation logic."""
    date_col = df_daily.columns[0]
    df_daily[date_col] = pd.to_datetime(df_daily[date_col])
    df_daily = df_daily.sort_values(date_col).set_index(date_col)

    today_candle = df_daily.iloc[-1]
    today_high = float(today_candle["High"])
    today_low = float(today_candle["Low"])

    if not df_1m.empty:
        if "High" in df_1m.columns and "Low" in df_1m.columns:
            today_high = max(today_high, float(df_1m["High"].max()))
            today_low = min(today_low, float(df_1m["Low"].min()))

    higher_tf_levels = []
    daily_levels = []

    for tf_key, tf_label, resampler in TIMEFRAMES:
        try:
            df_tf = resampler(df_daily)
        except Exception:
            continue
        if df_tf.empty or len(df_tf) < 3:
            continue

        labels = find_labels(df_tf, left=3, right=2, big_mult=2.0, break_tol=0.0)
        res_lvl, sup_lvl = nearest_levels(labels, df_tf, current_price)

        if res_lvl is not None:
            price = float(res_lvl["price"])
            if today_high < price:
                lvl_dict = {
                    "id": f"{tf_key}_R_{price:.2f}",
                    "timeframe": tf_label,
                    "name": f"{tf_label} Resistance",
                    "type": "resistance",
                    "price": price
                }
                if tf_key in ["2Y", "1Y", "M", "W"]:
                    higher_tf_levels.append(lvl_dict)
                else:
                    daily_levels.append(lvl_dict)

        if sup_lvl is not None:
            price = float(sup_lvl["price"])
            if today_low > price:
                lvl_dict = {
                    "id": f"{tf_key}_S_{price:.2f}",
                    "timeframe": tf_label,
                    "name": f"{tf_label} Support",
                    "type": "support",
                    "price": price
                }
                if tf_key in ["2Y", "1Y", "M", "W"]:
                    higher_tf_levels.append(lvl_dict)
                else:
                    daily_levels.append(lvl_dict)

    # Previous Day levels (PDH and PDL)
    prev_day_candle = df_daily.iloc[-2] if len(df_daily) >= 2 else df_daily.iloc[-1]
    pdh = float(prev_day_candle["High"])
    pdl = float(prev_day_candle["Low"])

    candidate_prev_day = []
    if today_high < pdh:
        candidate_prev_day.append({"id": f"PDH_{pdh:.2f}", "timeframe": "PrevDay", "name": "Prev Day High (PDH)", "type": "resistance", "price": pdh})

    if today_low > pdl:
        candidate_prev_day.append({"id": f"PDL_{pdl:.2f}", "timeframe": "PrevDay", "name": "Prev Day Low (PDL)", "type": "support", "price": pdl})

    valid_prev_day_levels = []
    for pd_lvl in candidate_prev_day:
        pd_price = pd_lvl["price"]
        has_nearby_higher_tf = any(
            abs(htf["price"] - pd_price) / pd_price <= PREV_DAY_HIERARCHY_TOL
            for htf in higher_tf_levels
        )
        if not has_nearby_higher_tf:
            valid_prev_day_levels.append(pd_lvl)

    all_levels = higher_tf_levels + daily_levels + valid_prev_day_levels
    return all_levels


def load_state() -> dict:
    if os.path.exists(STATE_JSON):
        try:
            with open(STATE_JSON, "r") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def save_state(state: dict):
    with open(STATE_JSON, "w") as f:
        json.dump(state, f, indent=2)


def log_event(event_dict: dict):
    file_exists = os.path.exists(EVENTS_CSV)
    df_evt = pd.DataFrame([event_dict])
    df_evt.to_csv(EVENTS_CSV, mode="a", header=not file_exists, index=False)


def run_event_finder():
    conf = load_dynamic_config()
    
    run_gold = bool(conf.get("run_gold_event_finder", True))
    show_events = bool(conf.get("show_gold_events", True))
    trigger_tol = float(conf.get("gold_trigger_tol", 0.0020))

    if not run_gold:
        print("\n[CONFIG NOTICE] Gold Event Finder is DISABLED. Skipping.")
        return

    print("\n" + "=" * 75)
    print(f" SPOT XAU/USD EVENT FINDER (ACTIVE MONITOR)")
    print(f" Mode: {'VERBOSE / SHOW ALERTS' if show_events else 'SILENT / BACKGROUND LOGGING ONLY'}")
    print(f" Proximity Tolerance: {trigger_tol * 100:.2f}% (${trigger_tol})")
    print(f" CoinDCX Trade Link: {COINDCX_URL}")
    print(f" Timestamp (Local): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)

    df_daily, df_1m = fetch_latest_data()
    if df_1m.empty:
        print("[ERROR] No 1-minute intraday data available.")
        return

    dt_col = df_1m.columns[0]
    latest_row = df_1m.iloc[-1]
    current_price = float(latest_row["Close"])
    current_time_str = str(latest_row[dt_col])

    print(f"\n Current Spot Gold Price: ${current_price:,.2f} USD")
    print(f" Latest Data Timestamp: {current_time_str}")

    levels = compute_stock_screener_levels(df_daily, df_1m, current_price)
    
    if show_events:
        print(f"\n Active Uncrossed Levels Tracked ({len(levels)} levels):")
        for l in sorted(levels, key=lambda x: x["price"], reverse=True):
            gap_pct = ((l["price"] - current_price) / current_price) * 100
            print(f"   * [{l['timeframe']}] {l['name']}: ${l['price']:,.2f} (Gap: {gap_pct:+.2f}%)")

    state = load_state()
    new_events = []

    for lvl in levels:
        lid = lvl["id"]
        lprice = lvl["price"]
        lname = lvl["name"]
        ltf = lvl["timeframe"]

        pct_dist = abs(current_price - lprice) / lprice

        lvl_state = state.get(lid, {"triggered": False, "last_price": current_price, "last_updated": current_time_str})
        was_triggered = lvl_state.get("triggered", False)

        if pct_dist <= trigger_tol:
            if not was_triggered:
                evt = {
                    "timestamp": current_time_str,
                    "level_id": lid,
                    "level_name": lname,
                    "timeframe": ltf,
                    "level_price": round(lprice, 2),
                    "spot_price": round(current_price, 2),
                    "dist_pct": round(pct_dist * 100, 3),
                    "status": "TRIGGERED",
                    "trade_link": COINDCX_URL
                }
                new_events.append(evt)
                log_event(evt)
                lvl_state["triggered"] = True
                lvl_state["trigger_time"] = current_time_str
                
                # Send Telegram Alert (Message Type 2) + Schedule 30-min Update (Message Type 3)
                try:
                    from telegram_notifier import send_event_trigger_alert
                    send_event_trigger_alert(evt)
                except Exception as te:
                    print(f"  [Telegram Event Alert Warning]: {te}")

                if show_events:
                    print(f"  *** [EVENT TRIGGERED] *** Price ${current_price:,.2f} is within {pct_dist*100:.2f}% of {lname} (${lprice:,.2f})!")
                    print(f"      -> Trade Gold on CoinDCX: {COINDCX_URL}")

            else:
                if show_events:
                    print(f"  [ACTIVE TRIGGER] {lname} (${lprice:,.2f}) -- Already triggered (Price gap: {pct_dist*100:.2f}%)")
        else:
            if was_triggered and pct_dist > RETRIGGER_DIST:
                lvl_state["triggered"] = False
                if show_events:
                    print(f"  [RE-ARMED] {lname} (${lprice:,.2f}) -- Price moved {pct_dist*100:.2f}% away (>1.0%). Trigger flag reset.")

        lvl_state["last_price"] = current_price
        lvl_state["last_updated"] = current_time_str
        state[lid] = lvl_state

    save_state(state)

    if show_events:
        print("\n" + "=" * 75)
        if new_events:
            print(f" TOTAL NEW EVENTS FOUND: {len(new_events)}")
            for e in new_events:
                print(f"   -> [{e['timestamp']}] {e['level_name']} @ ${e['level_price']} (Current: ${e['spot_price']}, Dist: {e['dist_pct']}%)")
                print(f"      Link: {COINDCX_URL}")
        else:
            print(" NO NEW NEARBY EVENTS AT THIS TIME.")
        print("=" * 75)


if __name__ == "__main__":
    run_event_finder()
