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
from pathlib import Path
import pandas as pd
import yaml

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
os.chdir(_ROOT)

from gold.coindcx_gold import (COINDCX_PAIR, drop_weekend_bars, fetch_latest_data as fetch_coindcx_gold,
                               fetch_live_price, is_gold_weekend)
from utils.find_labels import (find_labels, nearest_levels, to_2yearly, to_monthly,
                               to_weekly, to_yearly)

# Paths & Settings
CONFIG_YML = os.path.join("gold", "config.yml")
CONFIG_JSON = os.path.join("gold", "data", "event_config.json")
COINDCX_URL = "https://coindcx.com/futures/B-XAU_USDT"

TICKER_SYMBOL = COINDCX_PAIR  # CoinDCX gold futures (B-XAU_USDT / XAUUSDT)
DATA_DIR = os.path.join("gold", "data")
DAILY_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1d.csv")
MINUTE_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1m_today.csv")
STATE_JSON = os.path.join(DATA_DIR, "event_state.json")
EVENTS_CSV = os.path.join(DATA_DIR, "gold_events_log.csv")
CUSTOM_LABELS_JSON = os.path.join(DATA_DIR, "custom_labels.json")

DEFAULT_CONFIG = {
    "run_gold_event_finder": True,
    "show_gold_events": True,
    "gold_trigger_tol": 0.0020,          # 0.20% — NEAR when inside this of a level
    "watch_exit_dist": 0.0040,           # 0.40% — leave 30s watch and re-arm NEAR immediately
    "approach_dist": 0.0050,             # 0.50% — silent 1-minute checks
    "session_extreme_arm": 0.01,         # 1% — Today's High/Low arm after this move
    "near_retrigger_sec": 0,             # unused: NEAR does not repeat while still watching
    "monitor_fast_sec": 30,
    "monitor_approach_sec": 60,
    "monitor_slow_sec": 300,
    "prev_day_hierarchy_tol": 0.0040,    # 0.40% — hide PDH/PDL if a higher-TF level is this close
    "pivot_left_gap": 0.01,              # 1% — extra pivot if next bar confirms and left bar differs by this
}

_FLOAT_KEYS = {
    "gold_trigger_tol", "watch_exit_dist", "approach_dist",
    "session_extreme_arm", "prev_day_hierarchy_tol", "pivot_left_gap",
}
_INT_KEYS = {
    "near_retrigger_sec", "monitor_fast_sec",
    "monitor_approach_sec", "monitor_slow_sec",
}

# Module aliases — always match DEFAULT_CONFIG / last event_settings() load.
WATCH_EXIT_DIST = DEFAULT_CONFIG["watch_exit_dist"]
APPROACH_DIST = DEFAULT_CONFIG["approach_dist"]
SESSION_EXTREME_ARM_DIST = DEFAULT_CONFIG["session_extreme_arm"]
RETRIGGER_DIST = WATCH_EXIT_DIST
NEAR_RETRIGGER_SEC = DEFAULT_CONFIG["near_retrigger_sec"]
MONITOR_FAST_SEC = DEFAULT_CONFIG["monitor_fast_sec"]
MONITOR_APPROACH_SEC = DEFAULT_CONFIG["monitor_approach_sec"]
MONITOR_SLOW_SEC = DEFAULT_CONFIG["monitor_slow_sec"]
MONITOR_KEY = "_monitor"
PREV_DAY_HIERARCHY_TOL = DEFAULT_CONFIG["prev_day_hierarchy_tol"]

_SETTINGS_CACHE = None

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


def _fmt_pct(frac: float) -> str:
    return f"{float(frac) * 100:.2f}"


