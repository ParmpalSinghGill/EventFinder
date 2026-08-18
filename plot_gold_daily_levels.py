"""
Plot 1-Day Candlestick Chart for Spot Gold (XAU/USD) with Updated Level Rules
=============================================================================
Rules:
  - PDC (Prev Day Close) removed.
  - Prev Day Low (PDL) suppressed if crossed by today's price action.
  - Displays only active uncrossed levels.
"""

import os
import sys
import pandas as pd
import mplfinance as mpf

sys.path.append(os.getcwd())
from xauusd_event_finder import fetch_latest_data, compute_stock_screener_levels

DATA_DIR = os.path.join("data", "gold_xauusd")
ARTIFACT_DIR = r"C:\Users\parmp\.gemini\antigravity\brain\63f31c9d-d1c3-4775-bda8-e2481dead9bf"
OUTPUT_PNG_ARTIFACT = os.path.join(ARTIFACT_DIR, "gold_spot_daily_candles_with_levels.png")
OUTPUT_PNG_LOCAL = os.path.join(DATA_DIR, "gold_spot_daily_candles_with_levels.png")


def plot_daily_candles_with_levels():
    df_daily, df_1m = fetch_latest_data()
    date_col = df_daily.columns[0]
    df_daily[date_col] = pd.to_datetime(df_daily[date_col])
    df_daily = df_daily.sort_values(date_col).reset_index(drop=True)

    df_recent = df_daily.iloc[-45:].copy()
    current_price = float(df_recent["Close"].iloc[-1])

    # Compute key active uncrossed levels using updated rules
    levels = compute_stock_screener_levels(df_daily, df_1m, current_price)

    df_recent.set_index(date_col, inplace=True)

    # Filter levels within display range ($3,900 to $4,800)
    price_min = df_recent["Low"].min() * 0.96
    price_max = df_recent["High"].max() * 1.08
    plot_levels = [l for l in levels if price_min <= l["price"] <= price_max]

    color_map = {
        "2-Year": "#9b59b6",     # Purple
        "1-Year": "#e67e22",     # Orange
        "Monthly": "#f1c40f",    # Gold/Yellow
        "Weekly": "#e74c3c",     # Red
        "Daily": "#3498db",      # Blue
        "PrevDay": "#2ecc71"     # Green
    }

    hlines_prices = [l["price"] for l in plot_levels]
    hlines_colors = [color_map.get(l["timeframe"], "#ffffff") for l in plot_levels]
    hlines_styles = ["--" if "Low" in l["name"] or "Support" in l["name"] or "PDL" in l["name"] else "-" for l in plot_levels]

    custom_style = mpf.make_mpf_style(
        base_mpf_style="nightclouds",
        marketcolors=mpf.make_marketcolors(
            up="#2ecc71", down="#e74c3c", edge="inherit", wick="inherit", volume="#34495e"
        ),
        gridstyle=":",
        facecolor="#121721",
        figcolor="#0b0e14"
    )

    start_date_str = df_recent.index[0].strftime("%b %d, %Y")
    end_date_str = df_recent.index[-1].strftime("%b %d, %Y")

    title = (
        f"Spot Gold (XAU/USD) Daily Candlestick Chart with Active Uncrossed Levels\n"
        f"Period: {start_date_str} to {end_date_str} | Current Price: ${current_price:,.2f} USD\n"
        f"Rules: PDC Removed, Crossed Levels Cancelled | Yellow=Monthly, Red=Weekly, Blue=Daily, Green=PrevDay"
    )

    os.makedirs(ARTIFACT_DIR, exist_ok=True)

    mpf.plot(
        df_recent,
        type="candle",
        volume=True,
        hlines=dict(hlines=hlines_prices, colors=hlines_colors, linestyle=hlines_styles, linewidths=1.3),
        title=title,
        style=custom_style,
        figsize=(15, 9),
        savefig=dict(fname=OUTPUT_PNG_ARTIFACT, dpi=200, bbox_inches="tight")
    )
    
    mpf.plot(
        df_recent,
        type="candle",
        volume=True,
        hlines=dict(hlines=hlines_prices, colors=hlines_colors, linestyle=hlines_styles, linewidths=1.3),
        title=title,
        style=custom_style,
        figsize=(15, 9),
        savefig=dict(fname=OUTPUT_PNG_LOCAL, dpi=200, bbox_inches="tight")
    )

    print(f"[SUCCESS] Saved Daily Candlesticks with Levels to: {OUTPUT_PNG_ARTIFACT}")


if __name__ == "__main__":
    plot_daily_candles_with_levels()
