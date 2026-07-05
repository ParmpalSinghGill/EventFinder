"""
Download 1-HOUR (1h) OHLCV data for all NSE-listed equities via yfinance,
covering the most recent ~30 days (yfinance only serves intraday bars for a
limited trailing window).

Run inside the STOCK conda env:
    conda run -n STOCK python download_nse_hourly.py
    conda run -n STOCK python download_nse_hourly.py --days 30 --workers 8

Notes:
    * One file per symbol in data/nse_hourly/ -> resumable (re-running skips
      files already on disk; use the updater to refresh them).
    * Files carry a "Datetime" column (date + time, IST) instead of "Date".
    * For day-to-day refreshing use update_data.py, which updates BOTH the daily
      and hourly datasets in a single run and only re-downloads on a data
      discrepancy (corporate action).
"""

import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd

from download_nse_daily import download_one, get_nse_symbols


def main():
    p = argparse.ArgumentParser(description="Download NSE 1-hour data via yfinance.")
    p.add_argument("--days", type=int, default=30,
                   help="Trailing window of hourly data to fetch (default 30).")
    p.add_argument("--outdir", default="data/nse_hourly", help="Output directory.")
    p.add_argument("--format", choices=["csv", "parquet"], default="csv")
    p.add_argument("--workers", type=int, default=8, help="Parallel download threads.")
    p.add_argument("--limit", type=int, default=0, help="Only first N symbols (testing).")
    p.add_argument("--symbols-file", default="", help="Optional CSV with a SYMBOL column.")
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    cache_path = os.path.join(os.path.dirname(args.outdir) or ".", "nse_equity_list.csv")

    if args.symbols_file:
        symbols = pd.read_csv(args.symbols_file)["SYMBOL"].astype(str).str.strip().tolist()
    else:
        symbols = get_nse_symbols(cache_path)["SYMBOL"].astype(str).str.strip().tolist()
    if args.limit:
        symbols = symbols[: args.limit]

    period = f"{args.days}d"
    total = len(symbols)
    print(f"Downloading {period} of 1h data for {total} symbols "
          f"-> {args.outdir} ({args.format}), {args.workers} workers\n")

    ok = skip = fail = 0
    failures = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(download_one, s, 0, args.outdir, args.format, 3, False,
                      "1h", period): s
            for s in symbols
        }
        for i, fut in enumerate(as_completed(futs), 1):
            symbol, status, info = fut.result()
            if status == "ok":
                ok += 1
            elif status == "skip":
                skip += 1
            else:
                fail += 1
                failures.append((symbol, info))
            if i % 25 == 0 or i == total:
                rate = i / max(time.time() - t0, 1e-6)
                print(f"[{i}/{total}] ok={ok} skip={skip} fail={fail} ({rate:.1f}/s)")

    if failures:
        fpath = os.path.join(os.path.dirname(args.outdir) or ".", "failures_hourly.csv")
        pd.DataFrame(failures, columns=["SYMBOL", "error"]).to_csv(fpath, index=False)
        print(f"\n{len(failures)} failures written to {fpath} "
              f"(re-run the script to retry — successes are skipped).")

    dt = time.time() - t0
    print(f"\nDone in {dt/60:.1f} min. ok={ok} skip={skip} fail={fail} "
          f"total={total}. Data in: {os.path.abspath(args.outdir)}")


if __name__ == "__main__":
    main()