def event_settings(refresh: bool = False) -> dict:
    """Resolved event-finder settings from DEFAULT_CONFIG → config.yml → event_config.json."""
    global _SETTINGS_CACHE
    global WATCH_EXIT_DIST, APPROACH_DIST, SESSION_EXTREME_ARM_DIST, RETRIGGER_DIST
    global NEAR_RETRIGGER_SEC, MONITOR_FAST_SEC, MONITOR_APPROACH_SEC, MONITOR_SLOW_SEC
    global PREV_DAY_HIERARCHY_TOL

    if _SETTINGS_CACHE is not None and not refresh:
        return _SETTINGS_CACHE

    raw = load_dynamic_config()
    s = {}
    for key, default in DEFAULT_CONFIG.items():
        val = raw.get(key, default)
        try:
            if key in _FLOAT_KEYS:
                s[key] = float(val)
            elif key in _INT_KEYS:
                s[key] = int(val)
            else:
                s[key] = val
        except (TypeError, ValueError):
            s[key] = default

    WATCH_EXIT_DIST = s["watch_exit_dist"]
    APPROACH_DIST = s["approach_dist"]
    SESSION_EXTREME_ARM_DIST = s["session_extreme_arm"]
    RETRIGGER_DIST = WATCH_EXIT_DIST
    NEAR_RETRIGGER_SEC = s["near_retrigger_sec"]
    MONITOR_FAST_SEC = s["monitor_fast_sec"]
    MONITOR_APPROACH_SEC = s["monitor_approach_sec"]
    MONITOR_SLOW_SEC = s["monitor_slow_sec"]
    PREV_DAY_HIERARCHY_TOL = s["prev_day_hierarchy_tol"]
    _SETTINGS_CACHE = s
    return s


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


DISPLAY_TF_RANK = {
    "Today": 0, "PrevDay": 1, "Custom": 2,
    "2-Year": 3, "1-Year": 4, "Monthly": 5, "Weekly": 6, "Daily": 7
}


def _level_priority(lvl: dict) -> int:
    return DISPLAY_TF_RANK.get(str(lvl.get("timeframe") or ""), 50)


def _merge_unique_level(levels: list, lvl: dict):
    """Keep one row per price; prefer Today's High/Low and Prev Day over generic pivots."""
    px = round(float(lvl["price"]), 2)
    lid = lvl.get("id")
    for i, existing in enumerate(levels):
        same_id = lid and existing.get("id") == lid
        same_px = round(float(existing["price"]), 2) == px
        if same_id or same_px:
            if _level_priority(lvl) < _level_priority(existing):
                levels[i] = lvl
            return
    levels.append(lvl)


def session_display_levels(today_high: float, today_low: float, current_price: float) -> list:
    """Always list today's high/low on the dashboard, even before the event-arming move."""
    levels = []
    if _is_valid_px(today_high):
        high = float(today_high)
        levels.append({
            "id": f"TH_{high:.2f}",
            "timeframe": "Today",
            "name": "Today's High",
            "type": "resistance",
            "price": high
        })
    if _is_valid_px(today_low):
        low = float(today_low)
        levels.append({
            "id": f"TL_{low:.2f}",
            "timeframe": "Today",
            "name": "Today's Low",
            "type": "support",
            "price": low
        })
    return levels


def extra_display_pivots(engine: dict, current_price: float,
                         today_high: float, today_low: float) -> list:
    """Extra uncrossed pivots so the dashboard can fill up to 5 supports and 5 resistances."""
    extra = []
    if not engine or not _is_valid_px(current_price):
        return extra
    px = float(current_price)
    for tf_key, tf_label, _df_tf, labels in engine["tf_sets"]:
        for lab in labels or []:
            if lab.get("canceled"):
                continue
            price = float(lab["price"])
            kind = lab.get("type")
            if kind == "resistance":
                if _is_valid_px(today_high) and not (today_high < price):
                    continue
                if price <= px:
                    continue
                extra.append({
                    "id": f"{tf_key}_R_{price:.2f}",
                    "timeframe": tf_label,
                    "name": f"{tf_label} Resistance",
                    "type": "resistance",
                    "price": price
                })
            elif kind == "support":
                if _is_valid_px(today_low) and not (today_low > price):
                    continue
                if price >= px:
                    continue
                extra.append({
                    "id": f"{tf_key}_S_{price:.2f}",
                    "timeframe": tf_label,
                    "name": f"{tf_label} Support",
                    "type": "support",
                    "price": price
                })
    return extra


