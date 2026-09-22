"""
Screen NSE index stocks that are trading NEAR a key support/resistance level,
working from the BIGGEST timeframe down and widening the universe until enough
matches are found.

Cascade (stops as soon as --target stocks are collected):
    universes : Nifty 50  ->  Nifty 100  ->  Nifty 200
    timeframes:    2Y  ->  1Y  ->  Monthly  ->  Weekly      (big label first)

A stock is "near" a label when its latest close is within --tol (default 2%) of
the nearest still-active level on that timeframe -- EITHER the resistance above
or the support below (whichever is closer). Levels use the same pivot logic as
find_labels.py (with the unbroken-extreme fallback, so 1Y/2Y resolve to the
multi-year high/low). Within each (universe, timeframe) step, the closest
matches rank first.

Index constituent lists are fetched from NSE and cached under data/.

Run inside the STOCK conda env:
    conda run -n STOCK python screen_levels.py
    conda run -n STOCK python screen_levels.py --target 20 --tol 0.02
    conda run -n STOCK python screen_levels.py --tol 0.015 --save-csv
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import argparse
import io
import os

import pandas as pd
import requests

from stock.download_nse_daily import NSE_HEADERS
from utils.find_labels import (find_labels, load_daily, nearest_levels, to_2yearly,
                         to_monthly, to_weekly, to_yearly)

# Timeframe order: biggest label first. (key, label, resampler)
TIMEFRAMES = [
    ("2Y", "2-Year",  to_2yearly),
    ("1Y", "1-Year",  to_yearly),
    ("M",  "Monthly", to_monthly),
    ("W",  "Weekly",  to_weekly),
]

# Universe cascade: (display name, NSE constituent-list filename).
UNIVERSES = [
    ("Nifty 50",  "ind_nifty50list.csv"),
    ("Nifty 100", "ind_nifty100list.csv"),
    ("Nifty 200", "ind_nifty200list.csv"),
]
NSE_INDEX_BASE = "https://archives.nseindia.com/content/indices/"


# --------------------------------------------------------------------------- #
def get_index_constituents(list_file: str, base_dir: str) -> list:
    """Return the symbol list for an NSE index, fetching + caching on first use."""
    cache = os.path.join(base_dir, list_file)
    if os.path.exists(cache):
        df = pd.read_csv(cache)
    else:
        print(f"Fetching {list_file} from NSE ...")
        sess = requests.Session()
        sess.headers.update(NSE_HEADERS)
        try:                                   # prime cookies (NSE blocks cold hits)
            sess.get("https://www.nseindia.com", timeout=15)
        except requests.RequestException:
            pass
        resp = sess.get(NSE_INDEX_BASE + list_file, timeout=30)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))
        df.columns = [c.strip() for c in df.columns]
        df.to_csv(cache, index=False)
        print(f"  cached {len(df)} symbols -> {cache}")
    col = "Symbol" if "Symbol" in df.columns else df.columns[0]
    return df[col].astype(str).str.strip().tolist()


# --------------------------------------------------------------------------- #
def nearest_match(daily, kw):
    """For one stock, return {tf_key: best-level-dict-or-None} across all
    timeframes. best = {side, price, dist, formed} where dist is the |%| gap
    between the latest close and the nearest active level (either side)."""
    ref = float(daily["Close"].iloc[-1])
    out = {"ref": ref}
    for key, _label, resampler in TIMEFRAMES:
        try:
            df_tf = resampler(daily)
        except Exception:                      # noqa: BLE001 - skip unusable tf
            out[key] = None
            continue
        if df_tf.empty:
            out[key] = None
            continue
        labels = find_labels(df_tf, **kw)
        res, sup = nearest_levels(labels, df_tf, ref)
        best = None
        for lvl, side in ((res, "R"), (sup, "S")):
            if lvl is None:
                continue
            dist = abs(lvl["price"] - ref) / ref if ref else float("inf")
            if best is None or dist < best["dist"]:
                best = {"side": side, "price": float(lvl["price"]),
                        "dist": dist, "formed": lvl["formed_date"]}
        out[key] = best
    return out


def analyze_universe(symbols, indir, kw):
    """Return {symbol: nearest_match(...)} for symbols whose daily file exists."""
    res = {}
    for sym in symbols:
        try:
            daily = load_daily(indir, sym)
        except FileNotFoundError:
            continue                           # not downloaded -> silently skip
        if len(daily) < 5:
            continue
        try:
            res[sym] = nearest_match(daily, kw)
        except Exception:                      # noqa: BLE001
            continue
    return res


# --------------------------------------------------------------------------- #
def run(target=20, tol=0.02, indir="stock/data/nse_daily", base_dir="stock/data",
        left=3, right=2, big_mult=2.0, save_csv=False):
    kw = dict(left=left, right=right, big_mult=big_mult, break_tol=0.0)

    picked = []                 # ordered result rows
    chosen = set()              # symbols already picked
    scanned = set()             # symbols already analyzed (across universes)
    analysis = {}               # symbol -> nearest_match dict

    print(f"Target {target} stocks within {tol*100:.2f}% of a key level "
          f"(2Y -> 1Y -> Monthly -> Weekly; Nifty 50 -> 100 -> 200)\n")

    for uni_name, list_file in UNIVERSES:
        symbols = get_index_constituents(list_file, base_dir)
        new_syms = [s for s in symbols if s not in scanned]
        scanned.update(symbols)
        if new_syms:
            analysis.update(analyze_universe(new_syms, indir, kw))

        # Walk timeframes big -> small; only newly-added names are eligible here
        # (earlier universes already had every timeframe checked).
        for key, label, _ in TIMEFRAMES:
            cands = []
            for sym in new_syms:
                if sym in chosen or sym not in analysis:
                    continue
                m = analysis[sym].get(key)
                if m and m["dist"] <= tol:
                    cands.append((sym, m))
            cands.sort(key=lambda t: t[1]["dist"])     # closest first
            for sym, m in cands:
                if sym in chosen:
                    continue
                chosen.add(sym)
                picked.append({
                    "rank": len(picked) + 1, "symbol": sym, "universe": uni_name,
                    "timeframe": label, "side": "Resistance" if m["side"] == "R"
                    else "Support", "level": round(m["price"], 2),
                    "close": round(analysis[sym]["ref"], 2),
                    "dist_pct": round(m["dist"] * 100, 2),
                    "formed": pd.Timestamp(m["formed"]).date().isoformat(),
                })
                if len(picked) >= target:
                    break
            if len(picked) >= target:
                break
        print(f"[{uni_name}] running total: {len(picked)}/{target}")
        if len(picked) >= target:
            break

    df = pd.DataFrame(picked)
    print()
    if df.empty:
        print("No stocks found near a key level with the given tolerance.")
    else:
        cols = ["rank", "symbol", "universe", "timeframe", "side", "level",
                "close", "dist_pct", "formed"]
        print(df[cols].to_string(index=False))
        if len(picked) < target:
            print(f"\nOnly {len(picked)}/{target} found even across Nifty 200 "
                  f"at tol={tol*100:.2f}%. Loosen --tol to get more.")
        if save_csv:
            out = os.path.join(base_dir, "screen_near_levels.csv")
            df.to_csv(out, index=False)
            syms = ["NSE:NIFTY50-INDEX", "BSE:SENSEX-INDEX"] + \
                   [f"NSE:{s}-EQ" for s in df["symbol"]]
            fytxt = os.path.join(base_dir, "screen_near_levels_fyers.txt")
            with open(fytxt, "w", encoding="ascii") as f:
                f.write(",".join(syms))           # Fyers desktop watchlist (1 line)
            fycsv = os.path.join(base_dir, "screen_near_levels_fyers.csv")
            pd.DataFrame({"Symbol": syms}).to_csv(fycsv, index=False)  # Fyers web
            print(f"\nSaved -> {out}\nFyers desktop watchlist -> {fytxt}"
                  f"\nFyers web import -> {fycsv}")
    return df


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(
        description="Screen NSE index stocks trading near a key S/R level.")
    p.add_argument("--target", type=int, default=20, help="How many stocks to find.")
    p.add_argument("--tol", type=float, default=0.02,
                   help="Proximity threshold as a fraction (0.02 = 2%%). Changeable.")
    p.add_argument("--indir", default="stock/data/nse_daily")
    p.add_argument("--base-dir", default="stock/data", help="Where index lists are cached.")
    p.add_argument("--left", type=int, default=3)
    p.add_argument("--right", type=int, default=2)
    p.add_argument("--big-mult", type=float, default=2.0)
    p.add_argument("--save-csv", action="store_true")
    args = p.parse_args()
    run(target=args.target, tol=args.tol, indir=args.indir, base_dir=args.base_dir,
        left=args.left, right=args.right, big_mult=args.big_mult,
        save_csv=args.save_csv)


if __name__ == "__main__":
    main()
