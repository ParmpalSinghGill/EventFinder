"""
ONE command to bring BOTH datasets up to date:
    * data/nse_daily/  -> ~10y daily bars   (update_nse_daily)
    * data/nse_hourly/ -> last ~30d 1h bars (update_nse_hourly)

Both updaters are incremental: they append only the new bars and overwrite the
in-progress (today / current-hour) bar. A full re-download happens ONLY when a
confirmed historical bar's Close no longer matches the fresh pull (i.e. a
corporate action such as a split/bonus) -- identical safety logic for both
timeframes. Missing files are downloaded automatically, so the very first run
also bootstraps anything not yet on disk.

Run inside the STOCK conda env:
    conda run -n STOCK python update_data.py
    conda run -n STOCK python update_data.py --workers 8 --days 30
    conda run -n STOCK python update_data.py --only daily      # just one side
    conda run -n STOCK python update_data.py --limit 5         # quick test
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import argparse
import time

import stock.update_nse_daily as daily
import stock.update_nse_hourly as hourly


def main():
    p = argparse.ArgumentParser(
        description="Update both the daily and hourly NSE datasets in one run.")
    p.add_argument("--only", choices=["both", "daily", "hourly"], default="both",
                   help="Update only one dataset (default: both).")
    p.add_argument("--workers", type=int, default=8, help="Parallel threads per stage.")
    p.add_argument("--limit", type=int, default=0, help="Only first N symbols (testing).")
    p.add_argument("--symbols-file", default="", help="Optional CSV with a SYMBOL column.")
    p.add_argument("--force", action="store_true",
                   help="Ignore the 'already ran after close' skip on both stages.")
    p.add_argument("--tol", type=float, default=0.001,
                   help="Corporate-action Close tolerance for both stages.")
    # daily-specific
    p.add_argument("--daily-dir", default="stock/data/nse_daily")
    p.add_argument("--years", type=int, default=10, help="Daily history depth for re-syncs.")
    p.add_argument("--overlap", type=int, default=2, help="Daily overlap trading days.")
    # hourly-specific
    p.add_argument("--hourly-dir", default="stock/data/nse_hourly")
    p.add_argument("--days", type=int, default=30, help="Hourly trailing window (days).")
    p.add_argument("--overlap-hours", type=int, default=6, help="Hourly overlap hours.")
    args = p.parse_args()

    t0 = time.time()
    common = dict(workers=args.workers, limit=args.limit,
                  symbols_file=args.symbols_file, force=args.force, tol=args.tol)

    if args.only in ("both", "daily"):
        print("=" * 70)
        print("STAGE 1/2: DAILY (data/nse_daily)")
        print("=" * 70)
        daily.run(outdir=args.daily_dir, years=args.years, overlap=args.overlap,
                  **common)

    if args.only in ("both", "hourly"):
        print("\n" + "=" * 70)
        print(f"STAGE 2/2: HOURLY 1h, last {args.days}d (data/nse_hourly)")
        print("=" * 70)
        hourly.run(outdir=args.hourly_dir, days=args.days,
                   overlap_hours=args.overlap_hours, **common)

    print(f"\nAll done in {(time.time() - t0)/60:.1f} min.")


if __name__ == "__main__":
    main()