def get_all_active_levels(df_daily: pd.DataFrame, df_1m: pd.DataFrame, current_price: float) -> list:
    """Uncrossed labels plus remaining custom labels.

    Today's high/low are included only after price has moved the configured
    arm distance away (same rule as the event finder).
    """
    engine = _prepare_level_engine(df_daily)
    today_high, today_low = session_high_low(df_daily, df_1m)
    if engine is not None and (today_high is None or today_low is None):
        today_high = float(engine["today_candle"]["High"])
        today_low = float(engine["today_candle"]["Low"])
    if _is_valid_px(current_price):
        if _is_valid_px(today_high):
            today_high = max(float(today_high), float(current_price))
        if _is_valid_px(today_low):
            today_low = min(float(today_low), float(current_price))

    levels = []
    if engine is not None and today_high is not None and today_low is not None:
        armed = session_arm_from_minute_bars(df_daily, df_1m, current_price)
        levels = _levels_from_engine(engine, current_price, today_high, today_low, armed)
        custom = purge_crossed_custom_labels(current_price, today_high, today_low)
    else:
        custom = load_custom_labels()
    for lvl in custom_labels_as_levels(custom, current_price):
        _merge_unique_level(levels, lvl)
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
        labels = find_labels(
            df_tf, left=3, right=2, big_mult=2.0, break_tol=0.0,
            left_gap=event_settings()["pivot_left_gap"]
        )
        tf_sets.append((tf_key, tf_label, df_tf, labels))

    prev_day_candle = work.iloc[-2] if len(work) >= 2 else work.iloc[-1]
    return {
        "tf_sets": tf_sets,
        "pdh": float(prev_day_candle["High"]),
        "pdl": float(prev_day_candle["Low"]),
        "today_candle": work.iloc[-1],
    }


def _levels_from_engine(engine: dict, current_price: float,
                        today_high: float, today_low: float,
                        armed: dict | None = None) -> list:
    s = event_settings()
    pd_tol = s["prev_day_hierarchy_tol"]
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
            abs(htf["price"] - pd_price) / pd_price <= pd_tol
            for htf in higher_tf_levels
        )
        if not has_nearby_higher_tf:
            valid_prev_day_levels.append(pd_lvl)

    return (higher_tf_levels + daily_levels + valid_prev_day_levels
            + session_extreme_levels(today_high, today_low, current_price, armed))


def _is_valid_px(px) -> bool:
    try:
        value = float(px)
    except (TypeError, ValueError):
        return False
    return value > 0 and value != float("inf")


def _same_px(a, b) -> bool:
    if a is None or b is None:
        return False
    try:
        return round(float(a), 2) == round(float(b), 2)
    except (TypeError, ValueError):
        return False


def _new_session_arm() -> dict:
    return {"high": None, "low": None}


def update_session_extreme_arm(armed: dict, today_high, today_low, current_price) -> dict:
    """Arm Today's High/Low only after *current* price has been the arm distance away.

    Making a new low while the session high is far above does not count. A new
    high/low starts unarmed. Once this exact high/low is armed, it stays armed
    so a later 0.20% retest can fire.
    """
    if not isinstance(armed, dict):
        armed = _new_session_arm()
    arm = event_settings()["session_extreme_arm"]
    px = float(current_price) if _is_valid_px(current_price) else None
    high = float(today_high) if _is_valid_px(today_high) else None
    low = float(today_low) if _is_valid_px(today_low) else None

    if high is None or not _same_px(armed.get("high"), high):
        armed["high"] = None
    if low is None or not _same_px(armed.get("low"), low):
        armed["low"] = None

    if px is not None and high is not None:
        drop_now = (high - px) / high if px < high else 0.0
        if drop_now >= arm:
            armed["high"] = high
    if px is not None and low is not None:
        rally_now = (px - low) / low if px > low else 0.0
        if rally_now >= arm:
            armed["low"] = low
    return armed


def session_extreme_levels(today_high: float, today_low: float, current_price: float,
                           armed: dict | None = None) -> list:
    """List Today's High/Low only after they have been armed by a 1% (config) move away."""
    levels = []
    armed = armed if isinstance(armed, dict) else _new_session_arm()
    high = float(today_high) if _is_valid_px(today_high) else None
    low = float(today_low) if _is_valid_px(today_low) else None

    if high is not None and _same_px(armed.get("high"), high):
        levels.append({
            "id": f"TH_{high:.2f}",
            "timeframe": "Today",
            "name": "Today's High",
            "type": "resistance",
            "price": high
        })
    if low is not None and _same_px(armed.get("low"), low):
        levels.append({
            "id": f"TL_{low:.2f}",
            "timeframe": "Today",
            "name": "Today's Low",
            "type": "support",
            "price": low
        })
    return levels


