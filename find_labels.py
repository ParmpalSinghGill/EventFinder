"""
Find support/resistance "labels" (pivot levels) on daily, weekly AND monthly
candles, and plot them over the candlesticks so the rules can be eyeballed.

By default this picks exactly 6 key levels bracketing the current price -- one
ABOVE and one BELOW the last close for each timeframe -- searching the full
available history (and falling back to the data extreme) so a level is always
found. They are drawn on the daily chart colour-coded by timeframe:
monthly = black, weekly = red, daily = blue (resistance solid, support dashed).

RULES (all tunable via CLI flags):

  Pivot HIGH (resistance / upper level) at candle i, price = High[i]:
     * standard : >=3 consecutive LOWER-high candles on one side AND
                  >=2 consecutive LOWER-high candles on the other side, OR
     * big-body : >=2 lower-high candles on one side AND the adjacent candle on
                  the other side is a VERY BIG body (body >= big_mult * average
                  body) and is itself lower.
  Pivot LOW (support / lower level): mirror image using Low[] and HIGHER-low
  candles.

  CANCELLATION: once formed, a resistance at price P is cancelled the first time
  a later candle's High > P (price passes up through it); a support is cancelled
  when a later candle's Low < P. Level selection prefers still-active (uncrossed)
  pivots, so the drawn line is never crossed by a candle between its formation
  date and the right edge.

Run inside the STOCK conda env:
    conda run -n STOCK python find_labels.py RELIANCE TCS
    conda run -n STOCK python find_labels.py INFY --left 3 --right 2 --big-mult 2
"""

import argparse
import glob
import os
from functools import partial
from multiprocessing import Pool

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")            # headless / multiprocessing-safe rendering
import mplfinance as mpf
import matplotlib.lines as mlines
import matplotlib.pyplot as plt

AGG = {"Open": "first", "High": "max", "Low": "min", "Close": "last", "Volume": "sum"}


