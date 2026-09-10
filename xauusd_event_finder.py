"""
Spot XAU/USD Event Finder & Level Monitor (With Direct CoinDCX Trade Links)
=============================================================================
Direct CoinDCX Gold Futures Link: https://coindcx.com/futures/B-XAU_USDT
"""

import json
import os
import sys
import uuid
from datetime import datetime
import pandas as pd
import yaml

# Import exact stock label engine
sys.path.append(os.getcwd())
from coindcx_gold import (COINDCX_PAIR, drop_weekend_bars, fetch_latest_data as fetch_coindcx_gold,
                          fetch_live_price, is_gold_weekend)
from find_labels import (find_labels, nearest_levels, to_2yearly, to_monthly,
                         to_weekly, to_yearly)

# Paths & Settings
CONFIG_YML = "config.yml"
CONFIG_JSON = os.path.join("data", "gold_xauusd", "event_config.json")
COINDCX_URL = "https://coindcx.com/futures/B-XAU_USDT"

TICKER_SYMBOL = COINDCX_PAIR  # CoinDCX gold futures (B-XAU_USDT / XAUUSDT)
DATA_DIR = os.path.join("data", "gold_xauusd")
DAILY_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1d.csv")
MINUTE_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1m_today.csv")
STATE_JSON = os.path.join(DATA_DIR, "event_state.json")
EVENTS_CSV = os.path.join(DATA_DIR, "gold_events_log.csv")
CUSTOM_LABELS_JSON = os.path.join(DATA_DIR, "custom_labels.json")

DEFAULT_CONFIG = {
    "run_gold_event_finder": True,
    "show_gold_events": True,
    "gold_trigger_tol": 0.0020,
    "run_stock_event_finder": True,
    "show_stock_events": True
}

WATCH_EXIT_DIST = 0.0030         # 0.30% away: leave 30s watch and re-arm the near trigger
RETRIGGER_DIST = WATCH_EXIT_DIST  # alias used by chart replay
MONITOR_FAST_SEC = 30
MONITOR_SLOW_SEC = 300
MONITOR_KEY = "_monitor"
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


def fetch_latest_data(refresh_daily: bool = True):
    """Fetch CoinDCX B-XAU_USDT daily history and last 24h of 1-minute bars."""
    return fetch_coindcx_gold(save=True, refresh_daily=refresh_daily)


def _last_daily_session_start(df_daily: pd.DataFrame) -> pd.Timestamp | None:
    """UTC open of the latest daily candle (CoinDCX 1D bars are UTC-dated)."""
    if df_daily is None or df_daily.empty:
        return None
    if isinstance(df_daily.index, pd.DatetimeIndex):
        ts = pd.Timestamp(df_daily.index[-1])
    else:
        date_col = df_daily.columns[0]
        ts = pd.to_datetime(df_daily.iloc[-1][date_col], errors="coerce")
        if pd.isna(ts):
            return None
    ts = pd.Timestamp(ts).tz_localize(None).normalize()
    return ts.tz_localize("UTC")


def session_minute_bars(df_daily: pd.DataFrame, df_1m: pd.DataFrame) -> pd.DataFrame:
    """1-minute bars that belong to the current daily candle only.

    The 1m CSV is a rolling 24h window. Using High/Low on that whole file treats
    yesterday's PDH/PDL prints as today's session range and cancels Prev Day
    levels before price can enter the 0.20% trigger band.
    """
    if df_1m is None or df_1m.empty:
        return pd.DataFrame() if df_1m is None else df_1m.iloc[0:0].copy()
    work = drop_weekend_bars(df_1m.copy())
    start = _last_daily_session_start(df_daily)
    if start is None or work.empty:
        return work
    dt_col = work.columns[0]
    ts = pd.to_datetime(work[dt_col], utc=True)
    return work.loc[ts >= start].copy()


def session_high_low(df_daily: pd.DataFrame, df_1m: pd.DataFrame):
    """Today's session high/low from the current daily candle + today's 1-minute bars."""
    if df_daily is None or df_daily.empty:
        return None, None

    work = df_daily.copy()
    date_col = work.columns[0]
    work = drop_weekend_bars(work, date_col)
    if work.empty:
        return None, None

    work[date_col] = pd.to_datetime(work[date_col])
    work = work.sort_values(date_col)
    today_candle = work.iloc[-1]
    today_high = float(today_candle["High"])
    today_low = float(today_candle["Low"])

    minute = session_minute_bars(work, df_1m)
    if minute is not None and not minute.empty:
        if "High" in minute.columns and "Low" in minute.columns:
            today_high = max(today_high, float(minute["High"].max()))
            today_low = min(today_low, float(minute["Low"].min()))
    return today_high, today_low


