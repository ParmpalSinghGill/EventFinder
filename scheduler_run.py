"""
One scheduled run of the EventFinder pipeline. The Windows scheduled tasks call
this; it decides what to do from the current IST time and config.yml:

  * DURING market hours (a trading day, open <= now <= close):
      - quick data update of the screener universe (NO corporate-action /
        discrepancy check -- just pull new/today's bars),
      - build the "near a key level" stock list,
      - diff against earlier lists made today, write files, and notify:
          first list of the day  -> "stock list ready"
          later runs             -> "<n> NEW stock(s)" + the full list too.

  * OUTSIDE market hours (after close, pre-open, or a non-trading day):
      - FULL data update WITH the discrepancy check (daily + hourly, all
        symbols) so the data stays correct,
      - NO list is built.

Run manually for testing:
    conda run -n STOCK python scheduler_run.py            # auto (by clock)
    conda run -n STOCK python scheduler_run.py --list     # force a list now
    conda run -n STOCK python scheduler_run.py --eod      # force a full EOD update
"""

import argparse
import ctypes
import json
import os
import subprocess
from datetime import datetime, time as dtime, timedelta, timezone

import pandas as pd
import yaml

import screen_levels
import update_nse_daily as daily
import update_nse_hourly as hourly

BASE = os.path.dirname(os.path.abspath(__file__))
NO_DISCREPANCY_TOL = 1e9      # effectively disables the corporate-action resync


# --------------------------------------------------------------------------- #
def _abs(path):
    return path if os.path.isabs(path) else os.path.join(BASE, path)


def load_config(path="config.yml"):
    with open(_abs(path), "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def _parse_hhmm(s):
    h, m = str(s).split(":")
    return dtime(int(h), int(m))


def market_phase(cfg, now):
    """Return 'intraday' (build a list) or 'eod' (full update, no list)."""
    mk = cfg["market"]
    if mk.get("trading_days_only", True) and now.weekday() >= 5:
        return "eod"
    o, c = _parse_hhmm(mk["open"]), _parse_hhmm(mk["close"])
    return "intraday" if o <= now.time() <= c else "eod"


# --------------------------------------------------------------------------- #
# Power state
# --------------------------------------------------------------------------- #
def on_battery():
    """True only if the machine is CONFIRMED running on battery (AC unplugged).
    Desktops / unknown state -> False, so they always run normally."""
    class _SPS(ctypes.Structure):
        _fields_ = [("ACLineStatus", ctypes.c_ubyte),
                    ("BatteryFlag", ctypes.c_ubyte),
                    ("BatteryLifePercent", ctypes.c_ubyte),
                    ("Reserved1", ctypes.c_ubyte),
                    ("BatteryLifeTime", ctypes.c_ulong),
                    ("BatteryFullLifeTime", ctypes.c_ulong)]
    try:
        s = _SPS()
        if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(s)):
            return False
        return s.ACLineStatus == 0        # 0 = on battery, 1 = AC, 255 = unknown
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# Notifications
# --------------------------------------------------------------------------- #
def _ps(script):
    try:
        p = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", script],
                           capture_output=True, text=True, timeout=30)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _xml(s):
    """Escape for XML text inside a PowerShell single-quoted string."""
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
            .replace("'", "''"))


