"""
Incrementally bring the NSE daily dataset up to date, with run-state tracking.

A separate state file (data/update_state.csv) records, per symbol:
    last_date          - date of the most recent bar on disk
    last_bar_final     - 1 if that bar is final (fetched after market close or a
                         past trading day), 0 if it is an in-progress / partial
                         bar fetched during market hours
    ran_after_close    - 1 if the last run happened after market close
    last_run           - ISO timestamp (IST) of the last run for that symbol

How a run decides what to do for each symbol:
  * Already updated AFTER CLOSE today -> SKIP entirely (no network call).
  * Last stored today-bar was PARTIAL (intraday run) -> re-fetch and OVERWRITE
    just today's bar (plus append any new days). NO full resync.
  * A CONFIRMED historical bar (a date before today, and not a previously-partial
    bar) mismatches the fresh pull -> real corporate action -> full resync.
  * Missing on disk -> full download.

Run inside the STOCK conda env:
    conda run -n STOCK python update_nse_daily.py
    conda run -n STOCK python update_nse_daily.py --overlap 2 --tol 0.001 --workers 8
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import argparse
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, time as dtime, timedelta, timezone

import pandas as pd
import yfinance as yf

from stock.download_nse_daily import download_one, get_nse_symbols

COLS = ["Date", "Symbol", "Close", "High", "Low", "Open", "Volume"]

# NSE trades in IST (UTC+5:30, no DST). Treat a bar for *today* as final only
# once we are past the close + a short buffer for data to settle.
IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE = dtime(15, 40)  # 15:30 close + ~10 min buffer


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
def load_state(path: str) -> dict:
    """Return {symbol: {last_date(Timestamp), last_bar_final(bool),
                        ran_after_close(bool), last_run_date(Timestamp|NaT)}}."""
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path)
    state = {}
    for _, r in df.iterrows():
        try:
            last_date = pd.to_datetime(r["last_date"]).normalize()
        except Exception:  # noqa: BLE001
            continue
        try:
            # Take the IST calendar date and drop tz so it compares equal to
            # the tz-naive `today` Timestamp used in update_one.
            last_run_date = pd.Timestamp(pd.to_datetime(r["last_run"]).date())
        except Exception:  # noqa: BLE001
            last_run_date = pd.NaT
        state[str(r["SYMBOL"]).strip()] = {
            "last_date": last_date,
            "last_bar_final": bool(int(r.get("last_bar_final", 0))),
            "ran_after_close": bool(int(r.get("ran_after_close", 0))),
            "last_run_date": last_run_date,
        }
    return state


def is_final(last_date: pd.Timestamp, today: pd.Timestamp, after_close: bool) -> bool:
    """A bar is final if it is a past trading day, or it is today and we are
    already past market close."""
    if last_date < today:
        return True
    return last_date == today and after_close


def make_record(symbol, last_date, today, after_close, now_iso):
    return {
        "SYMBOL": symbol,
        "last_date": last_date.strftime("%Y-%m-%d"),
        "last_bar_final": int(is_final(last_date, today, after_close)),
        "ran_after_close": int(after_close),
        "last_run": now_iso,
    }


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #
def _read_existing(path: str, fmt: str) -> pd.DataFrame:
    df = pd.read_parquet(path) if fmt == "parquet" else pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None).dt.normalize()
    return df.sort_values("Date").reset_index(drop=True)


def _fetch(yf_symbol: str, start, end) -> pd.DataFrame:
    df = yf.download(yf_symbol, start=start, end=end, interval="1d",
                     auto_adjust=True, progress=False, threads=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    df["Date"] = pd.to_datetime(df["Date"]).dt.tz_localize(None).dt.normalize()
    return df


def _write(df: pd.DataFrame, path: str, fmt: str):
    keep = [c for c in COLS if c in df.columns]
    if fmt == "parquet":
        df[keep].to_parquet(path, index=False)
    else:
        df[keep].to_csv(path, index=False)


# --------------------------------------------------------------------------- #
# Per-symbol update
# --------------------------------------------------------------------------- #
def update_one(symbol, outdir, fmt, years, overlap_days, tol,
               today, after_close, now_iso, prev, retries=3):
    """Returns (symbol, status, info, state_record). status in:
       skip_recent / new / uptodate / appended / updated / resync / fail."""
    ext = "parquet" if fmt == "parquet" else "csv"
    path = os.path.join(outdir, f"{symbol}.{ext}")
    yf_symbol = f"{symbol}.NS"

    # --- Fast path: already refreshed after close today -> nothing new exists.
    if (prev and prev["ran_after_close"]
            and prev["last_run_date"] == today and prev["last_bar_final"]):
        rec = make_record(symbol, prev["last_date"], today, after_close, now_iso)
        return symbol, "skip_recent", 0, rec

    # --- Missing on disk -> full download.
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        _, st, info = download_one(symbol, years, outdir, fmt, retries, force=True)
        if st != "ok":
            return symbol, "fail", info, None
        ld = _read_existing(path, fmt)["Date"].max()
        return symbol, "new", info, make_record(symbol, ld, today, after_close, now_iso)

    try:
        old = _read_existing(path, fmt)
    except Exception as e:  # noqa: BLE001
        return symbol, "fail", f"read error: {e}", None
    if old.empty:
        _, st, info = download_one(symbol, years, outdir, fmt, retries, force=True)
        if st != "ok":
            return symbol, "fail", info, None
        ld = _read_existing(path, fmt)["Date"].max()
        return symbol, "new", info, make_record(symbol, ld, today, after_close, now_iso)

    last_date = old["Date"].max()
    start = (last_date - pd.tseries.offsets.BDay(overlap_days)).normalize()
    end = today + pd.Timedelta(days=1)  # yfinance 'end' is exclusive

    last_err = None
    fresh = None
    for attempt in range(1, retries + 1):
        try:
            fresh = _fetch(yf_symbol, start, end)
            break
        except Exception as e:  # noqa: BLE001
            last_err = str(e)
            time.sleep(1.0 * attempt)
    if fresh is None:
        return symbol, "fail", last_err, None
    if fresh.empty:
        rec = make_record(symbol, last_date, today, after_close, now_iso)
        return symbol, "uptodate", 0, rec

    old_dates, fresh_dates = set(old["Date"]), set(fresh["Date"])

    # Dates we must NOT use for corporate-action detection: today's (possibly
    # partial) bar, and any bar that was previously stored as partial.
    exclude = {today}
    if prev and not prev["last_bar_final"]:
        exclude.add(prev["last_date"])
    cmp_dates = sorted((old_dates & fresh_dates) - exclude)

    def _resync(reason):
        _, st, info = download_one(symbol, years, outdir, fmt, retries, force=True)
        if st != "ok":
            return symbol, "fail", info, None
        ld = _read_existing(path, fmt)["Date"].max()
        return (symbol, "resync", reason,
                make_record(symbol, ld, today, after_close, now_iso))

    if cmp_dates:
        o = old.set_index("Date").loc[cmp_dates, "Close"].astype(float)
        f = fresh.set_index("Date").loc[cmp_dates, "Close"].astype(float)
        rel = (o - f).abs() / o.replace(0, pd.NA)
        max_rel = float(rel.max()) if len(rel) else 0.0
        if pd.notna(max_rel) and max_rel > tol:
            return _resync(f"max_overlap_diff={max_rel:.4f}")
    elif not (old_dates & fresh_dates):
        # No overlap at all (a long gap) -> re-sync to be safe.
        return _resync("no overlap")

    # --- Merge: fresh wins on shared dates (overwrites today's partial bar),
    #     and brings in any genuinely new days. No full resync needed.
    fresh = fresh.assign(Symbol=symbol)
    combined = (pd.concat([old, fresh], ignore_index=True)
                .drop_duplicates(subset="Date", keep="last")
                .sort_values("Date")
                .reset_index(drop=True))
    new_last = combined["Date"].max()

    rec = make_record(symbol, new_last, today, after_close, now_iso)

    if len(combined) > len(old):
        _write(combined, path, fmt)
        return symbol, "appended", len(combined) - len(old), rec

    # Same set of dates -> did today's (partial) bar value actually change?
    if today in old_dates and today in fresh_dates:
        oc = float(old.loc[old["Date"] == today, "Close"].iloc[0])
        fc = float(fresh.loc[fresh["Date"] == today, "Close"].iloc[0])
        if oc != 0 and abs(oc - fc) / oc > 1e-9:
            _write(combined, path, fmt)
            return symbol, "updated", 1, rec

    return symbol, "uptodate", 0, rec


# --------------------------------------------------------------------------- #
def run(outdir="stock/data/nse_daily", fmt="csv", years=10, overlap=2, tol=0.001,
        workers=8, limit=0, symbols_file="", state_file="", force=False):
    """Incrementally update the daily dataset. Returns the status-count dict."""
    if not os.path.isdir(outdir):
        raise SystemExit(f"Output dir not found: {outdir}. Run the downloader first.")

    base = os.path.dirname(outdir) or "."
    state_path = state_file or os.path.join(base, "update_state.csv")

    if symbols_file:
        symbols = pd.read_csv(symbols_file)["SYMBOL"].astype(str).str.strip().tolist()
    else:
        cache = os.path.join(base, "nse_equity_list.csv")
        symbols = get_nse_symbols(cache)["SYMBOL"].astype(str).str.strip().tolist()
    if limit:
        symbols = symbols[:limit]

    now_ist = datetime.now(IST)
    today = pd.Timestamp(now_ist.date())          # tz-naive, normalized
    after_close = now_ist.time() >= MARKET_CLOSE
    now_iso = now_ist.isoformat(timespec="seconds")

    prev_state = {} if force else load_state(state_path)

    total = len(symbols)
    print(f"Updating {total} symbols @ {now_iso} "
          f"(after_close={after_close}, overlap={overlap}d, tol={tol}, "
          f"{workers} workers)\n")

    counts = {}
    failures, resyncs = [], []
    new_state = dict(prev_state)  # start from old; overwrite per result
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(update_one, s, outdir, fmt, years,
                          overlap, tol, today, after_close, now_iso,
                          prev_state.get(s)): s for s in symbols}
        for i, fut in enumerate(as_completed(futs), 1):
            symbol, status, info, rec = fut.result()
            counts[status] = counts.get(status, 0) + 1
            if rec is not None:
                new_state[symbol] = rec
            if status == "fail":
                failures.append((symbol, info))
            elif status == "resync":
                resyncs.append((symbol, info))
            if i % 25 == 0 or i == total:
                rate = i / max(time.time() - t0, 1e-6)
                done = {k: counts.get(k, 0) for k in
                        ("skip_recent", "appended", "updated", "uptodate",
                         "resync", "new", "fail")}
                print(f"[{i}/{total}] {done} ({rate:.1f}/s)")

    # Persist state (one write, no thread races).
    if new_state:
        pd.DataFrame(list(new_state.values()))[
            ["SYMBOL", "last_date", "last_bar_final", "ran_after_close", "last_run"]
        ].sort_values("SYMBOL").to_csv(state_path, index=False)

    if resyncs:
        pd.DataFrame(resyncs, columns=["SYMBOL", "info"]).to_csv(
            os.path.join(base, "resynced.csv"), index=False)
    if failures:
        pd.DataFrame(failures, columns=["SYMBOL", "error"]).to_csv(
            os.path.join(base, "update_failures.csv"), index=False)

    dt = time.time() - t0
    print(f"\nDone in {dt/60:.1f} min. {counts}")
    print(f"State saved to {state_path}")
    if resyncs:
        print(f"{len(resyncs)} re-synced (corporate action) -> resynced.csv")
    if failures:
        print(f"{len(failures)} failures -> update_failures.csv (re-run to retry).")
    return counts


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="Incrementally update NSE daily data.")
    p.add_argument("--outdir", default="stock/data/nse_daily")
    p.add_argument("--format", choices=["csv", "parquet"], default="csv")
    p.add_argument("--years", type=int, default=10, help="History depth for re-syncs.")
    p.add_argument("--overlap", type=int, default=2, help="Overlap trading days (1-2).")
    p.add_argument("--tol", type=float, default=0.001,
                   help="Max relative Close diff on confirmed bars before treating "
                        "it as a corporate action (default 0.1%%).")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--symbols-file", default="")
    p.add_argument("--state-file", default="",
                   help="Path to run-state CSV (default <parent-of-outdir>/update_state.csv).")
    p.add_argument("--force", action="store_true",
                   help="Ignore the 'already ran after close' skip and re-check all.")
    args = p.parse_args()
    run(outdir=args.outdir, fmt=args.format, years=args.years, overlap=args.overlap,
        tol=args.tol, workers=args.workers, limit=args.limit,
        symbols_file=args.symbols_file, state_file=args.state_file, force=args.force)


if __name__ == "__main__":
    main()
