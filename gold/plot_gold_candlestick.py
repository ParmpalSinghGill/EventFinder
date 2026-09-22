"""
Generate 1-Month Daily Candlestick Chart for Spot Gold (XAU/USD)
===============================================================
Matches CoinDCX gold futures B-XAU_USDT (XAUUSDT).
"""

import os
import pandas as pd
import mplfinance as mpf

# File paths
DATA_PATH = os.path.join("gold", "data", "gold_spot_xauusd_1d.csv")
ARTIFACT_DIR = r"C:\Users\parmp\.gemini\antigravity\brain\63f31c9d-d1c3-4775-bda8-e2481dead9bf"
OUTPUT_PNG_ARTIFACT = os.path.join(ARTIFACT_DIR, "gold_spot_xauusd_1mth_candlestick.png")
OUTPUT_PNG_LOCAL = os.path.join("gold", "data", "gold_spot_xauusd_1mth_candlestick.png")


def plot_candlestick():
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Data file not found at {DATA_PATH}")

    df = pd.read_csv(DATA_PATH)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    # Filter for the last 1 month (35 calendar days)
    latest_date = df["Date"].max()
    one_month_ago = latest_date - pd.Timedelta(days=35)
    df_1mth = df[df["Date"] >= one_month_ago].copy()

    df_1mth.set_index("Date", inplace=True)

    custom_style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mpf.make_marketcolors(
            up="#2ecc71",
            down="#e74c3c",
            edge="inherit",
            wick="inherit",
            volume="#34495e"
        ),
        gridstyle=":",
        facecolor="#121721",
        figcolor="#0b0e14"
    )

    start_str = df_1mth.index[0].strftime("%b %d, %Y")
    end_str = df_1mth.index[-1].strftime("%b %d, %Y")
    latest_close = df_1mth["Close"].iloc[-1]
    
    title = f"CoinDCX XAUUSDT 1-Month Daily Candlestick Chart ({start_str} – {end_str})\nPair: B-XAU_USDT | Latest Close: ${latest_close:,.2f}"

    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(OUTPUT_PNG_LOCAL), exist_ok=True)

    mpf.plot(
        df_1mth,
        type="candle",
        mav=(5, 20),
        volume=True,
        title=title,
        style=custom_style,
        figsize=(14, 8),
        savefig=dict(fname=OUTPUT_PNG_ARTIFACT, dpi=200, bbox_inches="tight")
    )

    mpf.plot(
        df_1mth,
        type="candle",
        mav=(5, 20),
        volume=True,
        title=title,
        style=custom_style,
        figsize=(14, 8),
        savefig=dict(fname=OUTPUT_PNG_LOCAL, dpi=200, bbox_inches="tight")
    )

    print(f"[SUCCESS] Saved Spot Gold candlestick graph to: {OUTPUT_PNG_ARTIFACT}")


if __name__ == "__main__":
    plot_candlestick()
