"""
Replay last 7 days of CoinDCX XAUUSDT events and plot each hit.

For every triggered label, write one PNG with two stacked charts:
  1. Daily candles — the liquidity level (S/R) and the source candle that formed it
  2. 1-minute candles around the trigger — same level, with the trigger candle boxed
"""

import glob
import os
from datetime import timedelta

import matplotlib.pyplot as plt
import mplfinance as mpf
import pandas as pd
from matplotlib.patches import Rectangle

from coindcx_gold import DAILY_CSV, drop_weekend_bars, fetch_daily, fetch_minutes
from find_labels import find_labels, nearest_levels
from xauusd_event_finder import TIMEFRAMES, event_settings

OUT_DIR = os.path.join("data", "gold_xauusd", "event_charts")
REPLAY_HOURS = 7 * 24 + 12  # 7 days + buffer
IST = "Asia/Kolkata"

STYLE = mpf.make_mpf_style(
    base_mpf_style="nightclouds",
    marketcolors=mpf.make_marketcolors(
        up="#2ecc71", down="#e74c3c", edge="inherit", wick="inherit", volume="#5d6d7e"
    ),
    gridstyle=":",
    facecolor="#121721",
    figcolor="#0b0e14",
    y_on_right=False,
)

LEVEL_COLOR = "#f1c40f"
SOURCE_COLOR = "#3498db"
TRIGGER_COLOR = "#e67e22"
BAND_COLOR = "#f39c12"


def load_daily() -> pd.DataFrame:
    df = fetch_daily()
    if df.empty and os.path.exists(DAILY_CSV):
        df = pd.read_csv(DAILY_CSV)
        df["Date"] = pd.to_datetime(df["Date"])
    df["Date"] = pd.to_datetime(df["Date"])
    if df["Date"].dt.tz is not None:
        df["Date"] = df["Date"].dt.tz_convert("UTC").dt.tz_localize(None)
    df = df.sort_values("Date").set_index("Date")
    df = drop_weekend_bars(df)
    return df[["Open", "High", "Low", "Close", "Volume"]].dropna()


def load_minutes() -> pd.DataFrame:
    print(f"Downloading CoinDCX B-XAU_USDT 1-minute bars ({REPLAY_HOURS}h) ...")
    raw = fetch_minutes(hours=REPLAY_HOURS)
    if raw.empty:
        return raw
    raw = raw.copy()
    raw["Datetime"] = pd.to_datetime(raw["Datetime"], utc=True)
    raw = raw.sort_values("Datetime").set_index("Datetime")[
        ["Open", "High", "Low", "Close", "Volume"]
    ].dropna(subset=["Close"])
    return drop_weekend_bars(raw)


def prepare_day_pivots(df_hist: pd.DataFrame) -> dict:
    work = df_hist.copy()
    if work.index.tz is not None:
        work.index = work.index.tz_convert("UTC").tz_localize(None)
    frames = {}
    for tf_key, tf_label, resampler in TIMEFRAMES:
        try:
            df_tf = resampler(work)
        except Exception:
            continue
        if df_tf.empty or len(df_tf) < 3:
            continue
        frames[tf_key] = {
            "label": tf_label,
            "df": df_tf,
            "labels": find_labels(df_tf, left=3, right=2, big_mult=2.0, break_tol=0.0),
        }
    prev_day = work.iloc[-1]
    frames["_pdh"] = float(prev_day["High"])
    frames["_pdl"] = float(prev_day["Low"])
    frames["_prev_date"] = work.index[-1]
    return frames


def _source_meta(date, field: str, tf_name: str) -> dict:
    if date is None or (isinstance(date, float) and pd.isna(date)):
        return {
            "source_date": "",
            "source_field": field,
            "source_tf": tf_name,
            "source": f"CoinDCX {tf_name} {field}",
        }
    d = pd.Timestamp(date)
    return {
        "source_date": d.strftime("%Y-%m-%d"),
        "source_field": field,
        "source_tf": tf_name,
        "source": f"CoinDCX {tf_name} {field} {d.strftime('%a %d %b %Y')}",
    }


