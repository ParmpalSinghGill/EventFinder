"""
Download TradingView XAUUSD candles (Vantage by default).

Does not touch CoinDCX files or the Gold Event Finder.
Output: data/gold_tv_xauusd/

  python download_tv_xauusd.py           # VANTAGE:XAUUSD
  python download_tv_xauusd.py oanda     # OANDA:XAUUSD (TradingView public default)
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import sys

from gold.tradingview_gold import DEFAULT_EXCHANGE, DEFAULT_SYMBOL, DATA_DIR, csv_path, fetch_latest_data


def download_tv_xauusd(exchange: str = DEFAULT_EXCHANGE) -> None:
    ex = (exchange or DEFAULT_EXCHANGE).strip().upper()
    print("=" * 75)
    print(" TRADINGVIEW XAUUSD DOWNLOADER")
    print(f" Symbol: {ex}:{DEFAULT_SYMBOL}")
    print(f" Output: {DATA_DIR}")
    print(" CoinDCX Event Finder files are not modified.")
    print("=" * 75)

    daily, minutes = fetch_latest_data(save=True, exchange=ex, symbol=DEFAULT_SYMBOL)
    daily_file = csv_path(ex, "1d")
    min_file = csv_path(ex, "1m")

    print(f"\n[1/2] Daily candles: {len(daily):,}")
    if daily.empty:
        print("  [ERROR] No daily candles.")
    else:
        print(f"  Date range: {daily['Date'].iloc[0].date()} to {daily['Date'].iloc[-1].date()}")
        print(f"  Saved to: {daily_file}")
        print("\n  Latest 3 daily candles:")
        print(daily.tail(3).to_string(index=False))

    print("\n" + "-" * 75)
    print(f"[2/2] 1-minute candles: {len(minutes):,}")
    if minutes.empty:
        print("  [ERROR] No 1-minute candles.")
    else:
        print(f"  Time range: {minutes['Datetime'].iloc[0]} to {minutes['Datetime'].iloc[-1]}")
        print(f"  Saved to: {min_file}")
        print("\n  Latest 3 1-minute candles:")
        print(minutes.tail(3).to_string(index=False))

    print("\n" + "=" * 75)
    print(" DOWNLOAD COMPLETE")
    print("=" * 75)


if __name__ == "__main__":
    arg = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_EXCHANGE
    download_tv_xauusd(exchange=arg)
