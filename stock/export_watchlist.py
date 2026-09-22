"""
Write a date-stamped Fyers watchlist from the current screener list into
data/screener_output/exports/, then open that folder.

Triggered by the "Save dated file to folder" button in latest.html (via the
eventfinder://export protocol), and runnable by hand:
    conda run -n STOCK python export_watchlist.py
"""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import os
from datetime import datetime

import pandas as pd
import yaml

import stock.watchlist_utils as watchlist_utils

BASE = str(_ROOT)


def _abs(p):
    return p if os.path.isabs(p) else os.path.join(BASE, p)


def main():
    outdir = _abs("stock/data/screener_output")
    prefix = []
    export_dir = watchlist_utils.get_export_dir()
    cfg_path = os.path.join(BASE, "stock", "config.yml")
    if os.path.exists(cfg_path):
        with open(cfg_path, encoding="utf-8") as f:
            out = yaml.safe_load(f).get("output", {})
        outdir = _abs(out.get("dir", outdir))
        prefix = out.get("watchlist_prefix", []) or []

    latest = os.path.join(outdir, "latest.csv")
    if not os.path.exists(latest):
        print(f"No list yet at {latest} -- run the screener first.")
        return
    df = pd.read_csv(latest)
    syms = list(prefix) + ([f"NSE:{s}-EQ" for s in df["symbol"]] if not df.empty else [])

    os.makedirs(export_dir, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    txt = os.path.join(export_dir, f"fyers_{stamp}.txt")
    csv = os.path.join(export_dir, f"fyers_{stamp}.csv")
    with open(txt, "w", encoding="ascii") as f:
        f.write(",".join(syms))                       # desktop watchlist (1 line)
    with open(csv, "w", encoding="ascii") as f:
        f.write("Symbol\n" + "\n".join(syms))          # web import
    # also refresh the stable latest_fyers.* in the same folder
    with open(os.path.join(export_dir, "latest_fyers.txt"), "w", encoding="ascii") as f:
        f.write(",".join(syms))
    with open(os.path.join(export_dir, "latest_fyers.csv"), "w", encoding="ascii") as f:
        f.write("Symbol\n" + "\n".join(syms))
    
    # Also write to ~/Downloads/Watchlist and clean up
    watchlist_utils.sync_and_clean_watchlist("latest_fyers.txt", ",".join(syms))

    print(f"Exported {len(syms)} symbols ->\n  {txt}\n  {csv}")
    try:
        os.startfile(export_dir)                        # show the folder
    except Exception:                                  # noqa: BLE001
        pass


if __name__ == "__main__":
    main()