def load_custom_labels() -> list:
    if os.path.exists(CUSTOM_LABELS_JSON):
        try:
            with open(CUSTOM_LABELS_JSON, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception:
            pass
    return []


def save_custom_labels(labels: list):
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(CUSTOM_LABELS_JSON, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2)


def _custom_label_crossed(price: float, current_price: float,
                          today_high: float, today_low: float) -> bool:
    """True when the session has already traded through or touched the custom level."""
    if current_price < price:
        return today_high >= price
    if current_price > price:
        return today_low <= price
    return False


def add_custom_label(price: float, name: str = "",
                     current_price: float = None,
                     today_high: float = None,
                     today_low: float = None) -> dict:
    price = round(float(price), 2)
    if price <= 0:
        raise ValueError("Price must be greater than 0.")

    name = (name or "").strip()
    labels = load_custom_labels()
    for existing in labels:
        if abs(float(existing["price"]) - price) < 0.01:
            raise ValueError(f"A custom label already exists at ${float(existing['price']):.2f}.")

    if current_price is not None and today_high is not None and today_low is not None:
        if _custom_label_crossed(price, current_price, today_high, today_low):
            raise ValueError(
                f"Gold already traded through ${price:.2f} today "
                f"(session range ${today_low:.2f}–${today_high:.2f}). "
                "That label would be cancelled immediately."
            )

    label = {
        "id": f"C_{uuid.uuid4().hex[:10]}",
        "name": name if name else f"Custom ${price:.2f}",
        "price": price,
        "created": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    }
    labels.append(label)
    save_custom_labels(labels)
    return label


def delete_custom_label(label_id: str) -> bool:
    labels = load_custom_labels()
    kept = [l for l in labels if l.get("id") != label_id]
    if len(kept) == len(labels):
        return False
    save_custom_labels(kept)
    state = load_state()
    if label_id in state:
        del state[label_id]
        save_state(state)
    return True


def purge_crossed_custom_labels(current_price: float, today_high: float, today_low: float) -> list:
    """Drop custom labels that have been traded through. Returns remaining labels."""
    labels = load_custom_labels()
    remaining = []
    removed_ids = []
    for label in labels:
        price = float(label["price"])
        if _custom_label_crossed(price, current_price, today_high, today_low):
            removed_ids.append(label.get("id"))
        else:
            remaining.append(label)
    if removed_ids:
        save_custom_labels(remaining)
        state = load_state()
        dirty = False
        for rid in removed_ids:
            if rid in state:
                del state[rid]
                dirty = True
        if dirty:
            save_state(state)
    return remaining


def custom_labels_as_levels(labels: list, current_price: float) -> list:
    levels = []
    for label in labels:
        price = float(label["price"])
        side = "resistance" if price > current_price else "support"
        levels.append({
            "id": label["id"],
            "timeframe": "Custom",
            "name": label.get("name") or f"Custom ${price:.2f}",
            "type": side,
            "price": price,
            "custom": True
        })
    return levels


def get_all_active_levels(df_daily: pd.DataFrame, df_1m: pd.DataFrame, current_price: float) -> list:
    """System labels (uncrossed) plus remaining custom labels."""
    levels = compute_stock_screener_levels(df_daily, df_1m, current_price)
    today_high, today_low = session_high_low(df_daily, df_1m)
    if today_high is not None and today_low is not None:
        custom = purge_crossed_custom_labels(current_price, today_high, today_low)
    else:
        custom = load_custom_labels()
    levels.extend(custom_labels_as_levels(custom, current_price))
    return levels


def _prepare_level_engine(df_daily: pd.DataFrame) -> dict | None:
    """Precompute timeframe labels + PDH/PDL once so 1-minute replay stays cheap."""
    if df_daily is None or df_daily.empty:
        return None

    date_col = df_daily.columns[0]
    work = drop_weekend_bars(df_daily.copy(), date_col)
    if work.empty:
        return None

    work[date_col] = pd.to_datetime(work[date_col])
    work = work.sort_values(date_col).set_index(date_col)

    tf_sets = []
    for tf_key, tf_label, resampler in TIMEFRAMES:
        try:
            df_tf = resampler(work)
        except Exception:
            continue
        if df_tf.empty or len(df_tf) < 3:
            continue
        labels = find_labels(df_tf, left=3, right=2, big_mult=2.0, break_tol=0.0)
        tf_sets.append((tf_key, tf_label, df_tf, labels))

    prev_day_candle = work.iloc[-2] if len(work) >= 2 else work.iloc[-1]
    return {
        "tf_sets": tf_sets,
        "pdh": float(prev_day_candle["High"]),
        "pdl": float(prev_day_candle["Low"]),
        "today_candle": work.iloc[-1],
    }


def _levels_from_engine(engine: dict, current_price: float,
                        today_high: float, today_low: float) -> list:
    higher_tf_levels = []
    daily_levels = []

    for tf_key, tf_label, df_tf, labels in engine["tf_sets"]:
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

    pdh = engine["pdh"]
    pdl = engine["pdl"]
    candidate_prev_day = []
    if today_high < pdh:
        candidate_prev_day.append({
            "id": f"PDH_{pdh:.2f}", "timeframe": "PrevDay",
            "name": "Prev Day High (PDH)", "type": "resistance", "price": pdh
        })
    if today_low > pdl:
        candidate_prev_day.append({
            "id": f"PDL_{pdl:.2f}", "timeframe": "PrevDay",
            "name": "Prev Day Low (PDL)", "type": "support", "price": pdl
        })

    valid_prev_day_levels = []
    for pd_lvl in candidate_prev_day:
        pd_price = pd_lvl["price"]
        has_nearby_higher_tf = any(
            abs(htf["price"] - pd_price) / pd_price <= PREV_DAY_HIERARCHY_TOL
            for htf in higher_tf_levels
        )
        if not has_nearby_higher_tf:
            valid_prev_day_levels.append(pd_lvl)

    return higher_tf_levels + daily_levels + valid_prev_day_levels


def compute_stock_screener_levels(df_daily: pd.DataFrame, df_1m: pd.DataFrame,
                                  current_price: float,
                                  today_high: float = None,
                                  today_low: float = None) -> list:
    """Compute active levels using stock find_labels engine + today's cancellation logic."""
    engine = _prepare_level_engine(df_daily)
    if engine is None:
        return []

    if today_high is None or today_low is None:
        today_high = float(engine["today_candle"]["High"])
        today_low = float(engine["today_candle"]["Low"])
        minute = session_minute_bars(df_daily, df_1m)
        if minute is not None and not minute.empty:
            today_high = max(today_high, float(minute["High"].max()))
            today_low = min(today_low, float(minute["Low"].min()))

    return _levels_from_engine(engine, current_price, today_high, today_low)


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


def _proximity_frac(lprice: float, current_price: float,
                    bar_high: float = None, bar_low: float = None,
                    live_price: float = None) -> float:
    samples = [current_price]
    if bar_high is not None:
        samples.append(bar_high)
    if bar_low is not None:
        samples.append(bar_low)
    if live_price is not None:
        samples.append(live_price)
    return min(abs(float(p) - lprice) / lprice for p in samples)


def _level_touched(lvl: dict, bar_high: float, bar_low: float,
                   live_price: float = None) -> bool:
    price = float(lvl["price"])
    typ = (lvl.get("type") or "").lower()
    if typ == "resistance":
        if bar_high is not None and bar_high >= price:
            return True
        if live_price is not None and live_price >= price:
            return True
        return False
    if typ == "support":
        if bar_low is not None and bar_low <= price:
            return True
        if live_price is not None and live_price <= price:
            return True
        return False
    if bar_high is not None and bar_low is not None and bar_low <= price <= bar_high:
        return True
    return False


def _send_desktop_toast(evt: dict):
    """Windows desktop toast for NEAR and TOUCH. Always attempted when alerting."""
    try:
        from scheduler_run import notify
        status = str(evt.get("status") or "NEAR").upper()
        lname = evt.get("level_name", "Key Level")
        if status == "TOUCH":
            title = f"PRICE TOUCHED THE LABEL {lname}"
        else:
            title = f"GOLD NEAR LEVEL: {lname}"
        notify(
            title,
            f"{lname} ({evt.get('timeframe', '')}) @ ${float(evt['level_price']):,.2f} | "
            f"Spot: ${float(evt['spot_price']):,.2f} ({float(evt['dist_pct']):.2f}% gap)"
        )
    except Exception as ne:
        print(f"  [System Toast Alert Warning]: {ne}")


def _fire_event(evt: dict, new_events: list, show_events: bool, send_alerts: bool):
    new_events.append(evt)
    log_event(evt)
    if send_alerts:
        # Telegram + Discord + desktop for both NEAR and TOUCH.
        try:
            from telegram_notifier import send_event_trigger_alert
            send_event_trigger_alert(evt)
        except Exception as te:
            print(f"  [Telegram/Discord Event Alert Warning]: {te}")
        _send_desktop_toast(evt)
    if show_events:
        if evt.get("status") == "TOUCH":
            print(f"  *** [TOUCH] *** {evt['timestamp']}  Price touched {evt['level_name']} "
                  f"(${evt['level_price']:,.2f}) | Spot ${evt['spot_price']:,.2f}")
            print("      Sent to Telegram, Discord, and desktop")
        else:
            print(f"  *** [NEAR] *** {evt['timestamp']}  Price ${evt['spot_price']:,.2f} is within "
                  f"{evt['dist_pct']:.2f}% of {evt['level_name']} (${evt['level_price']:,.2f}) — watching 30s")
            print("      Sent to Telegram, Discord, and desktop")
        print(f"      -> Trade Gold on CoinDCX: {COINDCX_URL}")


def _scan_bar_for_events(levels: list, state: dict, current_price: float,
                         current_time_str: str, trigger_tol: float,
                         new_events: list, show_events: bool,
                         verbose: bool, send_alerts: bool,
                         bar_high: float, bar_low: float,
                         live_price: float = None):
    """Two-stage trigger: NEAR (enter 0.20% band) then TOUCH (price hits the label)."""
    for lvl in levels:
        lid = lvl["id"]
        lprice = float(lvl["price"])
        lname = lvl["name"]
        ltf = lvl["timeframe"]
        close_dist = abs(current_price - lprice) / lprice
        near_dist = _proximity_frac(lprice, current_price, bar_high, bar_low, live_price)
        is_near = near_dist <= trigger_tol
        touched = _level_touched(lvl, bar_high, bar_low, live_price)

        lvl_state = state.get(lid, {
            "triggered": False,
            "near_triggered": False,
            "touch_triggered": False,
            "watching": False,
            "last_price": current_price,
            "last_updated": current_time_str
        })
        near_triggered = bool(lvl_state.get("near_triggered", lvl_state.get("triggered", False)))
        touch_triggered = bool(lvl_state.get("touch_triggered", False))

        if touch_triggered:
            lvl_state["watching"] = False
        elif touched:
            if not near_triggered:
                evt = {
                    "timestamp": current_time_str,
                    "level_id": lid,
                    "level_name": lname,
                    "timeframe": ltf,
                    "level_price": round(lprice, 2),
                    "spot_price": round(current_price, 2),
                    "dist_pct": round(near_dist * 100, 3),
                    "status": "NEAR",
                    "trade_link": COINDCX_URL
                }
                _fire_event(evt, new_events, show_events, send_alerts)
                near_triggered = True
                lvl_state["near_time"] = current_time_str
            evt = {
                "timestamp": current_time_str,
                "level_id": lid,
                "level_name": lname,
                "timeframe": ltf,
                "level_price": round(lprice, 2),
                "spot_price": round(current_price, 2),
                "dist_pct": round(near_dist * 100, 3),
                "status": "TOUCH",
                "trade_link": COINDCX_URL
            }
            _fire_event(evt, new_events, show_events, send_alerts)
            touch_triggered = True
            lvl_state["touch_time"] = current_time_str
            lvl_state["watching"] = False
        elif is_near:
            if not near_triggered:
                evt = {
                    "timestamp": current_time_str,
                    "level_id": lid,
                    "level_name": lname,
                    "timeframe": ltf,
                    "level_price": round(lprice, 2),
                    "spot_price": round(current_price, 2),
                    "dist_pct": round(near_dist * 100, 3),
                    "status": "NEAR",
                    "trade_link": COINDCX_URL
                }
                _fire_event(evt, new_events, show_events, send_alerts)
                near_triggered = True
                lvl_state["near_time"] = current_time_str
            elif verbose and show_events:
                print(f"  [WATCH 30s] {lname} (${lprice:,.2f}) -- Near, waiting for touch "
                      f"(Price gap: {close_dist*100:.2f}%)")
            lvl_state["watching"] = True
        else:
            if near_triggered and close_dist > WATCH_EXIT_DIST:
                near_triggered = False
                lvl_state["watching"] = False
                if verbose and show_events:
                    print(f"  [RE-ARMED] {lname} (${lprice:,.2f}) -- Price moved {close_dist*100:.2f}% away "
                          f"(>{WATCH_EXIT_DIST*100:.2f}%). Back to 5-minute checks.")
            elif near_triggered:
                lvl_state["watching"] = True
                if verbose and show_events:
                    print(f"  [WATCH 30s] {lname} (${lprice:,.2f}) -- Still inside 0.30% "
                          f"(Price gap: {close_dist*100:.2f}%)")
            else:
                lvl_state["watching"] = False

        lvl_state["near_triggered"] = near_triggered
        lvl_state["touch_triggered"] = touch_triggered
        lvl_state["triggered"] = near_triggered
        lvl_state["last_price"] = current_price
        lvl_state["last_updated"] = current_time_str
        state[lid] = lvl_state


def _write_monitor_meta(state: dict, last_levels: list, current_time_str: str) -> dict:
    """Keep 30s polling only while a near-level is still uncrossed and not 0.30% away."""
    active_ids = {lvl["id"] for lvl in last_levels}
    watching = []
    for lid, st in list(state.items()):
        if lid.startswith("_") or not isinstance(st, dict):
            continue
        if st.get("watching") and not st.get("touch_triggered"):
            if lid in active_ids:
                watching.append(lid)
            else:
                st["watching"] = False
    meta = {
        "interval_sec": MONITOR_FAST_SEC if watching else MONITOR_SLOW_SEC,
        "watching": watching,
        "updated": current_time_str
    }
    state[MONITOR_KEY] = meta
    return meta


def read_monitor_interval() -> int:
    """Seconds the background daemon should sleep until the next gold check."""
    state = load_state()
    try:
        sec = int((state.get(MONITOR_KEY) or {}).get("interval_sec") or MONITOR_SLOW_SEC)
    except (TypeError, ValueError):
        sec = MONITOR_SLOW_SEC
    if sec <= MONITOR_FAST_SEC:
        return MONITOR_FAST_SEC
    return MONITOR_SLOW_SEC


def run_event_finder():
    conf = load_dynamic_config()
    
    run_gold = bool(conf.get("run_gold_event_finder", True))
    show_events = bool(conf.get("show_gold_events", True))
    trigger_tol = float(conf.get("gold_trigger_tol", 0.0020))

    if not run_gold:
        print("\n[CONFIG NOTICE] Gold Event Finder is DISABLED. Skipping.")
        return

    if is_gold_weekend():
        print("\n[WEEKEND] Gold market is closed Saturday-Sunday (IST).")
        print(" Skipping event checks. Weekend candles are not used for liquidity labels.")
        return

    print("\n" + "=" * 75)
    print(f" COINDCX XAUUSDT EVENT FINDER (ACTIVE MONITOR)")
    print(f" Feed: {TICKER_SYMBOL}  (public candles, no API key)")
    print(f" Mode: {'VERBOSE / SHOW ALERTS' if show_events else 'SILENT / BACKGROUND LOGGING ONLY'}")
    print(f" Near trigger: {trigger_tol * 100:.2f}%   Touch: label high/low   Watch exit: {WATCH_EXIT_DIST * 100:.2f}%")
    print(f" CoinDCX Trade Link: {COINDCX_URL}")
    print(f" Timestamp (Local): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)

    prev_interval = read_monitor_interval()
    df_daily, df_1m = fetch_latest_data(refresh_daily=(prev_interval > MONITOR_FAST_SEC))
    if df_1m.empty:
        print("[ERROR] No 1-minute intraday data available.")
        return

    engine = _prepare_level_engine(df_daily)
    if engine is None:
        print("[ERROR] No daily data available.")
        return

    session_1m = session_minute_bars(df_daily, df_1m)
    if session_1m.empty:
        session_1m = drop_weekend_bars(df_1m.copy())
    if session_1m.empty:
        print("[ERROR] No session 1-minute bars available.")
        return

    dt_col = session_1m.columns[0]
    latest_row = session_1m.iloc[-1]
    current_price = float(latest_row["Close"])
    current_time_str = str(latest_row[dt_col])
    latest_ts = pd.to_datetime(latest_row[dt_col], utc=True)
    alert_lookback = pd.Timedelta(minutes=10)

    print(f"\n Current CoinDCX XAUUSDT: ${current_price:,.2f}")
    print(f" Latest Data Timestamp: {current_time_str}")
    print(f" Session 1-minute bars scanned: {len(session_1m)}")

    state = load_state()
    new_events = []
    custom = load_custom_labels()
    today_high = float("-inf")
    today_low = float("inf")
    last_levels = []
    n_bars = len(session_1m)

    for i, row in enumerate(session_1m.itertuples(index=False)):
        current_price = float(row.Close)
        current_time_str = str(row[0])
        bar_high = float(row.High)
        bar_low = float(row.Low)
        is_last = i == n_bars - 1
        bar_ts = pd.to_datetime(current_time_str, utc=True)
        send_alerts = bool(bar_ts >= latest_ts - alert_lookback)

        last_levels = _levels_from_engine(engine, current_price, today_high, today_low)
        live_custom = [
            lab for lab in custom
            if not _custom_label_crossed(float(lab["price"]), current_price, today_high, today_low)
        ]
        last_levels = last_levels + custom_labels_as_levels(live_custom, current_price)
        _scan_bar_for_events(
            last_levels, state, current_price, current_time_str, trigger_tol,
            new_events, show_events, verbose=is_last, send_alerts=send_alerts,
            bar_high=bar_high, bar_low=bar_low
        )
        today_high = bar_high if today_high == float("-inf") else max(today_high, bar_high)
        today_low = bar_low if today_low == float("inf") else min(today_low, bar_low)

    live_price = None
    try:
        live_price = float(fetch_live_price()["last"])
        current_price = live_price
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        last_levels = _levels_from_engine(engine, current_price, today_high, today_low)
        live_custom = [
            lab for lab in custom
            if not _custom_label_crossed(float(lab["price"]), current_price, today_high, today_low)
        ]
        last_levels = last_levels + custom_labels_as_levels(live_custom, current_price)
        _scan_bar_for_events(
            last_levels, state, current_price, current_time_str, trigger_tol,
            new_events, show_events, verbose=True, send_alerts=True,
            bar_high=max(today_high, live_price) if today_high != float("-inf") else live_price,
            bar_low=min(today_low, live_price) if today_low != float("inf") else live_price,
            live_price=live_price
        )
        if today_high != float("-inf"):
            today_high = max(today_high, live_price)
            today_low = min(today_low, live_price)
        print(f" Live CoinDCX last: ${live_price:,.2f}")
    except Exception as le:
        print(f"  [Live price warning]: {le}")

    if today_high != float("-inf") and today_low != float("inf"):
        purge_crossed_custom_labels(current_price, today_high, today_low)

    monitor = _write_monitor_meta(state, last_levels, current_time_str)
    if show_events:
        print(f"\n Active Uncrossed Levels Tracked ({len(last_levels)} levels):")
        for l in sorted(last_levels, key=lambda x: x["price"], reverse=True):
            gap_pct = ((l["price"] - current_price) / current_price) * 100
            print(f"   * [{l['timeframe']}] {l['name']}: ${l['price']:,.2f} (Gap: {gap_pct:+.2f}%)")
        watching = monitor.get("watching") or []
        if watching:
            print(f"\n 30-second watch ON for: {', '.join(watching)}")
        else:
            print("\n Next check: 5 minutes")

    save_state(state)

    if show_events:
        print("\n" + "=" * 75)
        if new_events:
            print(f" TOTAL NEW EVENTS FOUND: {len(new_events)}")
            for e in new_events:
                print(f"   -> [{e['status']}] [{e['timestamp']}] {e['level_name']} @ ${e['level_price']} "
                      f"(Current: ${e['spot_price']}, Dist: {e['dist_pct']}%)")
                print(f"      Link: {COINDCX_URL}")
        else:
            print(" NO NEW NEARBY EVENTS AT THIS TIME.")
        print("=" * 75)


if __name__ == "__main__":
    run_event_finder()
