"""
CoinDCX gold futures data client (B-XAU_USDT).

Public market-data endpoints only — no API key required.
Pair: https://coindcx.com/futures/B-XAU_USDT
Docs: GET https://public.coindcx.com/market_data/candlesticks
"""

import json
import os
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pandas as pd

COINDCX_PAIR = "B-XAU_USDT"
COINDCX_CANDLES_URL = "https://public.coindcx.com/market_data/candlesticks"
COINDCX_PRICES_URL = "https://public.coindcx.com/market_data/v3/current_prices/futures/rt"
USER_AGENT = "EventFinder/1.0 (CoinDCX public market data)"

# Contract listed ~2026-01-09; requesting earlier returns empty.
LISTING_EPOCH = int(datetime(2026, 1, 9, tzinfo=timezone.utc).timestamp())

DATA_DIR = os.path.join("gold", "data")
DAILY_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1d.csv")
MINUTE_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1m_today.csv")

# Spot/COMEX gold is closed Saturday-Sunday. CoinDCX still prints weekend
# candles; those are dropped for events and for liquidity/label construction.
GOLD_TZ = "Asia/Kolkata"


class CoinDCXError(RuntimeError):
    pass


def _http_get_json(url: str, timeout: int = 30) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def fetch_candles(resolution: str, from_epoch: int, to_epoch: int) -> list:
    """resolution: '1' (1m), '5', '60', '1D'."""
    params = {
        "pair": COINDCX_PAIR,
        "from": int(from_epoch),
        "to": int(to_epoch),
        "resolution": resolution,
        "pcode": "f",
    }
    url = COINDCX_CANDLES_URL + "?" + urllib.parse.urlencode(params)
    payload = _http_get_json(url)
    if payload.get("s") not in (None, "ok"):
        raise CoinDCXError(f"CoinDCX candles status={payload.get('s')!r}")
    return payload.get("data") or []


def is_gold_weekend(ts=None) -> bool:
    """True if `ts` (default: now) is Saturday or Sunday in IST."""
    if ts is None:
        ts = datetime.now()
    stamp = pd.Timestamp(ts)
    if stamp.tzinfo is None:
        stamp = stamp.tz_localize(GOLD_TZ)
    else:
        stamp = stamp.tz_convert(GOLD_TZ)
    return int(stamp.dayofweek) >= 5


def drop_weekend_bars(df: pd.DataFrame, time_col: str | None = None) -> pd.DataFrame:
    """Remove Saturday/Sunday candles so labels use weekday liquidity only."""
    if df is None or df.empty:
        return df
    work = df.copy()
    if time_col is None:
        if "Datetime" in work.columns:
            time_col = "Datetime"
        elif "Date" in work.columns:
            time_col = "Date"

    if time_col and time_col in work.columns:
        ts = pd.to_datetime(work[time_col], utc=(time_col == "Datetime"), errors="coerce")
        if getattr(ts.dt, "tz", None) is not None:
            weekday = ts.dt.tz_convert(GOLD_TZ).dt.dayofweek
        else:
            weekday = ts.dt.dayofweek
        return work.loc[weekday < 5].copy()

    idx = pd.to_datetime(work.index)
    if getattr(idx, "tz", None) is not None:
        weekday = idx.tz_convert(GOLD_TZ).dayofweek
    else:
        weekday = idx.dayofweek
    return work.loc[weekday < 5].copy()


def _rows_to_frame(rows: list, time_col: str) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=[time_col, "Open", "High", "Low", "Close", "Volume"])
    df = pd.DataFrame(rows)
    df["Open"] = pd.to_numeric(df["open"], errors="coerce")
    df["High"] = pd.to_numeric(df["high"], errors="coerce")
    df["Low"] = pd.to_numeric(df["low"], errors="coerce")
    df["Close"] = pd.to_numeric(df["close"], errors="coerce")
    df["Volume"] = pd.to_numeric(df["volume"], errors="coerce").fillna(0.0)
    ts = pd.to_datetime(df["time"], unit="ms", utc=True)
    if time_col == "Date":
        df[time_col] = ts.dt.tz_convert("UTC").dt.tz_localize(None).dt.normalize()
    else:
        df[time_col] = ts
    out = df[[time_col, "Open", "High", "Low", "Close", "Volume"]].dropna(
        subset=["Open", "High", "Low", "Close"]
    )
    return out.sort_values(time_col).drop_duplicates(subset=[time_col], keep="last")


def fetch_daily() -> pd.DataFrame:
    now = int(time.time())
    rows = fetch_candles("1D", LISTING_EPOCH, now)
    return _rows_to_frame(rows, "Date")


def fetch_minutes(hours: float = 24.0) -> pd.DataFrame:
    """Fetch 1-minute candles. Windows longer than 24h are pulled in 24h chunks."""
    now = int(time.time())
    frm = now - int(hours * 3600)
    chunk_sec = 24 * 3600
    frames = []
    t = frm
    while t < now:
        t2 = min(t + chunk_sec, now)
        rows = fetch_candles("1", t, t2)
        if rows:
            frames.append(_rows_to_frame(rows, "Datetime"))
        t = t2
        if t < now:
            time.sleep(0.12)
    if not frames:
        return _rows_to_frame([], "Datetime")
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values("Datetime").drop_duplicates(subset=["Datetime"], keep="last")


def fetch_live_price() -> dict:
    payload = _http_get_json(COINDCX_PRICES_URL)
    xau = (payload.get("prices") or {}).get(COINDCX_PAIR) or {}
    last = xau.get("ls")
    if last is None:
        raise CoinDCXError(f"{COINDCX_PAIR} missing from CoinDCX live prices")
    return {
        "pair": COINDCX_PAIR,
        "last": float(last),
        "mark": float(xau["mp"]) if xau.get("mp") is not None else float(last),
        "high": float(xau["h"]) if xau.get("h") is not None else None,
        "low": float(xau["l"]) if xau.get("l") is not None else None,
    }


def _load_csv(path: str) -> pd.DataFrame:
    if not os.path.exists(path):
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def fetch_latest_data(save: bool = True, refresh_daily: bool = True):
    """Daily history + last 24h of 1-minute bars. Falls back to cached CSVs on error.

    During 30-second watch mode, pass refresh_daily=False to reuse the daily CSV
    so CoinDCX is not hit for the full daily history every tick.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    errors = []

    df_daily = pd.DataFrame()
    if not refresh_daily:
        df_daily = _load_csv(DAILY_CSV)
    if df_daily.empty:
        try:
            df_daily = fetch_daily()
            if df_daily.empty:
                raise CoinDCXError("no daily candles")
            if save:
                df_daily.to_csv(DAILY_CSV, index=False)
        except Exception as exc:
            errors.append(f"daily: {exc}")
            df_daily = _load_csv(DAILY_CSV)

    try:
        df_1m = fetch_minutes(hours=24.0)
        if df_1m.empty:
            raise CoinDCXError("no 1-minute candles")
        if save:
            df_1m.to_csv(MINUTE_CSV, index=False)
    except Exception as exc:
        errors.append(f"1m: {exc}")
        df_1m = _load_csv(MINUTE_CSV)

    if errors:
        print("[CoinDCX] " + " | ".join(errors))
        if df_daily.empty or df_1m.empty:
            print("[CoinDCX] using cached CSV where available")

    # Keep weekend prints on disk, but never use them for levels/events.
    df_daily = drop_weekend_bars(df_daily, "Date")
    df_1m = drop_weekend_bars(df_1m, "Datetime")
    return df_daily, df_1m