def session_arm_from_minute_bars(df_daily: pd.DataFrame, df_1m: pd.DataFrame,
                                 current_price: float = None) -> dict:
    """Replay today's 1-minute bars to see which session extremes have been armed."""
    armed = _new_session_arm()
    minute = session_minute_bars(df_daily, df_1m)
    today_high = float("-inf")
    today_low = float("inf")
    if minute is not None and not minute.empty:
        for row in minute.itertuples(index=False):
            bar_high = float(row.High)
            bar_low = float(row.Low)
            px = float(row.Close)
            today_high = bar_high if today_high == float("-inf") else max(today_high, bar_high)
            today_low = bar_low if today_low == float("inf") else min(today_low, bar_low)
            update_session_extreme_arm(armed, today_high, today_low, px)
    if _is_valid_px(current_price) and today_high != float("-inf"):
        update_session_extreme_arm(armed, today_high, today_low, current_price)
    return armed


def compute_gold_levels(df_daily: pd.DataFrame, df_1m: pd.DataFrame,
                        current_price: float,
                        today_high: float = None,
                        today_low: float = None) -> list:
    """Active gold levels from the shared pivot rules, cancelled once price trades through them."""
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

    return _levels_from_engine(
        engine, current_price, today_high, today_low,
        session_arm_from_minute_bars(df_daily, df_1m, current_price)
    )


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
    """Distance of *this* price/candle from the level — never the full session range."""
    samples = [float(current_price)]
    if bar_high is not None:
        samples.append(float(bar_high))
    if bar_low is not None:
        samples.append(float(bar_low))
    if live_price is not None:
        samples.append(float(live_price))
    return min(abs(p - lprice) / lprice for p in samples)


def _close_dist_frac(lprice: float, current_price: float) -> float:
    return abs(float(current_price) - lprice) / lprice


def _seconds_between(prev_str, now_str):
    """Elapsed seconds from one event timestamp string to another, or None if unparseable."""
    a = pd.to_datetime(prev_str, errors="coerce")
    b = pd.to_datetime(now_str, errors="coerce")
    if pd.isna(a) or pd.isna(b):
        return None
    if a.tzinfo is not None or b.tzinfo is not None:
        a = a.tz_localize("UTC") if a.tzinfo is None else a.tz_convert("UTC")
        b = b.tz_localize("UTC") if b.tzinfo is None else b.tz_convert("UTC")
    return float((b - a).total_seconds())


def _already_emitted(new_events: list, status: str, price: float) -> bool:
    """One Telegram/Discord/desktop message per price+status in a single run."""
    px = round(float(price), 2)
    return any(
        str(e.get("status") or "").upper() == status
        and round(float(e.get("level_price") or 0), 2) == px
        for e in new_events
    )