def compute_levels_from_pivots(frames: dict, current_price: float, today_high: float, today_low: float) -> list:
    pd_tol = event_settings()["prev_day_hierarchy_tol"]
    higher_tf_levels = []
    daily_levels = []
    for tf_key, _tf_label, _ in TIMEFRAMES:
        packed = frames.get(tf_key)
        if not packed:
            continue
        res_lvl, sup_lvl = nearest_levels(packed["labels"], packed["df"], current_price)
        if res_lvl is not None:
            price = float(res_lvl["price"])
            if today_high < price:
                lvl = {"id": f"{tf_key}_R_{price:.2f}", "timeframe": packed["label"],
                       "name": f"{packed['label']} Resistance", "type": "resistance", "price": price}
                lvl.update(_source_meta(res_lvl.get("formed_date"), "High", packed["label"]))
                (higher_tf_levels if tf_key in ["2Y", "1Y", "M", "W"] else daily_levels).append(lvl)
        if sup_lvl is not None:
            price = float(sup_lvl["price"])
            if today_low > price:
                lvl = {"id": f"{tf_key}_S_{price:.2f}", "timeframe": packed["label"],
                       "name": f"{packed['label']} Support", "type": "support", "price": price}
                lvl.update(_source_meta(sup_lvl.get("formed_date"), "Low", packed["label"]))
                (higher_tf_levels if tf_key in ["2Y", "1Y", "M", "W"] else daily_levels).append(lvl)

    pdh, pdl = frames["_pdh"], frames["_pdl"]
    prev_date = frames["_prev_date"]
    candidate_prev_day = []
    if today_high < pdh:
        lvl = {
            "id": f"PDH_{pdh:.2f}", "timeframe": "PrevDay",
            "name": "Prev Day High (PDH)", "type": "resistance", "price": pdh,
        }
        lvl.update(_source_meta(prev_date, "High", "PrevDay"))
        candidate_prev_day.append(lvl)
    if today_low > pdl:
        lvl = {
            "id": f"PDL_{pdl:.2f}", "timeframe": "PrevDay",
            "name": "Prev Day Low (PDL)", "type": "support", "price": pdl,
        }
        lvl.update(_source_meta(prev_date, "Low", "PrevDay"))
        candidate_prev_day.append(lvl)
    valid_prev_day = []
    for pd_lvl in candidate_prev_day:
        pd_price = pd_lvl["price"]
        if not any(abs(htf["price"] - pd_price) / pd_price <= pd_tol for htf in higher_tf_levels):
            valid_prev_day.append(pd_lvl)
    return higher_tf_levels + daily_levels + valid_prev_day


def replay_last_7_days(daily: pd.DataFrame, minutes_utc: pd.DataFrame) -> list:
    """Walk CoinDCX 1-minute closes. Returns event dicts (UTC ts + IST fields)."""
    if minutes_utc.empty:
        return []
    cutoff = minutes_utc.index.max() - pd.Timedelta(days=7)
    bars = minutes_utc.loc[minutes_utc.index >= cutoff].copy()
    print(f"Replaying {len(bars)} x 1-min CoinDCX bars  {bars.index.min()} -> {bars.index.max()} UTC")
    s = event_settings()
    trigger_tol = s["gold_trigger_tol"]
    retrigger_dist = s["watch_exit_dist"]

    state = {}
    events = []
    last_day = None
    pivots = None
    today_high = today_low = None

    for i, (ts, row) in enumerate(bars.iterrows()):
        ts_ist = ts.tz_convert(IST)
        if int(ts_ist.dayofweek) >= 5:
            continue
        px = float(row["Close"])
        day = pd.Timestamp(ts.tz_convert("UTC").date())
        if int(day.dayofweek) >= 5:
            continue

        if last_day != day:
            hist = daily.loc[daily.index < day]
            if hist.empty:
                continue
            pivots = prepare_day_pivots(hist)
            today_high = float(row["High"])
            today_low = float(row["Low"])
            last_day = day
            print(f"  day {day.date()}  PDH={pivots['_pdh']:.2f}  PDL={pivots['_pdl']:.2f}")
        else:
            today_high = max(today_high, float(row["High"]))
            today_low = min(today_low, float(row["Low"]))

        levels = compute_levels_from_pivots(pivots, px, today_high, today_low)
        for lvl in levels:
            lid = lvl["id"]
            lprice = float(lvl["price"])
            dist = abs(px - lprice) / lprice
            st = state.get(lid, {"triggered": False})
            was = st.get("triggered", False)
            if dist <= trigger_tol:
                if not was:
                    ts_ist = ts.tz_convert(IST)
                    events.append({
                        "ts": ts.tz_convert("UTC").strftime("%Y-%m-%d %H:%M:%S"),
                        "ist": ts_ist.strftime("%Y-%m-%d %H:%M IST"),
                        "weekday": ts_ist.strftime("%a"),
                        "name": lvl["name"],
                        "tf": lvl["timeframe"],
                        "typ": lvl["type"],
                        "price": round(lprice, 2),
                        "spot": round(px, 2),
                        "dist_pct": round(dist * 100, 3),
                        "level_id": lid,
                        "source": lvl.get("source", "CoinDCX B-XAU_USDT"),
                        "source_date": lvl.get("source_date", ""),
                        "source_field": lvl.get("source_field", ""),
                        "source_tf": lvl.get("source_tf", lvl["timeframe"]),
                    })
                    st["triggered"] = True
            elif was and dist > retrigger_dist:
                st["triggered"] = False
            state[lid] = st

        if (i + 1) % 2000 == 0:
            print(f"  ... {i + 1}/{len(bars)} bars, events so far={len(events)}")

    return events


