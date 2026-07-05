"""
Download ~10 years of DAILY (1d) OHLCV data for all NSE-listed equities via yfinance.

Run inside the STOCK conda env:
    conda run -n STOCK python download_nse_daily.py
    conda run -n STOCK python download_nse_daily.py --years 10 --workers 8 --format csv

Features:
    * Pulls the official NSE equity master list (cached locally).
    * One file per symbol -> resumable (re-running skips files already on disk).
    * Threaded downloads with retry + a failures log you can re-run later.
"""

import argparse
import io
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import requests
import yfinance as yf

NSE_EQUITY_LIST_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/csv,application/csv,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def get_nse_symbols(cache_path: str) -> pd.DataFrame:
    """Return DataFrame of NSE equities. Cached to disk after first fetch."""
    if os.path.exists(cache_path):
        print(f"Using cached symbol list: {cache_path}")
        return pd.read_csv(cache_path)

    print(f"Fetching NSE equity master list from {NSE_EQUITY_LIST_URL} ...")
    sess = requests.Session()
    sess.headers.update(NSE_HEADERS)
    # Prime cookies via the homepage (NSE blocks cold archive requests).
    try:
        sess.get("https://www.nseindia.com", timeout=15)
    except requests.RequestException:
        pass
    resp = sess.get(NSE_EQUITY_LIST_URL, timeout=30)
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text))
    df.columns = [c.strip() for c in df.columns]
    # Keep only normal equity series (EQ, BE) – skip ETFs/odd series if present.
    if "SERIES" in df.columns:
        df = df[df["SERIES"].astype(str).str.strip().isin(["EQ", "BE"])]
    df = df.reset_index(drop=True)
    df.to_csv(cache_path, index=False)
    print(f"Saved {len(df)} symbols to {cache_path}")
    return df


def download_one(symbol: str, years: int, outdir: str, fmt: str, retries: int = 3,
                 force: bool = False, interval: str = "1d", period: str = None):
    """Download one symbol's history. Returns (symbol, status, rows/err).

    force=True overwrites an existing file (used by the updater to re-sync a
    symbol after a corporate action like a split/bonus). `interval` / `period`
    let the same routine pull daily ("1d", period "10y") or intraday
    ("1h", period "30d") bars; intraday pulls yield a "Datetime" column instead
    of "Date" (whatever yfinance names the index).
    """
    yf_symbol = f"{symbol}.NS"
    ext = "parquet" if fmt == "parquet" else "csv"
    out_path = os.path.join(outdir, f"{symbol}.{ext}")

    if not force and os.path.exists(out_path) and os.path.getsize(out_path) > 0:
        return symbol, "skip", 0

    period = period or f"{years}y"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            df = yf.download(
                yf_symbol,
                period=period,
                interval=interval,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if df is None or df.empty:
                last_err = "no data"
                time.sleep(1.0 * attempt)
                continue
            # Flatten the (price, ticker) column MultiIndex yfinance returns.
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)
            df = df.reset_index()
            df.insert(1, "Symbol", symbol)
            if fmt == "parquet":
                df.to_parquet(out_path, index=False)
            else:
                df.to_csv(out_path, index=False)
            return symbol, "ok", len(df)
        except Exception as e:  # noqa: BLE001 - log and move on
            last_err = str(e)
            time.sleep(1.0 * attempt)
    return symbol, "fail", last_err


def main():
    p = argparse.ArgumentParser(description="Download NSE daily data via yfinance.")
    p.add_argument("--years", type=int, default=10, help="Years of history (default 10).")
    p.add_argument("--outdir", default="data/nse_daily", help="Output directory.")
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

    total = len(symbols)
    print(f"Downloading {args.years}y daily data for {total} symbols "
          f"-> {args.outdir} ({args.format}), {args.workers} workers\n")

    ok = skip = fail = 0
    failures = []
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {
            ex.submit(download_one, s, args.years, args.outdir, args.format): s
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
                print(f"[{i}/{total}] ok={ok} skip={skip} fail={fail} "
                      f"({rate:.1f}/s)")

    if failures:
        fpath = os.path.join(os.path.dirname(args.outdir) or ".", "failures.csv")
        pd.DataFrame(failures, columns=["SYMBOL", "error"]).to_csv(fpath, index=False)
        print(f"\n{len(failures)} failures written to {fpath} "
              f"(re-run the script to retry — successes are skipped).")

    dt = time.time() - t0
    print(f"\nDone in {dt/60:.1f} min. ok={ok} skip={skip} fail={fail} "
          f"total={total}. Data in: {os.path.abspath(args.outdir)}")


if __name__ == "__main__":
    main()
