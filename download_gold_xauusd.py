"""
Gold (XAU/USD) Market Data Downloader
=====================================
Downloads Gold price data for:
  - Spot Gold / Crypto PAXG (Matches CoinDCX & TradingView Spot XAUUSD): 'PAXG-USD'
  - 24-Hour Gold Futures (COMEX Benchmark): 'GC=F'

Features:
  1. 1-Day timeframe historical data.
  2. 1-Minute timeframe data for today's session.
"""

import os
import sys
import pandas as pd
import yfinance as yf

# Available ticker options
TICKER_MAP = {
    "spot": "PAXG-USD",   # Spot Gold token (Matches CoinDCX PAXG/USDT & TradingView Spot XAUUSD)
    "futures": "GC=F"      # COMEX Gold Futures 24h market
}

DEFAULT_SYMBOL = "PAXG-USD"
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


def download_gold_data(symbol: str = DEFAULT_SYMBOL, output_dir: str = OUTPUT_DIR):
    """Download daily and 1-minute Gold data."""
    os.makedirs(output_dir, exist_ok=True)
    
    is_spot = (symbol.upper() in ["SPOT", "PAXG-USD", "PAXG"])
    ticker = TICKER_MAP["spot"] if is_spot else TICKER_MAP.get(symbol.lower(), symbol)
    market_name = "Spot Gold (CoinDCX & TradingView Spot XAU/USD)" if is_spot else "COMEX Gold Futures 24h"

    print("=" * 75)
    print(f" GOLD (XAU/USD) DATA DOWNLOADER")
    print(f" Asset Type: {market_name}")
    print(f" Ticker Symbol: {ticker}")
    print(f" Output Directory: {os.path.abspath(output_dir)}")
    print("=" * 75)

    # 1. Download Daily Data (1-Day candles)
    print("\n[1/2] Fetching 1-Day daily historical data...")
    try:
        df_daily = yf.download(
            tickers=ticker,
            period="max" if is_spot else "20y",
            interval="1d",
            progress=False,
            auto_adjust=False
        )
        
        if df_daily.empty:
            print("  [ERROR] No daily data returned for ticker:", ticker)
        else:
            df_daily = clean_dataframe(df_daily)
            prefix = "spot_xauusd" if is_spot else "futures_gc"
            daily_file = os.path.join(output_dir, f"gold_{prefix}_1d.csv")
            df_daily.to_csv(daily_file, index=False)
            
            date_col = df_daily.columns[0]
            start_date = str(df_daily[date_col].iloc[0])[:10]
            end_date = str(df_daily[date_col].iloc[-1])[:10]
            
            print(f"  [SUCCESS] Downloaded {len(df_daily):,} daily candles.")
            print(f"  Date Range: {start_date} to {end_date}")
            print(f"  Saved to: {daily_file}")
            print("\n  Sample (Latest 3 Daily Candles):")
            print(df_daily.tail(3).to_string(index=False))

    except Exception as e:
        print(f"  [ERROR] Failed to download daily data: {e}")

    # 2. Download Intraday Data (1-Minute candles for today)
    print("\n" + "-" * 75)
    print("[2/2] Fetching 1-Minute data for today's session...")
    try:
        df_1m = yf.download(
            tickers=ticker,
            period="1d",
            interval="1m",
            progress=False,
            auto_adjust=False
        )
        
        if df_1m.empty:
            print("  [WARNING] No 1m data for period='1d'. Retrying period='5d' filtered for today...")
            df_5d_1m = yf.download(
                tickers=ticker,
                period="5d",
                interval="1m",
                progress=False,
                auto_adjust=False
            )
            if not df_5d_1m.empty:
                df_5d_1m = clean_dataframe(df_5d_1m)
                dt_col = df_5d_1m.columns[0]
                latest_date = df_5d_1m[dt_col].max().date()
                df_1m = df_5d_1m[df_5d_1m[dt_col].dt.date == latest_date].copy()

        if df_1m.empty:
            print("  [ERROR] No 1-minute data returned.")
        else:
            df_1m = clean_dataframe(df_1m)
            prefix = "spot_xauusd" if is_spot else "futures_gc"
            min_file = os.path.join(output_dir, f"gold_{prefix}_1m_today.csv")
            df_1m.to_csv(min_file, index=False)
            
            dt_col = df_1m.columns[0]
            start_time = str(df_1m[dt_col].iloc[0])
            end_time = str(df_1m[dt_col].iloc[-1])
            
            print(f"  [SUCCESS] Downloaded {len(df_1m):,} 1-minute candles.")
            print(f"  Time Range: {start_time} to {end_time}")
            print(f"  Saved to: {min_file}")
            print("\n  Sample (Latest 3 1-Min Candles):")
            print(df_1m.tail(3).to_string(index=False))

    except Exception as e:
        print(f"  [ERROR] Failed to download 1-minute data: {e}")

    print("\n" + "=" * 75)
    print(" DOWNLOAD COMPLETE!")
    print("=" * 75)


if __name__ == "__main__":
    # Pass 'spot' or 'futures' as argument, e.g.: python download_gold_xauusd.py spot
    arg = sys.argv[1] if len(sys.argv) > 1 else "spot"
    download_gold_data(symbol=arg)