def notify(title, message, action=None):
    """Windows toast that, when CLICKED, opens the list via the eventfinder://
    protocol (registered by manage_scheduler). Falls back to a tray balloon.

    `action`, if given, is a (button_label, eventfinder_uri) pair that adds a
    clickable button to the toast (e.g. ("Run now", "eventfinder://run")); the
    button fires the URI through the same protocol handler."""
    t, m = _xml(title), _xml(message)
    if action:
        label, uri = action
        actions_xml = (f'<actions><action content="{_xml(label)}" '
                       f'arguments="{_xml(uri)}" activationType="protocol"/>'
                       f'</actions>')
        attribution = "Choose an action below"
    else:
        actions_xml = ""
        attribution = "Click to open the list"
    xml = (f'<toast launch="eventfinder://open" activationType="protocol">'
           f'<visual><binding template="ToastGeneric">'
           f'<text>{t}</text><text>{m}</text>'
           f'<text placement="attribution">{attribution}</text>'
           f'</binding></visual>{actions_xml}</toast>')
    toast = (
        "$ErrorActionPreference='Stop';"
        "$null=[Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime];"
        "$null=[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,"
        "ContentType=WindowsRuntime];"
        f"$xml='{xml}';"
        "$d=New-Object Windows.Data.Xml.Dom.XmlDocument;$d.LoadXml($xml);"
        "$n=[Windows.UI.Notifications.ToastNotification]::new($d);"
        "[Windows.UI.Notifications.ToastNotificationManager]::"
        "CreateToastNotifier('EventFinder').Show($n)"
    )
    if _ps(toast):
        return
    tb, mb = title.replace("'", "''"), message.replace("'", "''")
    balloon = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "Add-Type -AssemblyName System.Drawing;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;$n.Visible=$true;"
        f"$n.ShowBalloonTip(8000,'{tb}','{mb}',"
        "[System.Windows.Forms.ToolTipIcon]::Info);"
        "Start-Sleep -Seconds 8;$n.Dispose()"
    )
    _ps(balloon)


# --------------------------------------------------------------------------- #
# Data updates
# --------------------------------------------------------------------------- #
def update_intraday(cfg):
    """Quick update of just the screener universe, no discrepancy check."""
    d = cfg["data"]
    outdir = _abs(cfg["output"]["dir"])
    os.makedirs(outdir, exist_ok=True)
    syms = screen_levels.get_index_constituents(
        d["intraday_universe_list"], _abs(d["base_dir"]))
    sf = os.path.join(outdir, "_intraday_universe.csv")
    pd.DataFrame({"SYMBOL": syms}).to_csv(sf, index=False)
    print(f"Intraday data check: {len(syms)} universe symbols "
          f"(overlap append, no resync)")
    c = daily.run(outdir=_abs(d["daily_dir"]), tol=NO_DISCREPANCY_TOL,
                  overlap=d.get("overlap_days", 2),
                  workers=d["workers"], symbols_file=sf, force=True) or {}
    print(f"  DATA: {c.get('new', 0)} downloaded (were missing), "
          f"{c.get('appended', 0)} got new days, {c.get('updated', 0)} today-bar "
          f"refreshed, {c.get('uptodate', 0)} already current, "
          f"{c.get('fail', 0)} failed")
    if c.get("fail", 0):
        print("  NOTE: some symbols failed to download -> see update_failures.csv")
    if d.get("update_hourly_intraday", False):
        hourly.run(outdir=_abs(d["hourly_dir"]), tol=NO_DISCREPANCY_TOL,
                   workers=d["workers"], symbols_file=sf, force=True)


def update_eod(cfg):
    """Full update of all symbols WITH the per-ticker discrepancy resync.
    Hourly is updated only when data.update_hourly_eod is true."""
    d = cfg["data"]
    do_hourly = d.get("update_hourly_eod", False)
    print(f"EOD update: ALL symbols, per-ticker resync ON "
          f"(daily{' + hourly' if do_hourly else ''})")
    daily.run(outdir=_abs(d["daily_dir"]), tol=d.get("eod_tol", 0.001),
              overlap=d.get("overlap_days", 2), workers=d["workers"])
    if do_hourly:
        hourly.run(outdir=_abs(d["hourly_dir"]), tol=d.get("eod_tol", 0.001),
                   workers=d["workers"])


# --------------------------------------------------------------------------- #
# List building, diffing, output
# --------------------------------------------------------------------------- #
def _state_path(outdir, day):
    return os.path.join(outdir, f"state_{day}.json")