def find_source_candle(daily: pd.DataFrame, event: dict) -> pd.Timestamp | None:
    """Daily bar that created this liquidity (PDH/PDL previous day, else matching High/Low)."""
    if event.get("source_date"):
        src = pd.Timestamp(event["source_date"])
        if src in daily.index:
            return src
        loc = daily.index.get_indexer([src], method="nearest")
        if loc.size and loc[0] >= 0:
            return daily.index[loc[0]]

    ts = pd.Timestamp(event["ts"])
    event_day = ts.normalize()
    price = float(event["price"])
    typ = event["typ"]

    if event["tf"] == "PrevDay":
        prior = daily.loc[daily.index < event_day]
        return prior.index[-1] if len(prior) else None

    window = daily.loc[daily.index < event_day]
    if window.empty:
        return None
    if typ == "resistance":
        dist = (window["High"] - price).abs()
    else:
        dist = (window["Low"] - price).abs()
    return dist.idxmin()


def _box_candle(ax, df: pd.DataFrame, ts: pd.Timestamp, color: str, label: str, lw: float = 2.0):
    if ts is None or df.empty:
        return
    loc = df.index.get_indexer([ts], method="nearest")[0]
    if loc < 0 or loc >= len(df):
        return
    row = df.iloc[loc]
    low, high = float(row["Low"]), float(row["High"])
    pad = max((high - low) * 0.08, 0.4)
    rect = Rectangle(
        (loc - 0.45, low - pad),
        0.90,
        (high - low) + 2 * pad,
        linewidth=lw,
        edgecolor=color,
        facecolor="none",
        zorder=6,
    )
    ax.add_patch(rect)
    ax.annotate(
        label,
        xy=(loc, high + pad),
        xytext=(8, 10),
        textcoords="offset points",
        color=color,
        fontsize=8,
        fontweight="bold",
        va="bottom",
    )