def _near_alert_due(near_triggered: bool, lvl_state: dict, current_time_str: str) -> bool:
    """NEAR only on first entry. Next alert is TOUCH, or NEAR after leaving watch_exit."""
    return not near_triggered


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
            from gold.telegram_notifier import send_event_trigger_alert
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
                         live_price: float = None,
                         allow_rearm: bool = True):
    """NEAR at trigger_tol (30s), silent approach, TOUCH on the label.

    If price leaves more than watch_exit_dist and later comes back inside
    trigger_tol, NEAR fires again. Sitting inside the band does not re-alert.
    """
    s = event_settings()
    watch_exit = s["watch_exit_dist"]
    approach = s["approach_dist"]
    for lvl in levels:
        lid = lvl["id"]
        lprice = float(lvl["price"])
        lname = lvl["name"]
        ltf = lvl["timeframe"]
        close_dist = _close_dist_frac(lprice, current_price)
        near_dist = _proximity_frac(lprice, current_price, bar_high, bar_low, live_price)
        is_near = near_dist <= trigger_tol
        is_approach = near_dist <= approach
        touched = _level_touched(lvl, bar_high, bar_low, live_price)

        lvl_state = state.get(lid, {
            "triggered": False,
            "near_triggered": False,
            "touch_triggered": False,
            "watching": False,
            "approaching": False,
            "last_price": current_price,
            "last_updated": current_time_str
        })
        near_triggered = bool(lvl_state.get("near_triggered", lvl_state.get("triggered", False)))
        touch_triggered = bool(lvl_state.get("touch_triggered", False))
        approaching = False
        watching = False

        def _emit_near():
            nonlocal near_triggered
            evt = {
                "timestamp": current_time_str,
                "level_id": lid,
                "level_name": lname,
                "timeframe": ltf,
                "level_price": round(lprice, 2),
                "spot_price": round(current_price, 2),
                "dist_pct": round(close_dist * 100, 3),
                "status": "NEAR",
                "trade_link": COINDCX_URL
            }
            skip = _already_emitted(new_events, "NEAR", lprice)
            if not skip:
                _fire_event(evt, new_events, show_events, send_alerts)
            near_triggered = True
            lvl_state["near_time"] = current_time_str

        if touch_triggered:
            pass
        elif touched:
            if _near_alert_due(near_triggered, lvl_state, current_time_str):
                _emit_near()
            evt = {
                "timestamp": current_time_str,
                "level_id": lid,
                "level_name": lname,
                "timeframe": ltf,
                "level_price": round(lprice, 2),
                "spot_price": round(current_price, 2),
                "dist_pct": round(close_dist * 100, 3),
                "status": "TOUCH",
                "trade_link": COINDCX_URL
            }
            if not _already_emitted(new_events, "TOUCH", lprice):
                _fire_event(evt, new_events, show_events, send_alerts)
            touch_triggered = True
            lvl_state["touch_time"] = current_time_str
        elif is_near:
            if _near_alert_due(near_triggered, lvl_state, current_time_str):
                _emit_near()
            elif verbose and show_events:
                print(f"  [WATCH 30s] {lname} (${lprice:,.2f}) -- Near, waiting for touch "
                      f"(Price gap: {close_dist*100:.2f}%)")
            watching = True
        elif near_triggered and close_dist <= watch_exit:
            watching = True
            if verbose and show_events:
                print(f"  [WATCH 30s] {lname} (${lprice:,.2f}) -- Still inside {_fmt_pct(watch_exit)}% "
                      f"(Price gap: {close_dist*100:.2f}%)")
        else:
            if allow_rearm and near_triggered and close_dist > watch_exit:
                near_triggered = False
                if verbose and show_events:
                    print(f"  [RE-ARMED] {lname} (${lprice:,.2f}) -- Price moved {close_dist*100:.2f}% away "
                          f"(>{_fmt_pct(watch_exit)}%). Next {_fmt_pct(trigger_tol)}% visit will NEAR again.")
            if is_approach or close_dist <= approach:
                approaching = True
                if verbose and show_events:
                    print(f"  [WATCH 1m] {lname} (${lprice:,.2f}) -- Inside {_fmt_pct(approach)}% band, no alert yet "
                          f"(Price gap: {close_dist*100:.2f}%)")

        lvl_state["near_triggered"] = near_triggered
        lvl_state["touch_triggered"] = touch_triggered
        lvl_state["triggered"] = near_triggered
        lvl_state["watching"] = watching
        lvl_state["approaching"] = approaching and not watching and not touch_triggered
        lvl_state["last_price"] = current_price
        lvl_state["last_updated"] = current_time_str
        state[lid] = lvl_state


def _reconcile_watch_from_spot(levels: list, state: dict, current_price: float,
                               trigger_tol: float):
    """Watch flags follow the live/last price, not an earlier wick in the session."""
    s = event_settings()
    watch_exit = s["watch_exit_dist"]
    approach = s["approach_dist"]
    for lvl in levels:
        lid = lvl["id"]
        st = state.get(lid)
        if not isinstance(st, dict) or st.get("touch_triggered"):
            continue
        dist = _close_dist_frac(float(lvl["price"]), current_price)
        if dist <= trigger_tol:
            st["watching"] = True
            st["approaching"] = False
        elif dist <= watch_exit and st.get("near_triggered"):
            st["watching"] = True
            st["approaching"] = False
        elif dist <= approach:
            st["watching"] = False
            st["approaching"] = True
            if dist > watch_exit:
                st["near_triggered"] = False
                st["triggered"] = False
        else:
            st["watching"] = False
            st["approaching"] = False
            st["near_triggered"] = False
            st["triggered"] = False
        state[lid] = st


