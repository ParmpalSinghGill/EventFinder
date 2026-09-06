"""
Gold (XAUUSDT) Market Data Downloader
=====================================
Default feed: CoinDCX gold futures B-XAU_USDT (public candles, no API key).

Optional: pass 'futures' to download COMEX GC=F via Yahoo Finance.
"""

import os
import sys

import pandas as pd
import yfinance as yf

from coindcx_gold import COINDCX_PAIR, fetch_daily, fetch_minutes

OUTPUT_DIR = os.path.join("data", "gold_xauusd")


def clean_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten multi-index columns if present and format standard column order."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df.columns.name = None
    df = df.reset_index()

    first_col = df.columns[0]
    expected_cols = [first_col, "Open", "High", "Low", "Close", "Volume"]
    existing_cols = [c for c in expected_cols if c in df.columns]
    remaining_cols = [c for c in df.columns if c not in existing_cols]

    return df[existing_cols + remaining_cols]


def download_coindcx_xau(output_dir: str = OUTPUT_DIR):
    os.makedirs(output_dir, exist_ok=True)
    daily_file = os.path.join(output_dir, "gold_spot_xauusd_1d.csv")
    min_file = os.path.join(output_dir, "gold_spot_xauusd_1m_today.csv")

    print("=" * 75)
    print(" GOLD (XAUUSDT) DATA DOWNLOADER")
    print(f" Feed: CoinDCX {COINDCX_PAIR}  (public, no API key)")
    print(f" Output Directory: {os.path.abspath(output_dir)}")
    print("=" * 75)

    print("\n[1/2] Fetching CoinDCX 1-Day candles ...")
    df_daily = fetch_daily()
    if df_daily.empty:
        print("  [ERROR] No daily candles returned.")
    else:
        df_daily.to_csv(daily_file, index=False)
        print(f"  [SUCCESS] {len(df_daily):,} daily candles.")
        print(f"  Date Range: {df_daily['Date'].iloc[0].date()} to {df_daily['Date'].iloc[-1].date()}")
        print(f"  Saved to: {daily_file}")
        print("\n  Sample (Latest 3 Daily Candles):")
        print(df_daily.tail(3).to_string(index=False))

    print("\n" + "-" * 75)
    print("[2/2] Fetching CoinDCX 1-Minute candles (last 24h) ...")
    df_1m = fetch_minutes(hours=24.0)
    if df_1m.empty:
        print("  [ERROR] No 1-minute candles returned.")
    else:
        df_1m.to_csv(min_file, index=False)
        print(f"  [SUCCESS] {len(df_1m):,} 1-minute candles.")
        print(f"  Time Range: {df_1m['Datetime'].iloc[0]} to {df_1m['Datetime'].iloc[-1]}")
        print(f"  Saved to: {min_file}")
        print("\n  Sample (Latest 3 1-Min Candles):")
        print(df_1m.tail(3).to_string(index=False))

    print("\n" + "=" * 75)
    print(" DOWNLOAD COMPLETE!")
    print("=" * 75)


def download_gc_futures(output_dir: str = OUTPUT_DIR):
    os.makedirs(output_dir, exist_ok=True)
    ticker = "GC=F"
    print("=" * 75)
    print(" GOLD FUTURES DOWNLOADER")
    print(f" Ticker: {ticker} (Yahoo / COMEX)")
    print("=" * 75)

    print("\n[1/2] Fetching 1-Day daily historical data...")
    try:
        df_daily = yf.download(tickers=ticker, period="20y", interval="1d",
                               progress=False, auto_adjust=False)
        if df_daily.empty:
            print("  [ERROR] No daily data returned for ticker:", ticker)
        else:
            df_daily = clean_dataframe(df_daily)
            daily_file = os.path.join(output_dir, "gold_futures_gc_1d.csv")
            df_daily.to_csv(daily_file, index=False)
            date_col = df_daily.columns[0]
            print(f"  [SUCCESS] Downloaded {len(df_daily):,} daily candles.")
            print(f"  Date Range: {str(df_daily[date_col].iloc[0])[:10]} to {str(df_daily[date_col].iloc[-1])[:10]}")
            print(f"  Saved to: {daily_file}")
    except Exception as e:
        print(f"  [ERROR] Failed to download daily data: {e}")

    print("\n[2/2] Fetching 1-Minute data for today's session...")
    try:
        df_1m = yf.download(tickers=ticker, period="1d", interval="1m",
                            progress=False, auto_adjust=False)
        if df_1m.empty:
            print("  [ERROR] No 1-minute data returned.")
        else:
            df_1m = clean_dataframe(df_1m)
            min_file = os.path.join(output_dir, "gold_futures_gc_1m_today.csv")
            df_1m.to_csv(min_file, index=False)
            dt_col = df_1m.columns[0]
            print(f"  [SUCCESS] Downloaded {len(df_1m):,} 1-minute candles.")
            print(f"  Time Range: {df_1m[dt_col].iloc[0]} to {df_1m[dt_col].iloc[-1]}")
            print(f"  Saved to: {min_file}")
    except Exception as e:
        print(f"  [ERROR] Failed to download 1-minute data: {e}")


def download_gold_data(symbol: str = "spot", output_dir: str = OUTPUT_DIR):
    arg = (symbol or "spot").strip().lower()
    if arg in ("futures", "gc", "gc=f"):
        download_gc_futures(output_dir=output_dir)
        return
    download_coindcx_xau(output_dir=output_dir)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else "spot"
    download_gold_data(symbol=arg)
