"""
TradingView spot gold client (XAUUSD).

Unauthenticated chart websocket — same candles as the TradingView website.
Default symbol is Vantage XAUUSD (VANTAGE:XAUUSD), which matches the
TradingView XAUUSD source list. OANDA:XAUUSD is the public default on
https://www.tradingview.com/symbols/XAUUSD/ and prints within ~$0.20.

This module is independent of CoinDCX. It does not write
data/gold_xauusd/ and is not used by the Gold Event Finder.
"""

from __future__ import annotations

import json
import os
import random
import string
import time

import pandas as pd
import websocket

TV_WS = "wss://data.tradingview.com/socket.io/websocket"
TV_ORIGIN = "https://www.tradingview.com"
DEFAULT_EXCHANGE = "VANTAGE"
DEFAULT_SYMBOL = "XAUUSD"
GOLD_TZ = "Asia/Kolkata"

DATA_DIR = os.path.join("gold", "tv_data")
DAILY_CSV = os.path.join(DATA_DIR, "vantage_xauusd_1d.csv")
MINUTE_CSV = os.path.join(DATA_DIR, "vantage_xauusd_1m_today.csv")


class TradingViewError(RuntimeError):
    pass


def _sid(n: int = 12) -> str:
    return "".join(random.choice(string.ascii_lowercase) for _ in range(n))


def _packet(func: str, params: list) -> str:
    payload = json.dumps({"m": func, "p": params}, separators=(",", ":"))
    return f"~m~{len(payload)}~m~{payload}"


def _split_packets(raw: str) -> list[dict]:
    out: list[dict] = []
    i = 0
    while True:
        start = raw.find("~m~", i)
        if start < 0:
            break
        start += 3
        mid = raw.find("~m~", start)
        if mid < 0:
            break
        try:
            n = int(raw[start:mid])
        except ValueError:
            break
        body = raw[mid + 3 : mid + 3 + n]
        i = mid + 3 + n
        if body.startswith("~h~"):
            out.append({"m": "heartbeat", "p": [body[3:]]})
            continue
        try:
            out.append(json.loads(body))
        except json.JSONDecodeError:
            continue
    return out


def _ticker(exchange: str, symbol: str) -> str:
    return f"{exchange.strip().upper()}:{symbol.strip().upper()}"


def fetch_history(
    exchange: str = DEFAULT_EXCHANGE,
    symbol: str = DEFAULT_SYMBOL,
    interval: str = "1D",
    n_bars: int = 3000,
    timeout_sec: float = 25.0,
) -> pd.DataFrame:
    """OHLCV from TradingView. interval: '1' (1m), '5', '60', '1D'."""
    ticker = _ticker(exchange, symbol)
    chart = "cs_" + _sid()
    quote = "qs_" + _sid()
    series = "sds_1"
    bars: list[list] = []
    error = None
    complete = False

    ws = websocket.WebSocket(timeout=20)
    try:
        ws.connect(
            TV_WS,
            origin=TV_ORIGIN,
            header=["User-Agent: Mozilla/5.0"],
        )

        def send(func: str, params: list) -> None:
            ws.send(_packet(func, params))

        send("set_auth_token", ["unauthorized_user_token"])
        send("chart_create_session", [chart, ""])
        send("quote_create_session", [quote])
        send("quote_add_symbols", [quote, ticker])
        send(
            "resolve_symbol",
            [chart, "sds_sym_1", f'={{"symbol":"{ticker}","adjustment":"splits"}}'],
        )
        send("create_series", [chart, series, "s1", "sds_sym_1", interval, int(n_bars), ""])

        t0 = time.time()
        while time.time() - t0 < timeout_sec:
            raw = ws.recv()
            if not raw:
                continue
            for pkt in _split_packets(raw):
                m = pkt.get("m")
                p = pkt.get("p") or []
                if m == "heartbeat":
                    ws.send(f"~m~{len('~h~' + p[0])}~m~~h~{p[0]}")
                    continue
                if m in ("symbol_error", "critical_error", "series_error"):
                    error = pkt
                    complete = True
                    break
                if m in ("timescale_update", "du") and len(p) > 1:
                    series_data = (p[1].get(series) or {}).get("s") or []
                    for row in series_data:
                        v = row.get("v") or []
                        if len(v) >= 5:
                            bars.append(v)
                if m == "series_completed":
                    complete = True
                    break
            if complete:
                break
            if bars and time.time() - t0 > 4.0:
                # First batch is the full history; extra wait is only for late errors.
                break
    except Exception as exc:
        raise TradingViewError(f"{ticker} websocket failed: {exc}") from exc
    finally:
        try:
            ws.close()
        except Exception:
            pass

    if error and not bars:
        raise TradingViewError(f"{ticker} history failed: {error}")
    if not bars:
        raise TradingViewError(f"{ticker} returned no candles ({interval})")

    cols = ["t", "Open", "High", "Low", "Close"]
    extra = ["Volume"] if max(len(r) for r in bars) > 5 else []
    frame = pd.DataFrame(bars, columns=cols + extra)
    if "Volume" not in frame.columns:
        frame["Volume"] = 0.0
    ts = pd.to_datetime(frame["t"], unit="s", utc=True)
    frame["Datetime"] = ts
    out = frame[["Datetime", "Open", "High", "Low", "Close", "Volume"]].dropna(
        subset=["Open", "High", "Low", "Close"]
    )
    return out.sort_values("Datetime").drop_duplicates(subset=["Datetime"], keep="last")


def fetch_daily(
    exchange: str = DEFAULT_EXCHANGE,
    symbol: str = DEFAULT_SYMBOL,
    n_bars: int = 4000,
) -> pd.DataFrame:
    df = fetch_history(exchange, symbol, interval="1D", n_bars=n_bars)
    if df.empty:
        return pd.DataFrame(columns=["Date", "Open", "High", "Low", "Close", "Volume"])
    out = df.copy()
    # IST date of the candle open matches a TradingView chart in GMT+5:30.
    out["Date"] = out["Datetime"].dt.tz_convert(GOLD_TZ).dt.tz_localize(None).dt.normalize()
    return out[["Date", "Open", "High", "Low", "Close", "Volume"]]


def fetch_minutes(
    hours: float = 24.0,
    exchange: str = DEFAULT_EXCHANGE,
    symbol: str = DEFAULT_SYMBOL,
) -> pd.DataFrame:
    n_bars = min(5000, max(60, int(hours * 60) + 30))
    df = fetch_history(exchange, symbol, interval="1", n_bars=n_bars, timeout_sec=30.0)
    if df.empty:
        return df
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
    return df.loc[df["Datetime"] >= cutoff].copy()


def csv_path(exchange: str, kind: str) -> str:
    tag = exchange.strip().lower()
    if kind == "1d":
        return os.path.join(DATA_DIR, f"{tag}_xauusd_1d.csv")
    return os.path.join(DATA_DIR, f"{tag}_xauusd_1m_today.csv")


def fetch_latest_data(
    save: bool = True,
    exchange: str = DEFAULT_EXCHANGE,
    symbol: str = DEFAULT_SYMBOL,
    minute_hours: float = 24.0,
):
    """Daily history + recent 1-minute bars. Writes under data/gold_tv_xauusd/ only."""
    os.makedirs(DATA_DIR, exist_ok=True)
    daily = fetch_daily(exchange, symbol)
    minutes = fetch_minutes(hours=minute_hours, exchange=exchange, symbol=symbol)
    if save:
        daily.to_csv(csv_path(exchange, "1d"), index=False)
        minutes.to_csv(csv_path(exchange, "1m"), index=False)
    return daily, minutes