def _write_monitor_meta(state: dict, last_levels: list, current_price: float,
                        current_time_str: str, trigger_tol: float,
                        last_scanned: str = None) -> dict:
    """30s if NEAR, 1 min if inside approach band, otherwise slow interval."""
    s = event_settings()
    watch_exit = s["watch_exit_dist"]
    approach = s["approach_dist"]
    active_ids = {lvl["id"] for lvl in last_levels}
    watching = []
    approaching = []
    for lid, st in list(state.items()):
        if lid.startswith("_") or not isinstance(st, dict):
            continue
        if lid not in active_ids or st.get("touch_triggered"):
            st["watching"] = False
            st["approaching"] = False

    for lvl in last_levels:
        lid = lvl["id"]
        st = state.get(lid) if isinstance(state.get(lid), dict) else {}
        if st.get("touch_triggered"):
            continue
        dist = _close_dist_frac(float(lvl["price"]), current_price)
        if dist <= trigger_tol or (dist <= watch_exit and st.get("near_triggered")):
            watching.append(lid)
        elif dist <= approach:
            approaching.append(lid)
            if st:
                st["approaching"] = True

    if watching:
        interval = s["monitor_fast_sec"]
    elif approaching:
        interval = s["monitor_approach_sec"]
    else:
        interval = s["monitor_slow_sec"]
    meta = {
        "interval_sec": interval,
        "watching": watching,
        "approaching": approaching,
        "updated": current_time_str
    }
    if last_scanned:
        meta["last_scanned"] = last_scanned
    else:
        prev = state.get(MONITOR_KEY) if isinstance(state.get(MONITOR_KEY), dict) else {}
        if prev.get("last_scanned"):
            meta["last_scanned"] = prev["last_scanned"]
    state[MONITOR_KEY] = meta
    return meta


def read_monitor_interval() -> int:
    """Seconds the background daemon should sleep until the next gold check."""
    s = event_settings()
    slow = s["monitor_slow_sec"]
    fast = s["monitor_fast_sec"]
    approach = s["monitor_approach_sec"]
    state = load_state()
    try:
        sec = int((state.get(MONITOR_KEY) or {}).get("interval_sec") or slow)
    except (TypeError, ValueError):
        sec = slow
    if sec <= fast:
        return fast
    if sec <= approach:
        return approach
    return slow