# --------------------------------------------------------------------------- #
def load_daily(indir: str, symbol: str) -> pd.DataFrame:
    path = os.path.join(indir, f"{symbol}.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    df = pd.read_csv(path)
    df["Date"] = pd.to_datetime(df["Date"])
    df = df.sort_values("Date").set_index("Date")
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def to_weekly(daily: pd.DataFrame) -> pd.DataFrame:
    """Build weekly OHLCV from daily (week ending Friday)."""
    return daily.resample("W-FRI").agg(AGG).dropna()


def to_monthly(daily: pd.DataFrame) -> pd.DataFrame:
    """Build monthly OHLCV from daily (calendar month end)."""
    return _resample(daily, ("ME", "M"))


def to_yearly(daily: pd.DataFrame) -> pd.DataFrame:
    """Build yearly (1Y) OHLCV from daily (calendar year end)."""
    return _resample(daily, ("YE", "A", "Y"))


def to_2yearly(daily: pd.DataFrame) -> pd.DataFrame:
    """Build 2-yearly (2Y) OHLCV from daily."""
    return _resample(daily, ("2YE", "2A", "2Y"))


def _resample(daily: pd.DataFrame, rules) -> pd.DataFrame:
    """Resample with the first pandas offset alias that this version accepts
    (offset spellings changed in pandas 2.2: 'ME'/'YE' vs old 'M'/'A')."""
    last_err = None
    for rule in rules:
        try:
            return daily.resample(rule).agg(AGG).dropna()
        except (ValueError, KeyError) as e:  # unknown alias on this pandas
            last_err = e
    raise last_err


# --------------------------------------------------------------------------- #
def find_labels(df: pd.DataFrame, left: int = 3, right: int = 2,
                big_mult: float = 2.0, break_tol: float = 0.0,
                avg_window: int = 20) -> list:
    """Return a list of label dicts:
       {type, price, idx, formed_date, canceled, cancel_idx, cancel_date}."""
    n = len(df)
    if n < 5:
        return []
    highs = df["High"].to_numpy(float)
    lows = df["Low"].to_numpy(float)
    body = (df["Close"] - df["Open"]).abs().to_numpy(float)
    avg_body = (pd.Series(body).rolling(avg_window, min_periods=3).mean()
                .bfill().to_numpy(float))
    dates = df.index

    def consec(arr, i, step, cmp_lower):
        """Count consecutive neighbours strictly beyond arr[i] in `step`
        direction. cmp_lower=True counts arr[j] < arr[i] (for highs)."""
        c, j = 0, i + step
        while 0 <= j < n:
            ok = arr[j] < arr[i] if cmp_lower else arr[j] > arr[i]
            if not ok:
                break
            c += 1
            j += step
        return c

    def big(i, step, arr, cmp_lower):
        j = i + step
        if not (0 <= j < n):
            return False
        beyond = arr[j] < arr[i] if cmp_lower else arr[j] > arr[i]
        return beyond and body[j] >= big_mult * avg_body[j]

    labels = []
    for i in range(n):
        # ---- pivot HIGH (resistance) ----
        lc = consec(highs, i, -1, True)
        rc = consec(highs, i, +1, True)
        normal = (lc >= left and rc >= right) or (lc >= right and rc >= left)
        big_ok = (lc >= right and big(i, +1, highs, True)) or \
                 (rc >= right and big(i, -1, highs, True))
        if normal or big_ok:
            labels.append(_make(df, dates, i, highs[i], "resistance"))

        # ---- pivot LOW (support) ----
        lc = consec(lows, i, -1, False)
        rc = consec(lows, i, +1, False)
        normal = (lc >= left and rc >= right) or (lc >= right and rc >= left)
        big_ok = (lc >= right and big(i, +1, lows, False)) or \
                 (rc >= right and big(i, -1, lows, False))
        if normal or big_ok:
            labels.append(_make(df, dates, i, lows[i], "support"))

    # ---- cancellation: first later candle that passes through the level ----
    for lb in labels:
        i, P = lb["idx"], lb["price"]
        if lb["type"] == "resistance":
            beyond = highs[i + 1:] > P * (1 + break_tol)
        else:
            beyond = lows[i + 1:] < P * (1 - break_tol)
        hit = np.argmax(beyond) if beyond.any() else -1
        if hit >= 0:
            k = i + 1 + hit
            lb["canceled"] = True
            lb["cancel_idx"] = k
            lb["cancel_date"] = dates[k]
    return labels


def _make(df, dates, i, price, kind):
    return {"type": kind, "price": float(price), "idx": i,
            "formed_date": dates[i], "canceled": False,
            "cancel_idx": None, "cancel_date": None}


# --------------------------------------------------------------------------- #
# key, legend name, color, linestyle, linewidth
#   monthly = black, weekly = red, daily = blue;
#   resistance (above price) solid, support (below price) dashed.
LEVEL_SPECS = [
    ("monthly_res", "Monthly R", "#000000", "-",  2.1),
    ("weekly_res",  "Weekly R",  "#d62728", "-",  1.7),
    ("daily_res",   "Daily R",   "#1f77b4", "-",  1.3),
    ("daily_sup",   "Daily S",   "#1f77b4", "--", 1.3),
    ("weekly_sup",  "Weekly S",  "#d62728", "--", 1.7),
    ("monthly_sup", "Monthly S", "#000000", "--", 2.1),
]


def nearest_levels(labels, df, ref):
    """Nearest level above (resistance) and below (support) `ref`, searching the
    FULL history we have. Only still-ACTIVE (uncrossed) pivots qualify -- a
    cancelled resistance is one price has already traded above, so it is not
    resistance (and likewise for support), and must never be drawn as a level.
    If no active pivot exists on a side, fall back to the data extreme
    (highest High / lowest Low), which is by definition unbroken. Returns None
    for a side only when price is at the all-time high/low (nothing beyond it)."""
    highs = df["High"].to_numpy(float)
    lows = df["Low"].to_numpy(float)
    dates = df.index

    def pick(kind, above):
        cands = [l for l in labels if l["type"] == kind and not l["canceled"]
                 and (l["price"] > ref if above else l["price"] < ref)]
        if cands:
            return (min(cands, key=lambda l: l["price"]) if above
                    else max(cands, key=lambda l: l["price"]))
        # no unbroken pivot on this side -> the data extreme (an unbroken ceiling
        # / floor) is the only honest level we can show.
        if above:
            mask = highs > ref
            if not mask.any():
                return None
            j = int(np.argmax(np.where(mask, highs, -np.inf)))
            return _make(df, dates, j, highs[j], "resistance")
        mask = lows < ref
        if not mask.any():
            return None
        j = int(np.argmin(np.where(mask, lows, np.inf)))
        return _make(df, dates, j, lows[j], "support")

    return pick("resistance", True), pick("support", False)


def select_key_levels(frames, ref):
    """`frames` maps timeframe name -> (df, labels). Returns one resistance
    (above) and one support (below) per timeframe: keys '<tf>_res'/'<tf>_sup'."""
    out = {}
    for tf, (df, labels) in frames.items():
        res, sup = nearest_levels(labels, df, ref)
        out[f"{tf}_res"], out[f"{tf}_sup"] = res, sup
    return out


def plot_key(view, levels, ref, title, outpath, last=0):
    """Daily candles + the 6 bracketing levels (daily/weekly/monthly, one above
    and one below price each). Each level is drawn from its formation date to the
    right edge, so the drawn line is never crossed by any candle in between."""
    v = view.iloc[-last:] if last and last < len(view) else view
    n = len(v)
    pad = max(15, int(n * 0.12))             # blank candles of space on the right
    specs = LEVEL_SPECS

    fig, ax = mpf.plot(v, type="candle", style="yahoo",
                       title=f"{title}  (ref close {ref:.1f})",
                       volume=False, figratio=(16, 8), figscale=1.2,
                       tight_layout=True, datetime_format="%Y-%m", returnfig=True)
    a0 = ax[0]
    a0.set_xlim(-1, n - 1 + pad)             # add right-side breathing room
    x_end = n - 1 + pad                       # extend level lines into the space

    handles, names = [], []
    for key, name, color, style, width in specs:
        lb = levels.get(key)
        if not lb:
            continue
        # x position where this level first formed (clamped into the window)
        pos = int(v.index.searchsorted(lb["formed_date"]))
        pos = min(max(pos, 0), n - 1)
        a0.plot([pos, x_end], [lb["price"], lb["price"]],
                color=color, linestyle=style, lw=width, alpha=0.9)
        a0.text(x_end, lb["price"], f" {lb['price']:.1f}", color=color,
                va="center", fontsize=8, fontweight="bold")
        handles.append(mlines.Line2D([], [], color=color, linestyle=style, lw=width))
        names.append(f"{name}: {lb['price']:.1f}  ({lb['formed_date'].date()})")

    if handles:
        a0.legend(handles, names, loc="upper left", fontsize=9, framealpha=0.9)
    fig.savefig(outpath, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return len(handles)


# --------------------------------------------------------------------------- #
def process_symbol(sym, indir, outdir, kw, last_daily, save_csv, split=False):
    """Build the 6 key levels for one symbol, write its plot (+optional CSVs),
    and return a one-line status string (safe to run in a worker process).
    When split is set, also write separate daily/weekly/monthly charts, each
    showing just that timeframe's 2 key levels (1 above + 1 below) -> 4 graphs."""
    try:
        daily = load_daily(indir, sym)
    except FileNotFoundError:
        return f"[{sym}] not found in {indir} -- skipping."
    try:
        weekly = to_weekly(daily)
        monthly = to_monthly(daily)

        dl = find_labels(daily, **kw)
        wl = find_labels(weekly, **kw)
        ml = find_labels(monthly, **kw)

        ref = float(daily["Close"].iloc[-1])
        frames = {"daily": (daily, dl), "weekly": (weekly, wl),
                  "monthly": (monthly, ml)}
        lv = select_key_levels(frames, ref)

        def show(k):
            return f"{lv[k]['price']:.1f}" if lv[k] else "-"

        cp = os.path.join(outdir, f"{sym}_levels.png")
        plot_key(daily, lv, ref, f"{sym} key levels", cp, last=last_daily)

        if split:
            for name, df_tf, last in (("daily", daily, last_daily),
                                      ("weekly", weekly, 200),
                                      ("monthly", monthly, 0)):
                sub = {f"{name}_res": lv[f"{name}_res"],
                       f"{name}_sup": lv[f"{name}_sup"]}
                plot_key(df_tf, sub, ref, f"{sym} {name.title()}",
                         os.path.join(outdir, f"{sym}_{name}.png"), last=last)

        if save_csv:
            for name, lbls in (("daily", dl), ("weekly", wl), ("monthly", ml)):
                pd.DataFrame(lbls).to_csv(
                    os.path.join(outdir, f"{sym}_{name}_labels.csv"), index=False)

        tail = f"-> {outdir} (4 graphs)" if split else f"-> {cp}"
        return (f"[{sym}] ref={ref:.1f} | above  M={show('monthly_res')} "
                f"W={show('weekly_res')} D={show('daily_res')} | below  "
                f"M={show('monthly_sup')} W={show('weekly_sup')} "
                f"D={show('daily_sup')} {tail}")
    except Exception as e:                       # one bad symbol mustn't kill the batch
        return f"[{sym}] ERROR: {type(e).__name__}: {e}"


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="Find & plot S/R labels on candles.")
    p.add_argument("symbols", nargs="*", default=["RELIANCE", "TCS"],
                   help="NSE symbols (default: RELIANCE TCS).")
    p.add_argument("--indir", default="data/nse_daily")
    p.add_argument("--outdir", default="data/plots")
    p.add_argument("--left", type=int, default=3)
    p.add_argument("--right", type=int, default=2)
    p.add_argument("--big-mult", type=float, default=2.0)
    p.add_argument("--break-tol", type=float, default=0.0,
                   help="Fractional slack before a level counts as broken.")
    p.add_argument("--last-daily", type=int, default=300,
                   help="Candles shown in daily plot (0 = all). Labels use full history.")
    p.add_argument("--save-csv", action="store_true",
                   help="Also write the label table to CSV.")
    p.add_argument("--all", action="store_true",
                   help="Process every {SYMBOL}.csv in --indir (ignores symbols).")
    p.add_argument("--split", "--all-labels", dest="split", action="store_true",
                   help="Also write separate daily/weekly/monthly charts, each "
                        "showing just that timeframe's 2 key levels "
                        "(4 graphs per symbol instead of 1).")
    p.add_argument("-j", "--jobs", type=int, default=os.cpu_count(),
                   help="Parallel worker processes (default: all CPU cores).")
    args = p.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    if args.all:
        symbols = sorted(os.path.splitext(os.path.basename(f))[0]
                         for f in glob.glob(os.path.join(args.indir, "*.csv")))
    else:
        symbols = args.symbols or ["RELIANCE", "TCS"]

    kw = dict(left=args.left, right=args.right,
              big_mult=args.big_mult, break_tol=args.break_tol)
    work = partial(process_symbol, indir=args.indir, outdir=args.outdir,
                   kw=kw, last_daily=args.last_daily, save_csv=args.save_csv,
                   split=args.split)

    jobs = max(1, min(args.jobs, len(symbols)))
    n = len(symbols)
    print(f"Processing {n} symbol(s) with {jobs} worker(s) ...")

    done = 0
    if jobs == 1:
        for sym in symbols:
            print(f"({done + 1}/{n}) {work(sym)}")
            done += 1
    else:
        with Pool(jobs) as pool:
            for msg in pool.imap_unordered(work, symbols):
                done += 1
                print(f"({done}/{n}) {msg}")
    print(f"Done: {done}/{n} symbols.")


if __name__ == "__main__":
    main()
