# EventFinder

Find NSE stocks trading **near a key support/resistance level**, on an automated
daily schedule.

It does three things:

1. **Maintains price data** — ~10 years of daily bars (and optionally 1‑hour bars)
   for all NSE equities, updated incrementally.
2. **Finds support/resistance "labels"** (pivot levels) on Weekly / Monthly /
   1‑Year / 2‑Year candles, with charts.
3. **Screens** the Nifty 50 / 100 / 200 universes for stocks sitting within a
   configurable % of a key level, and **runs itself on a schedule** with a
   clickable Windows notification.

Everything runs inside the **`STOCK` conda environment**.

---

## Table of contents

- [Prerequisites](#prerequisites)
- [Quick start](#quick-start)
- [Data: download & update](#data-download--update)
- [Charts (find_labels.py)](#charts-find_labelspy)
- [Screener (screen_levels.py)](#screener-screen_levelspy)
- [The scheduler — run automatically](#the-scheduler--run-automatically)
  - [Install / start](#install--start)
  - [Run now / test anytime](#run-now--test-anytime)
  - [Change the run times (restart)](#change-the-run-times-restart)
  - [Stop / remove the schedule](#stop--remove-the-schedule)
  - [Check status](#check-status)
- [Where the output goes](#where-the-output-goes)
- [config.yml reference](#configyml-reference)
- [How it decides what to do each run](#how-it-decides-what-to-do-each-run)
- [Troubleshooting](#troubleshooting)
- [File map](#file-map)

---

## Prerequisites

- Windows, with **Anaconda/conda** and an environment named **`STOCK`** that has
  `pandas`, `numpy`, `yfinance`, `mplfinance`, `matplotlib`, `requests`,
  `pyyaml`, and `tabulate` installed.
- Run everything from the project folder:
  `C:\Users\parmp\OneDrive\CODE\Stocks\EventFinder`
- All commands below use `conda run -n STOCK python ...`. If that ever misbehaves,
  you can instead `conda activate STOCK` once and then just call `python ...`.

> Install any missing packages with, e.g.:
> `conda run -n STOCK python -m pip install pyyaml tabulate`

---

## Quick start

```powershell
# 1. (first time) download ~10y daily data for all NSE symbols
conda run -n STOCK python download_nse_daily.py

# 2. build the "near a key level" stock list once, by hand
conda run -n STOCK python screen_levels.py

# 3. turn on the automatic schedule (10:00 / 12:00 / 16:00 by default)
conda run -n STOCK python manage_scheduler.py install
```

After step 3 it runs by itself. The list opens from the notification, or from
`data\screener_output\latest.html`.

If you edit `config.yml` after the initial setup, re-apply it with:

```powershell
conda run -n STOCK python manage_scheduler.py restart
```

This is especially important when you change scheduler-related values such as
`run_times` or `moneycontrol_run_times`.

---

## Data: download & update

### One command to update everything

```powershell
conda run -n STOCK python update_data.py
```

This updates **both** datasets:

- `data/nse_daily/`  — ~10y of daily bars
- `data/nse_hourly/` — last ~30d of 1‑hour bars *(currently disabled in the
  scheduler; see config)*

It is **incremental and safe**:

- **Only new data is fetched** — it pulls from `last_date − 2 trading days` to
  today (a small overlap), appends genuinely new days, and overwrites today's
  in‑progress bar.
- **Missing file** → that ticker is fully downloaded.
- **Corporate action** (a confirmed past day's Close no longer matches) →
  **only that one ticker** is re‑downloaded. During market hours this check is
  skipped (just append); after close it runs so the data stays correct.

Useful flags:

```powershell
conda run -n STOCK python update_data.py --only daily      # skip hourly
conda run -n STOCK python update_data.py --workers 8       # parallelism
conda run -n STOCK python update_data.py --limit 5         # quick test
```

### First-time bulk downloads (optional, faster than letting the updater backfill)

```powershell
conda run -n STOCK python download_nse_daily.py            # all NSE, ~10y daily
conda run -n STOCK python download_nse_hourly.py           # all NSE, last 30d 1h
```

Re-running a downloader **skips files already on disk** (resumable). Failures are
written to `failures.csv` / `failures_hourly.csv` so you can re-run to retry.

---

## Charts (find_labels.py)

Draw the 6 key levels (1 above + 1 below the current price for Daily, Weekly,
Monthly — daily blue, weekly red, monthly black):

```powershell
conda run -n STOCK python find_labels.py RELIANCE
conda run -n STOCK python find_labels.py RELIANCE TCS INFY
```

- Output: `data/plots/<SYMBOL>_levels.png`
- `--split` also writes per‑timeframe charts (`_daily/_weekly/_monthly.png`),
  each showing just that timeframe's 2 levels.
- `--all` processes every symbol in `data/nse_daily/` (uses multiprocessing;
  `-j N` sets workers).

---

## Screener (screen_levels.py)

Find stocks near a key level, biggest timeframe first, widening the universe
until enough are found:

```powershell
conda run -n STOCK python screen_levels.py                 # 20 stocks, within 2%
conda run -n STOCK python screen_levels.py --target 30 --tol 0.015
conda run -n STOCK python screen_levels.py --save-csv
```

- **`--target`** — how many stocks to collect (default `20`).
- **`--tol`** — proximity to a level, as a fraction (`0.02` = 2%; **changeable**).
- **Cascade:** universes `Nifty 50 → 100 → 200`; timeframes `2Y → 1Y → Monthly →
  Weekly`. It stops as soon as `--target` is reached. Closest matches rank first.
- A stock is "near" when its latest close is within `--tol` of the nearest
  **active** level — either the resistance above or the support below.
- Index constituent lists are fetched from NSE and cached as
  `data/ind_nifty*list.csv`.

---

## The scheduler — run automatically

The scheduler runs `scheduler_run.py` at the times in `config.yml`. Per run it
decides what to do from the clock (see
[How it decides](#how-it-decides-what-to-do-each-run)).

> **All scheduler control is done with `manage_scheduler.py`.**

### Install / start

```powershell
conda run -n STOCK python manage_scheduler.py install
```

This registers (no admin needed):

- **Windows scheduled tasks** under the `EventFinder\` folder — one per run time
  (`Time_1000`, `Time_1200`, `Time_1600`). They are scheduled **weekdays only
  (Mon–Fri)** — never Sat/Sun — and run **only while you're logged in** so the
  notification can appear.
- A **logon launcher** (`EventFinder_Startup.vbs` in your Startup folder) so it
  also runs once each time you start/sign in to the PC.
- The **`eventfinder://` click‑to‑open protocol**, so clicking the notification
  opens `latest.html`.

**After a restart of the PC you do nothing** — the tasks persist and the logon
launcher fires automatically.

### Run now / test anytime

```powershell
# Force a LIST run right now (updates data for Nifty 200, builds + notifies),
# regardless of the time of day — best for testing:
conda run -n STOCK python scheduler_run.py --list

# Behave exactly like a scheduled tick (phase decided by the clock):
conda run -n STOCK python manage_scheduler.py run-now

# Force a full end-of-day data update (all symbols, discrepancy check, no list):
conda run -n STOCK python scheduler_run.py --eod

# Fire an actual registered task immediately:
schtasks /Run /TN "EventFinder\Time_1000"
```

### Change the run times (restart)

Edit **`run_times`** in `config.yml`, e.g. change `"12:00"` to `"11:00"` or add
more times. Then **restart** to apply:

```powershell
conda run -n STOCK python manage_scheduler.py restart
```

The tasks are re‑created from the new times — a newly added/changed time fires
**today** (if it hasn't passed yet) and every following day.

### Stop / remove the schedule

```powershell
# Remove EVERYTHING (all timed tasks + logon launcher + click protocol):
conda run -n STOCK python manage_scheduler.py uninstall
```

Other ways to stop:

```powershell
# Temporarily disable one time (keeps it registered):
schtasks /Change /TN "EventFinder\Time_1000" /DISABLE
schtasks /Change /TN "EventFinder\Time_1000" /ENABLE      # re-enable

# Or use the Windows "Task Scheduler" app -> Task Scheduler Library ->
# EventFinder -> right-click a task -> Disable/Delete.
```

To also stop the run‑at‑logon catch‑up without a full uninstall, delete
`EventFinder_Startup.vbs` from your Startup folder
(`%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`).

### Check status

```powershell
conda run -n STOCK python manage_scheduler.py status
```

Shows the registered `EventFinder\*` tasks, whether the logon launcher is
present, and whether the click‑to‑open protocol is registered. For the next fire
time of a task:

```powershell
schtasks /Query /TN "EventFinder\Time_1000" /V /FO LIST | findstr "Next"
```

---

## Where the output goes

Everything lands in **`data/screener_output/`**:

| File | What it is |
|------|------------|
| `latest.html` | The current list — **sortable** (click any column header), NEW stocks highlighted. This is what the notification opens. |
| `latest.csv` / `latest.md` | Same list as CSV / Markdown. |

**Fyers watchlists** are saved to **`output.export_dir`** (default
`~/Downloads/Watchlist`, i.e. `C:\Users\<you>\Downloads\Watchlist`), NOT inside `screener_output`:

| File (in `export_dir`) | What it is |
|------|------------|
| `latest_fyers.txt` | **Fyers DESKTOP watchlist** — one comma-separated line of `NSE:<SYM>-EQ` (indices from `watchlist_prefix` pinned at top). Import in the desktop watchlist. |
| `latest_fyers.csv` | **Fyers WEB watchlist** — `Symbol` column. In Fyers Web: watchlist ⋮ menu → Import. |
| `fyers_<DATETIME>.txt` / `.csv` | Date‑stamped snapshots, written automatically each run **and** when you click **Save dated file to folder** in `latest.html`. |

**Export buttons in `latest.html`:**
- **Save dated file to folder** → writes the dated + `latest_fyers.*` files into `export_dir`
  (via the `eventfinder://export` protocol → `export_watchlist.py`) and opens that folder. Only
  this button can write to the exact folder.
- **Download .txt / .csv** → save a date‑stamped file to your browser's Downloads (browsers can't
  target an arbitrary folder).
| `list_YYYYMMDD_HHMMSS.*` | A snapshot of every run. |
| `state_YYYYMMDD.json` | Per‑day state: how many runs, which symbols have been shown (drives the "NEW" diff). |
| `run.log` | Console output of every scheduled run (appended). Check here if a run misbehaves. |

Other data locations:

- `data/nse_daily/` , `data/nse_hourly/` — price CSVs (one per symbol)
- `data/ind_nifty*list.csv` — cached index constituents
- `data/plots/` — charts from `find_labels.py`
- `data/update_state.csv` , `data/update_state_hourly.csv` — updater run‑state

**Notifications:** the first list of the day says *"stock list ready"*; later runs
say *"N NEW: …"* (stocks not shown earlier today) **and** still link the full
list. Click the toast to open `latest.html`.

---

## config.yml reference

```yaml
run_times:            # IST, 24h HH:MM. Add/remove freely, then `restart`.
  - "10:00"
  - "12:00"
  - "16:00"

market:
  tz_offset_minutes: 330   # IST = UTC+05:30
  open: "09:15"
  close: "15:30"
  trading_days_only: true  # Sat/Sun -> no list, data update only

screener:
  target: 20               # how many stocks to collect
  tol: 0.02                # proximity to a level (0.02 = 2%) -- CHANGEABLE
  left: 3                  # pivot strictness
  right: 2
  big_mult: 2.0

data:
  daily_dir: "data/nse_daily"
  hourly_dir: "data/nse_hourly"
  base_dir: "data"
  workers: 8
  overlap_days: 2                       # incremental re-fetch overlap
  intraday_universe_list: "ind_nifty200list.csv"   # quick-updated during market hours
  update_hourly_intraday: false         # hourly off for now
  update_hourly_eod: false              # hourly off for now (set true to maintain it)
  eod_tol: 0.001                        # corporate-action threshold -> resync that ticker

output:
  dir: "data/screener_output"
  notify: true             # show a Windows notification on each list run
  auto_open: false         # also auto-open latest.html every list run (vs only on click)
  watchlist_prefix:        # symbols always pinned at the TOP of every Fyers watchlist
    - "NSE:NIFTY50-INDEX"
    - "BSE:SENSEX-INDEX"
  export_dir: "~/Downloads/Watchlist"   # where the Fyers watchlist files are written
```

> If clicking the notification ever stops opening the list on your machine, set
> `auto_open: true` and `restart` — the list will then open by itself each run.

---

## How it decides what to do each run

`scheduler_run.py` checks the current IST time against `config.yml`:

- **During market hours** (a trading day, `open ≤ now ≤ close`):
  1. **Quick data update** of the Nifty 200 universe — appends new/today's bars,
     downloads any missing files, **no** corporate‑action check.
  2. **Builds the list**, diffs against earlier lists today, writes the files,
     and **notifies**.

- **Outside market hours on a weekday** (after close, before open):
  1. **Full data update** of all symbols **with** the corporate‑action check
     (re‑downloads only mismatched tickers).
  2. **No list** is built.

- **Weekends (Sat/Sun):** nothing runs. The weekday‑only tasks don't fire, and
  if `scheduler_run.py` is invoked anyway (e.g. the logon launcher when you sign
  in on a weekend) it detects the weekend and exits immediately — no data update,
  no list.

So your `10:00` and `12:00` runs build lists; the `16:00` run keeps the full
dataset correct; Saturday and Sunday are idle.

---

## Troubleshooting

- **"It didn't update the data."** It did — open `data\screener_output\run.log`
  and look for the `DATA:` line, e.g.
  `DATA: 0 downloaded, 0 got new days, 0 today-bar refreshed, 200 already current`.
  "already current" just means nothing new was available.
- **Clicking the notification does nothing.** Set `output.auto_open: true` in
  `config.yml` and `restart`; the list will open automatically. (Also confirm the
  protocol is present via `manage_scheduler.py status`.)
- **A run didn't fire.** Tasks run **only while you're logged in** (so the toast
  can show). If the PC was asleep/off/logged out at that minute, that tick is
  skipped; the logon launcher catches up next sign‑in. Run it manually with
  `scheduler_run.py --list`.
- **Some symbols failed to download.** See `update_failures.csv` /
  `update_failures_hourly.csv`; re‑run the update to retry (successes are skipped).
- **Want hourly data maintained too.** Set `update_hourly_eod: true` (and/or
  `update_hourly_intraday: true`) in `config.yml`, then `restart`. The first such
  run downloads ~30d of hourly for all symbols (heavy, one‑time).

---

## File map

| File | Purpose |
|------|---------|
| `config.yml` | All schedule + screener settings. |
| `manage_scheduler.py` | Install / restart / uninstall / status / run‑now the schedule. |
| `scheduler_run.py` | One scheduled run: decide phase → update data → build/diff/notify list. |
| `screen_levels.py` | The cascade screener (Nifty 50→100→200, 2Y→1Y→M→W). |
| `find_labels.py` | Support/resistance labels + charts; timeframe resamplers. |
| `update_data.py` | One command to update both daily and hourly datasets. |
| `update_nse_daily.py` | Incremental daily updater (+ `run()` used by the scheduler). |
| `update_nse_hourly.py` | Incremental hourly updater. |
| `download_nse_daily.py` | Bulk daily downloader (all NSE). |
| `download_nse_hourly.py` | Bulk 1‑hour downloader (last 30d). |
| `run_screener.bat` | Generated launcher the scheduled tasks call. |
| `open_latest.bat` | Generated; opens `latest.html` (used by the click protocol). |
