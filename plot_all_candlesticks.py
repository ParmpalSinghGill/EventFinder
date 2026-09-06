"""
Generate Candlestick Charts for Spot Gold (XAU/USD) Data with IST Timezone
==========================================================================
1. 1-Month Daily Candlestick Chart
2. Today's 1-Minute Intraday Candlestick Chart (Converted to IST - UTC+05:30)
"""

import os
import pandas as pd
import mplfinance as mpf

# File paths
DATA_DIR = os.path.join("data", "gold_xauusd")
DAILY_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1d.csv")
MINUTE_CSV = os.path.join(DATA_DIR, "gold_spot_xauusd_1m_today.csv")

ARTIFACT_DIR = r"C:\Users\parmp\.gemini\antigravity\brain\63f31c9d-d1c3-4775-bda8-e2481dead9bf"
DAILY_PNG_ARTIFACT = os.path.join(ARTIFACT_DIR, "gold_spot_daily_candlestick.png")
MINUTE_PNG_ARTIFACT = os.path.join(ARTIFACT_DIR, "gold_spot_1m_candlestick.png")

DAILY_PNG_LOCAL = os.path.join(DATA_DIR, "gold_spot_daily_candlestick.png")
MINUTE_PNG_LOCAL = os.path.join(DATA_DIR, "gold_spot_1m_candlestick.png")


def plot_daily_candlestick():
    if not os.path.exists(DAILY_CSV):
        print(f"[ERROR] {DAILY_CSV} not found.")
        return

    df = pd.read_csv(DAILY_CSV)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    # Filter last 1 month (35 calendar days)
    latest_date = df["Date"].max()
    start_date = latest_date - pd.Timedelta(days=35)
    df_1mth = df[df["Date"] >= start_date].copy()
    df_1mth.set_index("Date", inplace=True)

    custom_style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mpf.make_marketcolors(
            up="#2ecc71", down="#e74c3c", edge="inherit", wick="inherit", volume="#34495e"
        ),
        gridstyle=":",
        facecolor="#121721",
        figcolor="#0b0e14"
    )

    start_str = df_1mth.index[0].strftime("%b %d, %Y")
    end_str = df_1mth.index[-1].strftime("%b %d, %Y")
    latest_close = df_1mth["Close"].iloc[-1]

    title = (
        f"CoinDCX XAUUSDT 1-Month Daily Candlestick Chart ({start_str} – {end_str})\n"
        f"Pair: B-XAU_USDT | Latest Close: ${latest_close:,.2f}"
    )

    mpf.plot(
        df_1mth,
        type="candle",
        mav=(5, 20),
        volume=True,
        title=title,
        style=custom_style,
        figsize=(14, 8),
        savefig=dict(fname=DAILY_PNG_ARTIFACT, dpi=200, bbox_inches="tight")
    )
    
    mpf.plot(
        df_1mth,
        type="candle",
        mav=(5, 20),
        volume=True,
        title=title,
        style=custom_style,
        figsize=(14, 8),
        savefig=dict(fname=DAILY_PNG_LOCAL, dpi=200, bbox_inches="tight")
    )

    print(f"[SUCCESS] Saved Daily Spot Candlestick graph to: {DAILY_PNG_ARTIFACT}")


def plot_intraday_1m_candlestick(tz_target="Asia/Kolkata"):
    """Plot 1-minute intraday candlestick chart converted to specified timezone (default IST)."""
    if not os.path.exists(MINUTE_CSV):
        print(f"[ERROR] {MINUTE_CSV} not found.")
        return

    df = pd.read_csv(MINUTE_CSV)
    dt_col = "Datetime" if "Datetime" in df.columns else df.columns[0]
    
    # Parse datetimes and convert to target timezone (IST - Asia/Kolkata)
    df[dt_col] = pd.to_datetime(df[dt_col], utc=True)
    df[dt_col] = df[dt_col].dt.tz_convert(tz_target)
    
    df = df.sort_values(dt_col).reset_index(drop=True)
    df.set_index(dt_col, inplace=True)

    custom_style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mpf.make_marketcolors(
            up="#2ecc71", down="#e74c3c", edge="inherit", wick="inherit", volume="#34495e"
        ),
        gridstyle=":",
        facecolor="#121721",
        figcolor="#0b0e14"
    )

    tz_label = "IST (UTC+05:30)" if tz_target == "Asia/Kolkata" else tz_target
    start_time = df.index[0].strftime("%H:%M")
    end_time = df.index[-1].strftime("%H:%M")
    session_date = df.index[-1].strftime("%b %d, %Y")
    latest_close = df["Close"].iloc[-1]

    title = (
        f"CoinDCX XAUUSDT Today's 1-Minute Chart ({session_date})\n"
        f"Timezone: {tz_label} | Session: {start_time} to {end_time} IST | Latest Price: ${latest_close:,.2f}"
    )

    mpf.plot(
        df,
        type="candle",
        mav=(9, 21),
        volume=True,
        title=title,
        style=custom_style,
        figsize=(14, 8),
        savefig=dict(fname=MINUTE_PNG_ARTIFACT, dpi=200, bbox_inches="tight")
    )

    mpf.plot(
        df,
        type="candle",
        mav=(9, 21),
        volume=True,
        title=title,
        style=custom_style,
        figsize=(14, 8),
        savefig=dict(fname=MINUTE_PNG_LOCAL, dpi=200, bbox_inches="tight")
    )

    print(f"[SUCCESS] Saved 1-Minute Intraday Candlestick graph ({tz_label}) to: {MINUTE_PNG_ARTIFACT}")


if __name__ == "__main__":
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    os.makedirs(DATA_DIR, exist_ok=True)
    plot_daily_candlestick()
    plot_intraday_1m_candlestick(tz_target="Asia/Kolkata")