def run_event_finder():
    s = event_settings(refresh=True)
    run_gold = bool(s.get("run_gold_event_finder", True))
    show_events = bool(s.get("show_gold_events", True))
    trigger_tol = float(s["gold_trigger_tol"])
    watch_exit = s["watch_exit_dist"]
    approach = s["approach_dist"]
    arm = s["session_extreme_arm"]
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
    print(f" Approach {_fmt_pct(approach)}% → 1 min (silent)  |  "
          f"Near {_fmt_pct(trigger_tol)}% → 30s + one alert  |  "
          f">{_fmt_pct(watch_exit)}% re-arms NEAR  |  "
          f"Touch: one alert, then done")
    print(f" Today's High/Low become levels only after a {_fmt_pct(arm)}% move away, "
          "then the same watch/touch rules apply")
    print(f" CoinDCX Trade Link: {COINDCX_URL}")
    print(f" Timestamp (Local): {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)

    prev_interval = read_monitor_interval()
    df_daily, df_1m = fetch_latest_data(refresh_daily=(prev_interval >= s["monitor_slow_sec"]))
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
    print(f" Session 1-minute bars: {len(session_1m)}")

    state = load_state()
    new_events = []
    custom = load_custom_labels()
    today_high = float("-inf")
    today_low = float("inf")
    last_levels = []
    n_bars = len(session_1m)
    scanned_bars = 0
    armed = _new_session_arm()

    session_start_ts = pd.to_datetime(session_1m.iloc[0][dt_col], utc=True)
    prev_monitor = state.get(MONITOR_KEY) if isinstance(state.get(MONITOR_KEY), dict) else {}
    last_scanned_ts = pd.to_datetime(prev_monitor.get("last_scanned"), utc=True, errors="coerce")
    if pd.isna(last_scanned_ts):
        last_scanned_ts = None
    elif last_scanned_ts < session_start_ts:
        last_scanned_ts = None

    for i, row in enumerate(session_1m.itertuples(index=False)):
        current_price = float(row.Close)
        current_time_str = str(row[0])
        bar_high = float(row.High)
        bar_low = float(row.Low)
        is_last = i == n_bars - 1
        bar_ts = pd.to_datetime(current_time_str, utc=True)
        is_new = last_scanned_ts is None or bar_ts > last_scanned_ts
        if is_new:
            scanned_bars += 1
            send_alerts = bool(bar_ts >= latest_ts - alert_lookback)
            last_levels = _levels_from_engine(
                engine, current_price, today_high, today_low, armed
            )
            live_custom = [
                lab for lab in custom
                if not _custom_label_crossed(float(lab["price"]), current_price, today_high, today_low)
            ]
            last_levels = last_levels + custom_labels_as_levels(live_custom, current_price)
            _scan_bar_for_events(
                last_levels, state, current_price, current_time_str, trigger_tol,
                new_events, show_events, verbose=is_last, send_alerts=send_alerts,
                bar_high=bar_high, bar_low=bar_low, allow_rearm=is_last
            )
        today_high = bar_high if today_high == float("-inf") else max(today_high, bar_high)
        today_low = bar_low if today_low == float("inf") else min(today_low, bar_low)
        update_session_extreme_arm(armed, today_high, today_low, current_price)

    print(f" New 1-minute bars event-scanned: {scanned_bars}")

    forming_high = float(latest_row["High"])
    forming_low = float(latest_row["Low"])
    live_price = None
    try:
        live_price = float(fetch_live_price()["last"])
        current_price = live_price
        current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        forming_high = max(forming_high, live_price)
        forming_low = min(forming_low, live_price)
        last_levels = _levels_from_engine(
            engine, current_price, today_high, today_low, armed
        )
        live_custom = [
            lab for lab in custom
            if not _custom_label_crossed(float(lab["price"]), current_price, today_high, today_low)
        ]
        last_levels = last_levels + custom_labels_as_levels(live_custom, current_price)
        _scan_bar_for_events(
            last_levels, state, current_price, current_time_str, trigger_tol,
            new_events, show_events, verbose=True, send_alerts=True,
            bar_high=forming_high, bar_low=forming_low,
            live_price=live_price, allow_rearm=True
        )
        if today_high != float("-inf"):
            today_high = max(today_high, live_price)
            today_low = min(today_low, live_price)
            update_session_extreme_arm(armed, today_high, today_low, live_price)
        print(f" Live CoinDCX last: ${live_price:,.2f}")
    except Exception as le:
        print(f"  [Live price warning]: {le}")
        last_levels = _levels_from_engine(
            engine, current_price, today_high, today_low, armed
        )
        live_custom = [
            lab for lab in custom
            if not _custom_label_crossed(float(lab["price"]), current_price, today_high, today_low)
        ]
        last_levels = last_levels + custom_labels_as_levels(live_custom, current_price)

    if last_levels:
        _reconcile_watch_from_spot(last_levels, state, current_price, trigger_tol)

    if today_high != float("-inf") and today_low != float("inf"):
        purge_crossed_custom_labels(current_price, today_high, today_low)

    monitor = _write_monitor_meta(
        state, last_levels, current_price, current_time_str, trigger_tol,
        last_scanned=str(latest_row[dt_col])
    )
    if show_events:
        print(f"\n Active Uncrossed Levels Tracked ({len(last_levels)} levels):")
        for l in sorted(last_levels, key=lambda x: x["price"], reverse=True):
            gap_pct = ((l["price"] - current_price) / current_price) * 100
            print(f"   * [{l['timeframe']}] {l['name']}: ${l['price']:,.2f} (Gap: {gap_pct:+.2f}%)")
        watching = monitor.get("watching") or []
        approaching = monitor.get("approaching") or []
        interval = int(monitor.get("interval_sec") or MONITOR_SLOW_SEC)
        if watching:
            print(f"\n 30-second watch ON for: {', '.join(watching)}")
        elif approaching:
            print(f"\n 1-minute approach watch ON for: {', '.join(approaching)}")
        else:
            print("\n Next check: 5 minutes")
        print(f" Sleep interval: {interval}s")

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
