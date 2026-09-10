"""
Background Event Manager Daemon (With Telegram Integration)
============================================================
Runs continuously in the background from laptop startup to shutdown.
Checks configuration dynamically on every 5-minute loop.

Features:
  1. Sends Telegram Startup Summary when laptop turns on.
  2. Runs 5-minute Gold Event Finder check.
  3. Runs Stock Event Finder check based on Web Dashboard config.
"""

import json
import os
import sys

# Safe stdout/stderr fallback for pythonw (windowless python)
if sys.stdout is None:
    sys.stdout = open(os.path.join("data", "manager.log"), "a", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.path.join("data", "manager.log"), "a", encoding="utf-8")

import time
import subprocess
from datetime import datetime
import yaml


sys.path.append(os.getcwd())
try:
    from telegram_notifier import send_startup_summary
    from xauusd_event_finder import (MONITOR_SLOW_SEC, compute_stock_screener_levels,
                                     fetch_latest_data, read_monitor_interval)
    from coindcx_gold import is_gold_weekend
except ImportError:
    is_gold_weekend = lambda *_args, **_kw: False
    MONITOR_SLOW_SEC = 300
    read_monitor_interval = lambda: 300

CONFIG_YML = "config.yml"
CONFIG_JSON = os.path.join("data", "gold_xauusd", "event_config.json")

DEFAULT_CONFIG = {
    "run_gold_event_finder": True,
    "show_gold_events": True,
    "gold_trigger_tol": 0.0020,
    "run_stock_event_finder": True,
    "show_stock_events": True
}


def load_config() -> dict:
    conf = DEFAULT_CONFIG.copy()
    if os.path.exists(CONFIG_YML):
        try:
            with open(CONFIG_YML, "r", encoding="utf-8") as f:
                raw_yml = yaml.safe_load(f)
                if raw_yml:
                    if "event_finder" in raw_yml:
                        conf.update(raw_yml["event_finder"])
                    if "run_times" in raw_yml:
                        conf["run_times"] = raw_yml["run_times"]
        except Exception:
            pass

    if os.path.exists(CONFIG_JSON):
        try:
            with open(CONFIG_JSON, "r", encoding="utf-8") as f:
                json_conf = json.load(f)
                conf.update(json_conf)
        except Exception:
            pass

    return conf


def send_laptop_startup_telegram():
    """Send Message Type 1 on laptop boot / daemon start."""
    try:
        df_daily, df_1m = fetch_latest_data()
        if not df_1m.empty:
            current_price = float(df_1m.iloc[-1]["Close"])
            levels = compute_stock_screener_levels(df_daily, df_1m, current_price)

            resistances = []
            supports = []
            for l in levels:
                if l["price"] > current_price:
                    gap = ((l["price"] - current_price) / current_price) * 100
                    resistances.append({"name": l["name"], "timeframe": l["timeframe"], "price": l["price"], "gap_pct": gap})
                elif l["price"] < current_price:
                    gap = ((current_price - l["price"]) / current_price) * 100
                    supports.append({"name": l["name"], "timeframe": l["timeframe"], "price": l["price"], "gap_pct": gap})

            resistances.sort(key=lambda x: x["price"])
            supports.sort(key=lambda x: x["price"], reverse=True)

            print("[Telegram] Sending Startup Summary to Telegram...")
            send_startup_summary(current_price, resistances, supports)
    except Exception as e:
        print(f"[Telegram Startup Warning]: {e}")


def main_loop():
    print("=" * 75)
    print(" BACKGROUND EVENT FINDER DAEMON STARTED")
    print(" Gold: 5 min, 1 min inside 0.50%, 30s inside 0.20%")
    print("=" * 75)

    # Send startup message when laptop turns on / daemon starts
    send_laptop_startup_telegram()

    last_executed_stock_slot = None

    while True:
        sleep_sec = MONITOR_SLOW_SEC
        try:
            now = datetime.now()
            now_str = now.strftime("%Y-%m-%d %H:%M:%S")
            conf = load_config()

            run_gold = bool(conf.get("run_gold_event_finder", True))
            show_gold = bool(conf.get("show_gold_events", True))
            tol_pct = float(conf.get("gold_trigger_tol", 0.0020)) * 100
            run_stock = bool(conf.get("run_stock_event_finder", True))

            print(f"\n[{now_str}] Executing Scheduled Loop Check...")
            print(f"  * Gold Event Finder: {'ENABLED' if run_gold else 'DISABLED'} (Alerts: {'ON' if show_gold else 'SILENT'}, Tol: {tol_pct:.2f}%)")
            print(f"  * Stock Event Finder: {'ENABLED' if run_stock else 'DISABLED'}")

            # 1. Run Gold Event Finder if enabled (weekdays only; gold is off Sat/Sun)
            if run_gold:
                if is_gold_weekend(now):
                    print("  -> Gold Event Finder skipped (Saturday/Sunday).")
                else:
                    subprocess.run([sys.executable, "xauusd_event_finder.py"], check=False)
                    try:
                        sleep_sec = int(read_monitor_interval())
                    except Exception:
                        sleep_sec = MONITOR_SLOW_SEC
            else:
                print("  -> Gold Event Finder is turned OFF in config. Skipping.")

            # 2. Run Stock Event Finder if enabled and matching a scheduled run_time
            if run_stock:
                run_times = [str(t) for t in conf.get("run_times", ["09:30", "10:30", "11:30", "12:30", "13:30", "14:30", "16:00"])]
                current_hhmm = now.strftime("%H:%M")
                current_slot = f"{now.strftime('%Y-%m-%d')}_{current_hhmm}"

                if current_hhmm in run_times:
                    if last_executed_stock_slot != current_slot:
                        latest_html = os.path.join("data", "screener_output", "latest.html")
                        already_ran = False
                        if os.path.exists(latest_html):
                            mtime = os.path.getmtime(latest_html)
                            if (time.time() - mtime) < 240:
                                already_ran = True

                        if not already_ran:
                            print(f"  -> Scheduled time {current_hhmm} reached. Executing Stock Event Finder...")
                            subprocess.run([sys.executable, "scheduler_run.py"], check=False)
                        else:
                            print(f"  -> Stock Event Finder was already executed recently for slot {current_hhmm}.")
                        last_executed_stock_slot = current_slot
                    else:
                        print(f"  -> Stock Event Finder already processed for slot {current_hhmm}.")
                else:
                    print(f"  -> Stock Event Finder: Not a scheduled run time ({current_hhmm}). Skipping.")
            else:
                print("  -> Stock Event Finder is turned OFF in config. Skipping.")

        except Exception as e:
            print(f"  [Loop Error]: {e}")
            sleep_sec = MONITOR_SLOW_SEC

        print(f"  -> Next loop in {sleep_sec} seconds")
        time.sleep(max(5, int(sleep_sec)))


if __name__ == "__main__":
    main_loop()

