"""
Incrementally bring the NSE 1-HOUR dataset (data/nse_hourly/) up to date.

Mirrors update_nse_daily.py but works on intraday bars (a "Datetime" column,
IST wall-clock, tz-naive once stored). Run-state lives in
data/update_state_hourly.csv:
    last_dt            - timestamp of the most recent bar on disk
    last_bar_final     - 1 if that bar's hour has fully elapsed, 0 if it was an
                         in-progress (current-hour) bar
    ran_after_close    - 1 if the last run happened after market close
    last_run           - ISO timestamp (IST) of the last run

Per-symbol decision (same philosophy as the daily updater):
  * Already refreshed AFTER CLOSE today -> SKIP (no network call).
  * New/partial bars -> fetch the recent window, OVERWRITE the in-progress bar
    and APPEND any genuinely new bars. NO full re-download.
  * A CONFIRMED past bar's Close mismatches the fresh pull (beyond --tol) ->
    corporate action -> FULL re-download of the trailing window.
  * Missing on disk, or last bar older than the window -> full download.

Usually invoked via update_data.py (updates daily + hourly in one run), but can
be run standalone:
    conda run -n STOCK python update_nse_hourly.py
    conda run -n STOCK python update_nse_hourly.py --days 30 --tol 0.001 --workers 8
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

DTCOL = "Datetime"
COLS = [DTCOL, "Symbol", "Close", "High", "Low", "Open", "Volume"]

IST = timezone(timedelta(hours=5, minutes=30))
MARKET_CLOSE = dtime(15, 40)  # 15:30 close + ~10 min buffer


# --------------------------------------------------------------------------- #
# State helpers
# --------------------------------------------------------------------------- #
def load_state(path: str) -> dict:
    """Return {symbol: {last_dt, last_bar_final, ran_after_close, last_run_date}}."""
    if not os.path.exists(path):
        return {}
    df = pd.read_csv(path)
    state = {}
    for _, r in df.iterrows():
        try:
            last_dt = pd.to_datetime(r["last_dt"])
        except Exception:  # noqa: BLE001
            continue
        try:
            last_run_date = pd.Timestamp(pd.to_datetime(r["last_run"]).date())
        except Exception:  # noqa: BLE001
            last_run_date = pd.NaT
        state[str(r["SYMBOL"]).strip()] = {
            "last_dt": last_dt,
            "last_bar_final": bool(int(r.get("last_bar_final", 0))),
            "ran_after_close": bool(int(r.get("ran_after_close", 0))),
            "last_run_date": last_run_date,
        }
    return state


def is_final(last_dt: pd.Timestamp, now_naive: pd.Timestamp) -> bool:
    """A bar is final once its hour has fully elapsed (older than ~1h)."""
    return last_dt <= now_naive - pd.Timedelta(hours=1)


def make_record(symbol, last_dt, now_naive, after_close, now_iso):
    return {
        "SYMBOL": symbol,
        "last_dt": pd.Timestamp(last_dt).strftime("%Y-%m-%d %H:%M:%S"),
        "last_bar_final": int(is_final(last_dt, now_naive)),
        "ran_after_close": int(after_close),
        "last_run": now_iso,
    }


# --------------------------------------------------------------------------- #
# I/O helpers
# --------------------------------------------------------------------------- #
def _norm_dt(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize the Datetime column to tz-naive IST wall-clock and sort."""
    s = pd.to_datetime(df[DTCOL])
    if getattr(s.dt, "tz", None) is not None:
        s = s.dt.tz_convert("Asia/Kolkata").dt.tz_localize(None)
    df = df.copy()
    df[DTCOL] = s
    return df.sort_values(DTCOL).reset_index(drop=True)


def _read_existing(path: str, fmt: str) -> pd.DataFrame:
    df = pd.read_parquet(path) if fmt == "parquet" else pd.read_csv(path)
    return _norm_dt(df)


def _fetch(yf_symbol: str, start, end) -> pd.DataFrame:
    df = yf.download(yf_symbol, start=start, end=end, interval="1h",
                     auto_adjust=True, progress=False, threads=False)
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.reset_index()
    # yfinance names the intraday index "Datetime" (sometimes "index"); unify it.
    if DTCOL not in df.columns:
        df = df.rename(columns={df.columns[0]: DTCOL})
    return _norm_dt(df)


