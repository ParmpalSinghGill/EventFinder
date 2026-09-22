"""
Generate 1 Daily Graph for Gold (XAU/USD) 20-Year Historical Data
===================================================================
Plots 20-year 1-day price history, 50-day & 200-day Moving Averages,
and daily trading volume with dark theme styling.
"""

import os
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

# Set paths
DATA_PATH = os.path.join("gold", "data", "gold_xauusd_1d_20y.csv")
ARTIFACT_DIR = r"C:\Users\parmp\.gemini\antigravity\brain\63f31c9d-d1c3-4775-bda8-e2481dead9bf"
OUTPUT_PNG_ARTIFACT = os.path.join(ARTIFACT_DIR, "gold_xauusd_daily_graph.png")
OUTPUT_PNG_LOCAL = os.path.join("gold", "data", "gold_xauusd_daily_graph.png")

def plot_gold_daily():
    if not os.path.exists(DATA_PATH):
        raise FileNotFoundError(f"Data file not found at {DATA_PATH}")

    df = pd.read_csv(DATA_PATH)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").reset_index(drop=True)

    # Calculate Moving Averages
    df["SMA_50"] = df["Close"].rolling(window=50).mean()
    df["SMA_200"] = df["Close"].rolling(window=200).mean()

    # Dark visual style setup
    plt.style.use("dark_background")
    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(14, 8), gridspec_kw={"height_ratios": [3, 1]}, sharex=True
    )
    fig.patch.set_facecolor("#0b0e14")
    ax1.set_facecolor("#121721")
    ax2.set_facecolor("#121721")

    # Top Plot: Gold Price & MAs
    ax1.plot(df["Date"], df["Close"], label="XAU/USD Close Price", color="#f39c12", linewidth=1.5, alpha=0.95)
    ax1.plot(df["Date"], df["SMA_50"], label="50-Day SMA", color="#3498db", linewidth=1.2, linestyle="--")
    ax1.plot(df["Date"], df["SMA_200"], label="200-Day SMA", color="#e74c3c", linewidth=1.2, linestyle="--")

    # Annotations for min/max
    max_idx = df["Close"].idxmax()
    max_date = df.loc[max_idx, "Date"]
    max_price = df.loc[max_idx, "Close"]
    
    ax1.annotate(
        f"All-Time High: ${max_price:,.2f}",
        xy=(max_date, max_price),
        xytext=(max_date - pd.Timedelta(days=1200), max_price * 0.90),
        arrowprops=dict(facecolor="#2ecc71", edgecolor="#2ecc71", shrink=0.05, width=1.5, headwidth=8),
        fontsize=10,
        fontweight="bold",
        color="#2ecc71",
        bbox=dict(boxstyle="round,pad=0.3", fc="#1e272e", ec="#2ecc71", lw=1),
    )

    latest_date = df["Date"].iloc[-1].strftime("%Y-%m-%d")
    latest_price = df["Close"].iloc[-1]

    ax1.set_title(
        f"Gold (XAU/USD) 20-Year Daily Price Chart (2006 – {latest_date[:4]})\n"
        f"Latest Close: ${latest_price:,.2f} USD | 24-Hour Forex Market",
        fontsize=14,
        fontweight="bold",
        color="#ffffff",
        pad=12,
    )
    ax1.set_ylabel("Price (USD / oz)", fontsize=12, color="#cccccc")
    ax1.legend(loc="upper left", frameon=True, facecolor="#1e272e", edgecolor="#444444", fontsize=10)
    ax1.grid(True, color="#2c3e50", linestyle=":", alpha=0.6)
    ax1.yaxis.set_major_formatter("${x:,.0f}")

    # Bottom Plot: Volume
    ax2.bar(df["Date"], df["Volume"], color="#34495e", width=2.0, alpha=0.7)
    ax2.set_ylabel("Volume", fontsize=11, color="#cccccc")
    ax2.set_xlabel("Year", fontsize=12, color="#cccccc")
    ax2.grid(True, color="#2c3e50", linestyle=":", alpha=0.6)
    ax2.xaxis.set_major_locator(mdates.YearLocator(2))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax2.yaxis.set_major_formatter("{x:,.0f}")

    plt.xticks(rotation=0)
    plt.tight_layout()

    # Save to both artifact directory and data directory
    os.makedirs(ARTIFACT_DIR, exist_ok=True)
    os.makedirs(os.path.dirname(OUTPUT_PNG_LOCAL), exist_ok=True)

    fig.savefig(OUTPUT_PNG_ARTIFACT, dpi=200, bbox_inches="tight")
    fig.savefig(OUTPUT_PNG_LOCAL, dpi=200, bbox_inches="tight")
    plt.close(fig)

    print(f"[SUCCESS] Saved graph artifact to: {OUTPUT_PNG_ARTIFACT}")
    print(f"[SUCCESS] Saved graph copy to: {OUTPUT_PNG_LOCAL}")

if __name__ == "__main__":
    plot_gold_daily()