def plot_event(daily: pd.DataFrame, minutes: pd.DataFrame, event: dict, idx: int) -> str:
    ts_utc = pd.Timestamp(event["ts"], tz="UTC")
    ts_ist = ts_utc.tz_convert("Asia/Kolkata").tz_localize(None)
    price = float(event["price"])
    event_day = ts_utc.tz_convert("UTC").tz_localize(None).normalize()

    daily_end = event_day + timedelta(days=2)
    daily_start = event_day - timedelta(days=45)
    if event.get("source_date"):
        src = pd.Timestamp(event["source_date"])
        if src < daily_start:
            daily_start = src - timedelta(days=5)
    dview = daily.loc[(daily.index >= daily_start) & (daily.index <= daily_end)].copy()
    if dview.empty:
        dview = daily.iloc[-45:]

    minute_pad = pd.Timedelta(minutes=150)
    mview = minutes.loc[(minutes.index >= ts_ist - minute_pad) & (minutes.index <= ts_ist + minute_pad)].copy()
    if len(mview) < 30:
        # Fall back to the whole IST session day.
        day0 = ts_ist.normalize()
        mview = minutes.loc[(minutes.index >= day0) & (minutes.index < day0 + pd.Timedelta(days=1))].copy()

    source_ts = find_source_candle(daily, event)
    source_txt = event.get("source") or "CoinDCX B-XAU_USDT"
    source_box = "LIQUIDITY"
    if event.get("source_date") and event.get("source_field"):
        src_d = pd.Timestamp(event["source_date"])
        source_box = f"LIQUIDITY  {src_d.strftime('%d %b')} {event['source_field']}"
    level_ls = "--" if event["typ"] == "support" else "-"
    trigger_tol = event_settings()["gold_trigger_tol"]
    band_lo, band_hi = price * (1 - trigger_tol), price * (1 + trigger_tol)

    fig = plt.figure(figsize=(16.5, 13.5), facecolor="#0b0e14")
    gs = fig.add_gridspec(4, 1, height_ratios=[3.2, 1.0, 3.2, 1.0], hspace=0.08)
    ax_d = fig.add_subplot(gs[0])
    ax_dv = fig.add_subplot(gs[1], sharex=ax_d)
    ax_m = fig.add_subplot(gs[2])
    ax_mv = fig.add_subplot(gs[3], sharex=ax_m)

    hlines_d = dict(
        hlines=[price, band_lo, band_hi],
        colors=[LEVEL_COLOR, BAND_COLOR, BAND_COLOR],
        linestyle=[level_ls, ":", ":"],
        linewidths=[1.6, 0.8, 0.8],
    )
    mpf.plot(
        dview, type="candle", ax=ax_d, volume=ax_dv, style=STYLE,
        hlines=hlines_d, datetime_format="%b %d", xrotation=0, warn_too_much_data=10000,
    )
    ax_d.set_ylabel("Gold price (USD)", color="#cccccc")
    ax_dv.set_ylabel("Volume", color="#cccccc")
    ax_d.set_title(
        f"Daily candles — {event['name']} @ ${price:,.2f}   |   feed: CoinDCX B-XAU_USDT\n"
        f"Liquidity source: {source_txt}   |   Blue box = source candle   |   "
        f"Orange box = event day   |   Yellow = level   |   dotted = 0.20% band",
        color="#f1c40f", fontsize=11, pad=10, loc="left",
    )

    if source_ts is not None and source_ts in dview.index:
        _box_candle(ax_d, dview, source_ts, SOURCE_COLOR, source_box)
    elif source_ts is not None:
        nearest = dview.index[dview.index.get_indexer([source_ts], method="nearest")[0]]
        _box_candle(ax_d, dview, nearest, SOURCE_COLOR, source_box)
    event_daily_ts = dview.index[dview.index.get_indexer([event_day], method="nearest")[0]]
    _box_candle(ax_d, dview, event_daily_ts, TRIGGER_COLOR, "EVENT DAY")

    ax_d.axhline(price, color=LEVEL_COLOR, lw=0)  # already drawn; keep label
    ax_d.text(
        1.0, price, f"  {event['name']} ${price:,.2f}",
        color=LEVEL_COLOR, fontsize=8, va="center", ha="left",
        transform=ax_d.get_yaxis_transform(),
    )

    hlines_m = dict(
        hlines=[price, band_lo, band_hi],
        colors=[LEVEL_COLOR, BAND_COLOR, BAND_COLOR],
        linestyle=[level_ls, ":", ":"],
        linewidths=[1.6, 0.8, 0.8],
    )
    mpf.plot(
        mview, type="candle", ax=ax_m, volume=ax_mv, style=STYLE,
        hlines=hlines_m, datetime_format="%H:%M", xrotation=0, warn_too_much_data=10000,
    )
    ax_m.set_ylabel("Gold price (USD)", color="#cccccc")
    ax_mv.set_ylabel("Volume", color="#cccccc")
    ax_m.set_title(
        f"1-minute candles — trigger {ts_ist.strftime('%d %b %Y %H:%M')} IST "
        f"({ts_utc.strftime('%H:%M')} UTC)  |  spot ${event['spot']:,.2f}  vs  level ${price:,.2f}\n"
        f"Orange box = the 1-minute candle that fired the event   |   "
        f"level from {source_txt}",
        color="#e67e22", fontsize=11, pad=10, loc="left",
    )
    _box_candle(ax_m, mview, ts_ist, TRIGGER_COLOR, "TRIGGER CANDLE", lw=2.4)
    ax_m.text(
        1.0, price, f"  {event['name']} ${price:,.2f}",
        color=LEVEL_COLOR, fontsize=8, va="center", ha="left",
        transform=ax_m.get_yaxis_transform(),
    )

    for ax in (ax_d, ax_dv, ax_m, ax_mv):
        ax.tick_params(colors="#bbbbbb")
        for spine in ax.spines.values():
            spine.set_color("#2c3e50")

    fig.suptitle(
        f"Gold Event Finder  ·  {idx:02d}  ·  {event['name']} ({event['tf']})  ·  "
        f"{ts_ist.strftime('%a %d %b %Y  %H:%M IST')}",
        color="#ecf0f1", fontsize=14, fontweight="bold", y=0.995,
    )
    caption = (
        f"Feed: CoinDCX B-XAU_USDT  |  Liquidity source: {source_txt}  |  "
        "weekdays only  |  Event = 1-minute close within 0.20% of an uncrossed label"
    )
    fig.text(0.01, 0.006, caption, color="#7f8c8d", fontsize=8)

    slug = (
        f"{idx:02d}_{ts_utc.strftime('%Y%m%d_%H%M')}_"
        f"{event['tf']}_{event['typ']}_{price:.0f}"
    ).replace(" ", "")
    out_path = os.path.join(OUT_DIR, f"{slug}.png")
    fig.savefig(out_path, dpi=160, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    return out_path


def write_index(paths: list[str]):
    cards = []
    for p in paths:
        name = os.path.basename(p)
        cards.append(
            f'<div class="card"><h3>{name}</h3>'
            f'<img src="{name}" alt="{name}"></div>'
        )
    html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<title>Gold Event Charts — last week</title>
<style>
 body {{ margin:0; background:#0b0e14; color:#ecf0f1; font-family:Segoe UI,sans-serif; }}
 h1 {{ padding:20px 24px 8px; font-size:22px; }}
 p {{ padding:0 24px 16px; color:#95a5a6; }}
 .card {{ margin:0 20px 28px; }}
 .card h3 {{ font-size:13px; color:#f1c40f; font-weight:600; }}
 img {{ width:100%; max-width:1400px; border:1px solid #243044; }}
</style></head>
<body>
<h1>CoinDCX XAUUSDT Event Finder — last 7 days</h1>
<p>Each figure is two graphs: daily candles with the liquidity source candle boxed, and 1-minute candles with the trigger boxed. Feed: CoinDCX B-XAU_USDT. Times are IST. Weekends excluded.</p>
{''.join(cards)}
</body></html>"""
    with open(os.path.join(OUT_DIR, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    for old in glob.glob(os.path.join(OUT_DIR, "*.png")):
        os.remove(old)

    daily = load_daily()
    minutes_utc = load_minutes()
    print(f"Daily {daily.index.min().date()} -> {daily.index.max().date()}  ({len(daily)} bars)")
    print(f"Minute {minutes_utc.index.min()} -> {minutes_utc.index.max()}  ({len(minutes_utc)} bars) UTC")

    events = replay_last_7_days(daily, minutes_utc)

    print("\n" + "=" * 108)
    print(" WEEKDAY LEVELS (CoinDCX B-XAU_USDT, weekends excluded)  |  liquidity source = candle that formed the level")
    print("=" * 108)
    if not minutes_utc.empty:
        start = minutes_utc.index.min().tz_convert("UTC").normalize().tz_localize(None)
        end = minutes_utc.index.max().tz_convert("UTC").normalize().tz_localize(None)
        for day in pd.date_range(start, end, freq="D"):
            if int(day.dayofweek) >= 5:
                continue
            hist = daily.loc[daily.index < day]
            if hist.empty:
                continue
            pivots = prepare_day_pivots(hist)
            px = float(hist.iloc[-1]["Close"])
            levels = compute_levels_from_pivots(pivots, px, today_high=px, today_low=px)
            print(f"\n  {day.strftime('%a %d %b %Y')}  prev close ${px:,.2f}")
            for lvl in sorted(levels, key=lambda x: -x["price"]):
                gap = (lvl["price"] - px) / px * 100
                src = lvl.get("source", "")
                print(f"    {lvl['timeframe']:8} {lvl['name']:24} ${lvl['price']:10,.2f}  "
                      f"gap={gap:+6.2f}%  |  {src}")

    print("\n" + "=" * 108)
    print(" EVENTS that should have fired  (times IST)")
    print("=" * 108)
    if not events:
        print("No labels within 0.20% of an uncrossed level.")
        return

    print(f"{'#':>3}  {'Trigger (IST)':<22}  {'Label':<24}  {'Level':>10}  {'Trig px':>10}  {'Gap':>7}  Liquidity source")
    print("-" * 108)
    for i, ev in enumerate(events, 1):
        print(
            f"{i:3d}  {ev['ist']:<22}  {ev['name']:<24}  "
            f"${ev['price']:9,.2f}  ${ev['spot']:9,.2f}  {ev['dist_pct']:6.3f}%  {ev.get('source', '')}"
        )
    print("=" * 108)
    print(f"TOTAL EVENTS: {len(events)}")

    csv_path = os.path.join(OUT_DIR, "last_7_days_events_ist.csv")
    pd.DataFrame(events).to_csv(csv_path, index=False)
    print(f"Saved table -> {csv_path}")

    minutes_ist = minutes_utc.copy()
    minutes_ist.index = minutes_ist.index.tz_convert(IST).tz_localize(None)

    paths = []
    for i, event in enumerate(events, 1):
        path = plot_event(daily, minutes_ist, event, i)
        paths.append(path)
        print(f"[OK] {path}")
    write_index(paths)
    print(f"\nWrote {len(paths)} charts + index.html -> {OUT_DIR}")


if __name__ == "__main__":
    main()