def _write(df: pd.DataFrame, path: str, fmt: str):
    keep = [c for c in COLS if c in df.columns]
    if fmt == "parquet":
        df[keep].to_parquet(path, index=False)
    else:
        df[keep].to_csv(path, index=False)


# --------------------------------------------------------------------------- #
# Per-symbol update
# --------------------------------------------------------------------------- #
def update_one(symbol, outdir, fmt, days, overlap_hours, tol,
               now_naive, today, after_close, now_iso, prev, retries=3):
    """Returns (symbol, status, info, state_record). status in:
       skip_recent / new / uptodate / appended / updated / resync / fail."""
    ext = "parquet" if fmt == "parquet" else "csv"
    path = os.path.join(outdir, f"{symbol}.{ext}")
    yf_symbol = f"{symbol}.NS"
    period = f"{days}d"

    def _full(reason_status, info_override=None):
        _, st, info = download_one(symbol, 0, outdir, fmt, retries, True, "1h", period)
        if st != "ok":
            return symbol, "fail", info, None
        ld = _read_existing(path, fmt)[DTCOL].max()
        return symbol, reason_status, (info_override or info), make_record(
            symbol, ld, now_naive, after_close, now_iso)

    # --- Fast path: already refreshed after close today -> nothing new exists.
    if (prev and prev["ran_after_close"] and prev["last_bar_final"]
            and prev["last_run_date"] == today
            and pd.Timestamp(prev["last_dt"]).normalize() == today):
        rec = make_record(symbol, prev["last_dt"], now_naive, after_close, now_iso)
        return symbol, "skip_recent", 0, rec

    # --- Missing/empty on disk -> full download.
    if not (os.path.exists(path) and os.path.getsize(path) > 0):
        return _full("new")
    try:
        old = _read_existing(path, fmt)
    except Exception as e:  # noqa: BLE001
        return symbol, "fail", f"read error: {e}", None
    if old.empty:
        return _full("new")

    last_dt = old[DTCOL].max()

    # Last bar older than the trailing window -> can't stitch intraday -> resync.
    if last_dt < now_naive - pd.Timedelta(days=days):
        return _full("resync")

    start = (last_dt - pd.Timedelta(hours=overlap_hours)).normalize()
    end = today + pd.Timedelta(days=1)            # yfinance 'end' is exclusive

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
        return symbol, "uptodate", 0, make_record(
            symbol, last_dt, now_naive, after_close, now_iso)

    old_dts, fresh_dts = set(old[DTCOL]), set(fresh[DTCOL])

    # Exclude bars we must not use to detect corporate actions: the newest fresh
    # bar (may be in-progress), any bar in the current hour, and the previously
    # in-progress last bar on disk.
    newest_fresh = max(fresh_dts)
    cur_hour = now_naive.floor("h")
    exclude = {newest_fresh}
    if prev and not prev["last_bar_final"]:
        exclude.add(pd.Timestamp(prev["last_dt"]))
    cmp_dts = sorted(d for d in (old_dts & fresh_dts)
                     if d not in exclude and d < cur_hour)

    if cmp_dts:
        o = old.set_index(DTCOL).loc[cmp_dts, "Close"].astype(float)
        f = fresh.set_index(DTCOL).loc[cmp_dts, "Close"].astype(float)
        rel = (o - f).abs() / o.replace(0, pd.NA)
        max_rel = float(rel.max()) if len(rel) else 0.0
        if pd.notna(max_rel) and max_rel > tol:
            return _full("resync", f"max_overlap_diff={max_rel:.4f}")
    elif not (old_dts & fresh_dts):
        return _full("resync", "no overlap")   # long gap -> re-sync to be safe

    # --- Merge: fresh wins on shared timestamps, brings in new bars.
    fresh = fresh.assign(Symbol=symbol)
    combined = (pd.concat([old, fresh], ignore_index=True)
                .drop_duplicates(subset=DTCOL, keep="last")
                .sort_values(DTCOL)
                .reset_index(drop=True))
    new_last = combined[DTCOL].max()
    rec = make_record(symbol, new_last, now_naive, after_close, now_iso)

    if len(combined) > len(old):
        _write(combined, path, fmt)
        return symbol, "appended", len(combined) - len(old), rec

    # Same set of timestamps -> did the latest (partial) bar's value change?
    if newest_fresh in old_dts:
        oc = float(old.loc[old[DTCOL] == newest_fresh, "Close"].iloc[0])
        fc = float(fresh.loc[fresh[DTCOL] == newest_fresh, "Close"].iloc[0])
        if oc != 0 and abs(oc - fc) / oc > 1e-9:
            _write(combined, path, fmt)
            return symbol, "updated", 1, rec

    return symbol, "uptodate", 0, rec


