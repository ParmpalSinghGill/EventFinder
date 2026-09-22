"""Replay last 7 weekdays of CoinDCX gold and write when events should have fired."""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import os
import sys

import pandas as pd

from gold.coindcx_gold import DAILY_CSV, drop_weekend_bars, fetch_daily, fetch_minutes
from gold.xauusd_event_finder import (
    DATA_DIR,
    _levels_from_engine,
    _prepare_level_engine,
    _scan_bar_for_events,
    load_dynamic_config,
    update_session_extreme_arm,
)

IST = "Asia/Kolkata"
REPLAY_HOURS = 7 * 24 + 12
OUT_CSV = os.path.join(DATA_DIR, "gold_events_last_week.csv")


def load_daily() -> pd.DataFrame:
    df = fetch_daily()
    if df.empty and os.path.exists(DAILY_CSV):
        df = pd.read_csv(DAILY_CSV)
    df["Date"] = pd.to_datetime(df["Date"])
    if getattr(df["Date"].dt, "tz", None) is not None:
        df["Date"] = df["Date"].dt.tz_convert("UTC").dt.tz_localize(None)
    df = df.sort_values("Date").set_index("Date")
    df = drop_weekend_bars(df)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def load_minutes() -> pd.DataFrame:
    print(f"Downloading CoinDCX B-XAU_USDT 1-minute bars ({REPLAY_HOURS}h) ...")
    raw = fetch_minutes(hours=REPLAY_HOURS)
    if raw.empty:
        return raw
    raw = raw.copy()
    raw["Datetime"] = pd.to_datetime(raw["Datetime"], utc=True)
    raw = raw.sort_values("Datetime").set_index("Datetime")[
        ["Open", "High", "Low", "Close", "Volume"]
    ].dropna(subset=["Close"])
    return drop_weekend_bars(raw)


def engine_for_day(daily: pd.DataFrame, day: pd.Timestamp):
    """Labels from days strictly before `day`; PDH/PDL = previous session."""
    hist = daily.loc[daily.index < day]
    if hist.empty or len(hist) < 3:
        return None
    work = hist.reset_index()
    engine = _prepare_level_engine(work)
    if engine is None:
        return None
    prev = hist.iloc[-1]
    engine["pdh"] = float(prev["High"])
    engine["pdl"] = float(prev["Low"])
    return engine


def replay(daily: pd.DataFrame, minutes_utc: pd.DataFrame) -> list:
    if minutes_utc.empty:
        return []

    cutoff = minutes_utc.index.max() - pd.Timedelta(days=7)
    bars = minutes_utc.loc[minutes_utc.index >= cutoff].copy()
    print(f"Replaying {len(bars)} x 1-min bars  {bars.index.min()} -> {bars.index.max()} UTC")

    conf = load_dynamic_config()
    trigger_tol = float(conf.get("gold_trigger_tol", 0.0020))
    print(f"Trigger: NEAR within {trigger_tol * 100:.2f}%  |  TOUCH at the label  |  "
          f">{conf.get('watch_exit_dist', 0.004) * 100:.2f}% re-arms  |  "
          f"one NEAR per level until TOUCH or pullback")

    import gold.xauusd_event_finder as xf

    captured = []

    def _capture(evt, new_events, show_events, send_alerts):
        new_events.append(evt)
        captured.append(evt)

    xf._fire_event = _capture

    state = {}
    last_day = None
    engine = None
    today_high = float("-inf")
    today_low = float("inf")
    armed = {"high": None, "low": None}

    for i, (ts, row) in enumerate(bars.iterrows()):
        px = float(row["Close"])
        bar_high = float(row["High"])
        bar_low = float(row["Low"])
        day = pd.Timestamp(ts.tz_convert("UTC").normalize().tz_localize(None))

        if last_day != day:
            engine = engine_for_day(daily, day)
            today_high = float("-inf")
            today_low = float("inf")
            armed = {"high": None, "low": None}
            last_day = day
            if engine is not None:
                print(f"  day {day.date()}  PDH={engine['pdh']:.2f}  PDL={engine['pdl']:.2f}")

        if engine is None:
            continue

        levels = _levels_from_engine(engine, px, today_high, today_low, armed)
        ts_ist = ts.tz_convert(IST)
        current_time_str = ts_ist.strftime("%Y-%m-%d %H:%M:%S")
        _scan_bar_for_events(
            levels, state, px, current_time_str, trigger_tol,
            [], False, False, False,
            bar_high, bar_low, allow_rearm=True,
        )
        today_high = bar_high if today_high == float("-inf") else max(today_high, bar_high)
        today_low = bar_low if today_low == float("inf") else min(today_low, bar_low)
        xf.update_session_extreme_arm(armed, today_high, today_low, px)

        if (i + 1) % 2000 == 0:
            print(f"  ... {i + 1}/{len(bars)} bars, events so far={len(captured)}")

    return captured


def main():
    os.makedirs(DATA_DIR, exist_ok=True)
    daily = load_daily()
    minutes_utc = load_minutes()
    if daily.empty:
        print("[ERROR] No daily gold data.")
        sys.exit(1)
    if minutes_utc.empty:
        print("[ERROR] No 1-minute gold data.")
        sys.exit(1)

    print(f"Daily {daily.index.min().date()} -> {daily.index.max().date()}  ({len(daily)} bars)")
    print(f"Minute {minutes_utc.index.min()} -> {minutes_utc.index.max()}  ({len(minutes_utc)} bars) UTC")

    events = replay(daily, minutes_utc)
    rows = []
    for evt in events:
        rows.append({
            "datetime": evt["timestamp"],
            "event_type": evt.get("status", ""),
            "event_level": evt.get("level_name", ""),
            "timeframe": evt.get("timeframe", ""),
            "level_price": evt.get("level_price", ""),
            "spot_price": evt.get("spot_price", ""),
            "dist_pct": evt.get("dist_pct", ""),
        })

    out = pd.DataFrame(rows, columns=[
        "datetime", "event_type", "event_level",
        "timeframe", "level_price", "spot_price", "dist_pct",
    ])
    out.to_csv(OUT_CSV, index=False)

    print("\n" + "=" * 100)
    print(" EVENTS that should have fired (datetime is IST)")
    print("=" * 100)
    if out.empty:
        print("No NEAR/TOUCH events in the last 7 weekdays.")
    else:
        print(f"{'#':>3}  {'Date time (IST)':<20}  {'Type':<6}  {'Event level':<28}  {'Level':>10}  {'Spot':>10}")
        print("-" * 100)
        for i, row in out.iterrows():
            print(
                f"{i + 1:3d}  {row['datetime']:<20}  {row['event_type']:<6}  "
                f"{row['event_level']:<28}  ${float(row['level_price']):9,.2f}  "
                f"${float(row['spot_price']):9,.2f}"
            )
        print("=" * 100)
        print(out["event_type"].value_counts().to_string())
    print(f"\nSaved CSV -> {OUT_CSV}")
    print(f"TOTAL EVENTS: {len(out)}")


if __name__ == "__main__":
    main()