def _html(df, new_syms, run_n, ts, prefix=()):
    import html as _h
    new = set(new_syms)
    sub = (f"<b>NEW since earlier today ({len(new_syms)}):</b> "
           + (", ".join(new_syms) if new_syms else "none")
           if run_n > 1 else "First list of the day.")
    cols = ["rank", "symbol", "universe", "timeframe", "side",
            "level", "close", "dist_pct", "formed"]
    rows = ""
    for _, r in df.iterrows():
        is_new = r["symbol"] in new
        cls = ' class="new"' if is_new else ""
        cells = []
        for c in cols:
            val = _h.escape(str(r[c]))
            if c == "symbol" and is_new:
                val += ' <span class="badge">NEW</span>'
            cells.append(f"<td>{val}</td>")
        rows += f"<tr{cls}>{''.join(cells)}</tr>"
    # numeric columns (0-based): #, Level, Close, Dist %
    headers = ["#", "Symbol", "Universe", "Timeframe", "Side",
               "Level", "Close", "Dist %", "Formed"]
    hrow = "".join(f'<th onclick="sortTable({i})">{h}<span class="arr"></span></th>'
                   for i, h in enumerate(headers))
    fy_js = ",".join("'%s'" % s for s in list(prefix) + _fyers_symbols(df))
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>EventFinder list</title><style>
body{{font-family:'Segoe UI',Arial;margin:24px;color:#222}}
h2{{margin-bottom:4px}} .meta{{color:#555;margin:2px 0}}
table{{border-collapse:collapse;margin-top:14px;font-size:14px}}
th,td{{border:1px solid #ccc;padding:5px 10px;text-align:left}}
th{{background:#222;color:#fff;cursor:pointer;user-select:none;white-space:nowrap}}
th:hover{{background:#3a3a3a}} .arr{{font-size:10px;margin-left:5px;color:#bbb}}
tr:nth-child(even){{background:#f6f6f6}}
tr.new{{background:#fff4cf}} .badge{{color:#b00;font-weight:bold;font-size:11px}}
.hint{{color:#888;font-size:12px}}
.bar{{margin:12px 0}} .btn{{display:inline-block;background:#1f6feb;color:#fff;
text-decoration:none;border:0;border-radius:5px;padding:7px 12px;margin-right:8px;
font-size:13px;cursor:pointer}} .btn:hover{{background:#1a5fd0}}
.btn.alt{{background:#444}} .btn.alt:hover{{background:#333}} #msg{{color:#0a0;font-size:12px}}
</style></head><body>
<h2>EventFinder &mdash; stocks near a key level</h2>
<p class="meta">Generated {ts.strftime('%Y-%m-%d %H:%M:%S IST')} &middot; Run #{run_n} today &middot; {len(df)} stocks</p>
<p class="meta">{sub}</p>
<div class="bar">
<a class="btn" href="eventfinder://export" onclick="document.getElementById('msg').textContent='Saving to exports/ folder...'">&#128190; Save dated file to folder</a>
<button class="btn alt" onclick="dl('txt')">&#11015; Download .txt (desktop)</button>
<button class="btn alt" onclick="dl('csv')">&#11015; Download .csv (web)</button>
<span id="msg"></span></div>
<p class="hint">Click any column header to sort (click again to reverse).</p>
<table id="t"><tr>{hrow}</tr>
{rows}</table>
<script>
var FY=[{fy_js}];
function pad(n){{return(n<10?'0':'')+n;}}
function ts2(){{var d=new Date();return ''+d.getFullYear()+pad(d.getMonth()+1)+pad(d.getDate())+'_'+pad(d.getHours())+pad(d.getMinutes())+pad(d.getSeconds());}}
function dl(kind){{
  var data=(kind==='csv')?('Symbol\\n'+FY.join('\\n')):FY.join(',');
  var b=new Blob([data],{{type:'text/plain'}});
  var a=document.createElement('a');
  a.href=URL.createObjectURL(b); a.download='fyers_'+ts2()+'.'+kind;
  document.body.appendChild(a); a.click(); a.remove();
}}
var NUM=[0,5,6,7], dir={{}};
function sortTable(c){{
  var t=document.getElementById('t'), rows=Array.prototype.slice.call(t.rows,1);
  var asc=dir[c]!=='asc'; dir={{}}; dir[c]=asc?'asc':'desc';
  var num=NUM.indexOf(c)>=0;
  rows.sort(function(a,b){{
    var x=a.cells[c].innerText.trim(), y=b.cells[c].innerText.trim();
    if(num){{x=parseFloat(x.replace(/[^0-9.\\-]/g,''))||0;
             y=parseFloat(y.replace(/[^0-9.\\-]/g,''))||0; return asc?x-y:y-x;}}
    return asc?x.localeCompare(y):y.localeCompare(x);
  }});
  rows.forEach(function(r){{t.appendChild(r);}});
  var ths=t.rows[0].cells;
  for(var i=0;i<ths.length;i++){{ths[i].getElementsByClassName('arr')[0].textContent='';}}
  ths[c].getElementsByClassName('arr')[0].textContent=asc?'▲':'▼';
}}
</script>
</body></html>"""


def _fyers_symbols(df):
    """Screened symbols in Fyers notation, e.g. NSE:APOLLOHOSP-EQ."""
    return [f"NSE:{s}-EQ" for s in df["symbol"]] if not df.empty else []


def write_fyers(export_dir, df, stamp, prefix=(), new_syms=()):
    """Write Fyers watchlists into `export_dir`:
      * full list   -> stable `latest_fyers.*`     + dated `fyers_<stamp>.*`
      * NEW only    -> stable `latest_fyers_new.*` + dated `fyers_new_<stamp>.*`
    `prefix` symbols (e.g. indices) are pinned at the top of the FULL list only;
    the NEW-only files hold just the stocks added since earlier today (no prefix,
    so you can import only the fresh names). `.txt` = desktop watchlist (one
    comma-separated line), `.csv` = web import. Returns the export folder path."""
    syms = list(prefix) + _fyers_symbols(df)
    line = ",".join(syms)
    csv = "Symbol\n" + "\n".join(syms)
    new_fy = [f"NSE:{s}-EQ" for s in new_syms]
    new_line = ",".join(new_fy)
    new_csv = "Symbol\n" + "\n".join(new_fy)
    os.makedirs(export_dir, exist_ok=True)
    targets = [(os.path.join(export_dir, "latest_fyers.txt"), line),
               (os.path.join(export_dir, "latest_fyers.csv"), csv),
               (os.path.join(export_dir, f"fyers_{stamp}.txt"), line),
               (os.path.join(export_dir, f"fyers_{stamp}.csv"), csv),
               (os.path.join(export_dir, "latest_fyers_new.txt"), new_line),
               (os.path.join(export_dir, "latest_fyers_new.csv"), new_csv),
               (os.path.join(export_dir, f"fyers_new_{stamp}.txt"), new_line),
               (os.path.join(export_dir, f"fyers_new_{stamp}.csv"), new_csv)]
    for path, data in targets:
        with open(path, "w", encoding="ascii") as f:
            f.write(data)
    return export_dir


def _export_dir(cfg):
    return os.path.expanduser(cfg["output"].get("export_dir", "~/Downloads/Watchlist"))


def _write_outputs(outdir, df, new_syms, run_n, ts, prefix=(), export_dir=None):
    """Write per-run + latest CSV / Markdown / HTML to outdir, and the Fyers
    watchlists to export_dir (defaults to outdir). Returns the latest.html path."""
    stamp = ts.strftime("%Y%m%d_%H%M%S")
    df.to_csv(os.path.join(outdir, f"list_{stamp}.csv"), index=False)
    df.to_csv(os.path.join(outdir, "latest.csv"), index=False)

    write_fyers(export_dir or outdir, df, stamp, prefix, new_syms)

    head = (f"# EventFinder near-level list\n\n"
            f"- Generated: {ts.strftime('%Y-%m-%d %H:%M:%S IST')}\n"
            f"- Run #{run_n} today | {len(df)} stocks\n")
    if run_n == 1:
        head += "- First list of the day.\n"
    else:
        head += (f"- **NEW since earlier today ({len(new_syms)}):** "
                 + (", ".join(new_syms) if new_syms else "none") + "\n")
    if df.empty:
        table = "_No matches._"
    else:
        try:
            table = df.to_markdown(index=False)          # needs `tabulate`
        except ImportError:
            table = "```\n" + df.to_string(index=False) + "\n```"
    md = head + "\n" + table + "\n"
    with open(os.path.join(outdir, "latest.md"), "w", encoding="utf-8") as f:
        f.write(md)

    html = _html(df, new_syms, run_n, ts, prefix) if not df.empty else (
        "<html><body><h2>EventFinder</h2><p>No matches.</p></body></html>")
    latest_html = os.path.join(outdir, "latest.html")
    with open(os.path.join(outdir, f"list_{stamp}.html"), "w", encoding="utf-8") as f:
        f.write(html)
    with open(latest_html, "w", encoding="utf-8") as f:
        f.write(html)
    return latest_html


def build_and_notify(cfg, now):
    s = cfg["screener"]
    d = cfg["data"]
    outdir = _abs(cfg["output"]["dir"])
    os.makedirs(outdir, exist_ok=True)
    day = now.strftime("%Y%m%d")

    df = screen_levels.run(target=s["target"], tol=s["tol"],
                           indir=_abs(d["daily_dir"]), base_dir=_abs(d["base_dir"]),
                           left=s["left"], right=s["right"], big_mult=s["big_mult"])
    cur = df["symbol"].tolist() if not df.empty else []

    sp = _state_path(outdir, day)
    if os.path.exists(sp):
        with open(sp, "r", encoding="utf-8") as f:
            st = json.load(f)
    else:
        st = {"runs": 0, "seen": []}
    run_n = st["runs"] + 1
    seen = set(st["seen"])
    new_syms = [x for x in cur if x not in seen]

    prefix = cfg["output"].get("watchlist_prefix", []) or []
    latest_html = _write_outputs(outdir, df, new_syms, run_n, now, prefix,
                                 _export_dir(cfg))

    st["runs"] = run_n
    st["seen"] = sorted(seen | set(cur))
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(st, f, indent=2)

    if cfg["output"].get("notify", True):
        if run_n == 1:
            notify("EventFinder: stock list ready",
                   f"{len(cur)} stocks near key levels")
        else:
            preview = ", ".join(new_syms[:8]) + ("…" if len(new_syms) > 8 else "")
            head = (f"{len(new_syms)} NEW: {preview}" if new_syms
                    else "No new stocks")
            notify(f"EventFinder: {head}", f"Full list {len(cur)} stocks")

    if cfg["output"].get("auto_open", False):
        try:
            os.startfile(latest_html)        # noqa: pylint - Windows-only
        except Exception:                    # noqa: BLE001
            pass
    print(f"List run #{run_n}: {len(cur)} stocks, {len(new_syms)} new -> {latest_html}")


# --------------------------------------------------------------------------- #
def main():
    p = argparse.ArgumentParser(description="One scheduled EventFinder run.")
    p.add_argument("--config", default="config.yml")
    p.add_argument("--list", action="store_true",
                   help="Force an intraday-style list run regardless of the clock.")
    p.add_argument("--eod", action="store_true",
                   help="Force a full EOD update regardless of the clock.")
    p.add_argument("--force", action="store_true",
                   help="Run even on battery (skip the 'Run now' battery prompt).")
    args = p.parse_args()

    cfg = load_config(args.config)
    tz = timezone(timedelta(minutes=cfg["market"]["tz_offset_minutes"]))
    now = datetime.now(tz)

    if args.eod:
        phase = "eod"
    elif args.list:
        phase = "intraday"
    else:
        # Auto (a real scheduled tick / logon catch-up): markets are shut on
        # weekends, so there is nothing to do -- skip entirely.
        if cfg["market"].get("trading_days_only", True) and now.weekday() >= 5:
            print(f"EventFinder @ {now.strftime('%Y-%m-%d %H:%M')} IST: weekend, "
                  f"markets closed -- nothing to do. Skipping.")
            return
        phase = market_phase(cfg, now)
        # On battery, don't spend power automatically -- pop a toast with a
        # "Run now" button and let the user decide (--force overrides this).
        if on_battery() and not args.force:
            uri = "eventfinder://runeod" if phase == "eod" else "eventfinder://run"
            what = ("full data update" if phase == "eod"
                    else "stock-list scan")
            notify("EventFinder: on battery — run skipped",
                   f"Plug in, or click Run now to do the {what}.",
                   action=("Run now", uri))
            print(f"EventFinder @ {now.strftime('%Y-%m-%d %H:%M')} IST: on battery "
                  f"-- deferred ({phase}); sent 'Run now' prompt.")
            return

    print("=" * 70)
    print(f"EventFinder run @ {now.strftime('%Y-%m-%d %H:%M:%S')} IST  phase={phase}")
    print("=" * 70)

    if phase == "intraday":
        update_intraday(cfg)
        build_and_notify(cfg, now)
    else:
        update_eod(cfg)
        print("EOD run complete -- no list built (after market hours).")


if __name__ == "__main__":
    main()