# --------------------------------------------------------------------------- #
def run(outdir="stock/data/nse_hourly", fmt="csv", days=30, overlap_hours=6, tol=0.001,
        workers=8, limit=0, symbols_file="", state_file="", force=False):
    """Incrementally update the hourly dataset. Returns the status-count dict.
    Missing files are downloaded on the fly, so this also bootstraps the dataset."""
    os.makedirs(outdir, exist_ok=True)
    base = os.path.dirname(outdir) or "."
    state_path = state_file or os.path.join(base, "update_state_hourly.csv")

    if symbols_file:
        symbols = pd.read_csv(symbols_file)["SYMBOL"].astype(str).str.strip().tolist()
    else:
        cache = os.path.join(base, "nse_equity_list.csv")
        symbols = get_nse_symbols(cache)["SYMBOL"].astype(str).str.strip().tolist()
    if limit:
        symbols = symbols[:limit]

    now_ist = datetime.now(IST)
    now_naive = pd.Timestamp(now_ist).tz_localize(None)   # IST wall-clock, tz-naive
    today = pd.Timestamp(now_ist.date())
    after_close = now_ist.time() >= MARKET_CLOSE
    now_iso = now_ist.isoformat(timespec="seconds")

    prev_state = {} if force else load_state(state_path)

    total = len(symbols)
    print(f"Updating {total} symbols (1h, {days}d window) @ {now_iso} "
          f"(after_close={after_close}, tol={tol}, {workers} workers)\n")

    counts = {}
    failures, resyncs = [], []
    new_state = dict(prev_state)
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(update_one, s, outdir, fmt, days, overlap_hours, tol,
                          now_naive, today, after_close, now_iso,
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

    if new_state:
        pd.DataFrame(list(new_state.values()))[
            ["SYMBOL", "last_dt", "last_bar_final", "ran_after_close", "last_run"]
        ].sort_values("SYMBOL").to_csv(state_path, index=False)

    if resyncs:
        pd.DataFrame(resyncs, columns=["SYMBOL", "info"]).to_csv(
            os.path.join(base, "resynced_hourly.csv"), index=False)
    if failures:
        pd.DataFrame(failures, columns=["SYMBOL", "error"]).to_csv(
            os.path.join(base, "update_failures_hourly.csv"), index=False)

    dt = time.time() - t0
    print(f"\nDone in {dt/60:.1f} min. {counts}")
    print(f"State saved to {state_path}")
    if resyncs:
        print(f"{len(resyncs)} re-synced (corporate action) -> resynced_hourly.csv")
    if failures:
        print(f"{len(failures)} failures -> update_failures_hourly.csv (re-run to retry).")
    return counts


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="Incrementally update NSE 1-hour data.")
    p.add_argument("--outdir", default="stock/data/nse_hourly")
    p.add_argument("--format", choices=["csv", "parquet"], default="csv")
    p.add_argument("--days", type=int, default=30,
                   help="Trailing window (days) for full downloads / re-syncs.")
    p.add_argument("--overlap", type=int, default=6,
                   help="Overlap hours re-fetched before the last stored bar.")
    p.add_argument("--tol", type=float, default=0.001,
                   help="Max relative Close diff on confirmed bars before treating "
                        "it as a corporate action (default 0.1%%).")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--symbols-file", default="")
    p.add_argument("--state-file", default="")
    p.add_argument("--force", action="store_true",
                   help="Ignore the 'already ran after close' skip and re-check all.")
    args = p.parse_args()
    run(outdir=args.outdir, fmt=args.format, days=args.days, overlap_hours=args.overlap,
        tol=args.tol, workers=args.workers, limit=args.limit,
        symbols_file=args.symbols_file, state_file=args.state_file, force=args.force)


if __name__ == "__main__":
    main()
