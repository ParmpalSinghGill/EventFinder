"""
Install / restart / remove the Windows scheduled tasks that drive EventFinder.

It reads run_times from config.yml and registers (under Task Scheduler folder
"EventFinder"):
    * EventFinder\\Logon        - runs once at every user logon (i.e. when you
                                  start using the PC), to catch up.
    * EventFinder\\Time_HHMM    - one task per configured run time, daily.

All tasks launch run_screener.bat (generated here with this env's python baked
in), which calls scheduler_run.py and logs to data/screener_output/run.log.

Usage (inside the STOCK env):
    conda run -n STOCK python manage_scheduler.py install     # first-time setup
    conda run -n STOCK python manage_scheduler.py restart     # re-apply config.yml
    conda run -n STOCK python manage_scheduler.py status
    conda run -n STOCK python manage_scheduler.py uninstall
    conda run -n STOCK python manage_scheduler.py run-now     # run once, right now

THE RESTART SWITCH: after changing run_times in config.yml, run `restart`. Tasks
are re-created from the new times, so a newly-added time fires TODAY (if it
hasn't passed) and every following day.
"""

import os
import subprocess
import sys

import yaml

BASE = os.path.dirname(os.path.abspath(__file__))
FOLDER = "EventFinder"
PYEXE = sys.executable                     # the STOCK env python running this
BAT = os.path.join(BASE, "run_screener.bat")
MC_BAT = os.path.join(BASE, "run_moneycontrol.bat")
VBS = os.path.join(BASE, "run_screener.vbs")
MC_VBS = os.path.join(BASE, "run_moneycontrol.vbs")
LOGDIR = os.path.join(BASE, "data", "screener_output")
STARTUP_DIR = os.path.join(os.environ.get("APPDATA", ""),
                           r"Microsoft\Windows\Start Menu\Programs\Startup")
STARTUP_VBS = os.path.join(STARTUP_DIR, "EventFinder_Startup.vbs")
OPEN_BAT = os.path.join(BASE, "open_latest.bat")
LATEST_HTML = os.path.join(LOGDIR, "latest.html")
PROTO_KEY = r"HKCU\Software\Classes\eventfinder"   # clickable-toast handler


def load_times():
    with open(os.path.join(BASE, "config.yml"), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return [str(t) for t in cfg.get("run_times", [])]


def load_moneycontrol_times():
    with open(os.path.join(BASE, "config.yml"), "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    return [str(t) for t in cfg.get("moneycontrol_run_times", [])]


def write_bat():
    os.makedirs(LOGDIR, exist_ok=True)
    content = (
        "@echo off\r\n"
        f'cd /d "{BASE}"\r\n'
        f'"{PYEXE}" "{os.path.join(BASE, "scheduler_run.py")}" '
        f'>> "{os.path.join(LOGDIR, "run.log")}" 2>&1\r\n'
    )
    with open(BAT, "w", encoding="ascii") as f:
        f.write(content)
    print(f"Wrote launcher: {BAT}")


def write_moneycontrol_bat():
    os.makedirs(LOGDIR, exist_ok=True)
    content = (
        "@echo off\r\n"
        f'cd /d "{BASE}"\r\n'
        f'"{PYEXE}" "{os.path.join(BASE, "scrape_moneycontrol_stocks.py")}" '
        f'>> "{os.path.join(LOGDIR, "run_moneycontrol.log")}" 2>&1\r\n'
    )
    with open(MC_BAT, "w", encoding="ascii") as f:
        f.write(content)
    print(f"Wrote Moneycontrol launcher: {MC_BAT}")


def write_vbs():
    vbs = f'CreateObject("WScript.Shell").Run """{BAT}""", 0, False\r\n'
    with open(VBS, "w", encoding="ascii") as f:
        f.write(vbs)
    print(f"Wrote silent launcher: {VBS}")

    mc_vbs = f'CreateObject("WScript.Shell").Run """{MC_BAT}""", 0, False\r\n'
    with open(MC_VBS, "w", encoding="ascii") as f:
        f.write(mc_vbs)
    print(f"Wrote silent Moneycontrol launcher: {MC_VBS}")


def write_startup():
    """Run-at-logon via a hidden launcher in the Startup folder (no admin needed)."""
    if not STARTUP_DIR or not os.path.isdir(STARTUP_DIR):
        print("  (could not locate Startup folder; skipping logon launcher)")
        return
    vbs = (f'CreateObject("WScript.Shell").Run """{BAT}""", 0, False\r\n')
    with open(STARTUP_VBS, "w", encoding="ascii") as f:
        f.write(vbs)
    print(f"  logon launcher  -> {STARTUP_VBS}")


def remove_startup():
    if os.path.exists(STARTUP_VBS):
        os.remove(STARTUP_VBS)
        print(f"  removed logon launcher {STARTUP_VBS}")


def register_protocol():
    """Register the eventfinder:// URL protocol (HKCU, no admin) so clicking the
    toast opens latest.html via open_latest.bat."""
    os.makedirs(LOGDIR, exist_ok=True)
    # Branch on the protocol URI:
    #   eventfinder://export         -> run the exporter
    #   eventfinder://runeod         -> full EOD update now (battery "Run now")
    #   eventfinder://run            -> intraday list run now (battery "Run now")
    #   anything else (…://open)     -> open the HTML list
    # ("runeod" is checked before "run" since it also contains "run".)
    export_py = os.path.join(BASE, "export_watchlist.py")
    sched_py = os.path.join(BASE, "scheduler_run.py")
    runlog = os.path.join(LOGDIR, "run.log")
    lines = [
        "@echo off",
        'set "ARG=%~1"',
        'echo.%ARG%| findstr /I "export" >nul && goto :export',
        'echo.%ARG%| findstr /I "runeod" >nul && goto :runeod',
        'echo.%ARG%| findstr /I "run"    >nul && goto :runlist',
        f'start "" "{LATEST_HTML}"',
        "goto :eof",
        ":export",
        f'"{PYEXE}" "{export_py}"',
        "goto :eof",
        ":runeod",
        f'cd /d "{BASE}"',
        f'"{PYEXE}" "{sched_py}" --eod >> "{runlog}" 2>&1',
        "goto :eof",
        ":runlist",
        f'cd /d "{BASE}"',
        f'"{PYEXE}" "{sched_py}" --list >> "{runlog}" 2>&1',
        "goto :eof",
    ]
    with open(OPEN_BAT, "w", encoding="ascii") as f:
        f.write("\r\n".join(lines) + "\r\n")
    cmd = f'"{OPEN_BAT}" "%1"'
    subprocess.run(["reg", "add", PROTO_KEY, "/ve", "/d",
                    "URL:EventFinder Protocol", "/f"], capture_output=True)
    subprocess.run(["reg", "add", PROTO_KEY, "/v", "URL Protocol", "/d", "", "/f"],
                   capture_output=True)
    r = subprocess.run(["reg", "add", PROTO_KEY + r"\shell\open\command", "/ve",
                        "/d", cmd, "/f"], capture_output=True, text=True)
    print(("  protocol eventfinder:// registered" if r.returncode == 0
           else f"  FAILED protocol -> {r.stderr.strip()}"))


def unregister_protocol():
    subprocess.run(["reg", "delete", PROTO_KEY, "/f"], capture_output=True)
    if os.path.exists(OPEN_BAT):
        os.remove(OPEN_BAT)
    print("  protocol eventfinder:// removed")


def _proto_present():
    r = subprocess.run(["reg", "query", PROTO_KEY], capture_output=True)
    return r.returncode == 0


def _schtasks(args):
    return subprocess.run(["schtasks"] + args, capture_output=True, text=True)


def list_tasks():
    """Return EventFinder task names currently registered."""
    p = _schtasks(["/Query", "/FO", "CSV", "/NH"])
    names = []
    for line in p.stdout.splitlines():
        if not line.strip():
            continue
        name = line.split('","')[0].strip('"').strip()
        if name.startswith("\\" + FOLDER + "\\") or name.startswith(FOLDER + "\\"):
            names.append(name)
    return names


def delete_all():
    for name in list_tasks():
        r = _schtasks(["/Delete", "/TN", name, "/F"])
        print(("  deleted " if r.returncode == 0 else "  FAILED delete ") + name)


def create(name, schedule_args, target_vbs=VBS):
    tn = f"{FOLDER}\\{name}"
    tr = f'wscript.exe "{target_vbs}"'
    args = (["/Create", "/TN", tn, "/TR", tr] + schedule_args
            + ["/IT", "/F"])
    r = _schtasks(args)
    ok = r.returncode == 0
    print(("  created " if ok else "  FAILED  ") + tn +
          ("" if ok else f"  -> {r.stderr.strip() or r.stdout.strip()}"))
    return ok


def harden_settings():
    """schtasks bakes in Windows defaults that break laptop use:
      * DisallowStartIfOnBatteries / StopIfGoingOnBatteries -> the task is
        REFUSED on battery (result 0x800710E0). We want it to START on battery
        so scheduler_run.py can pop its "Run now" toast instead.
      * StartWhenAvailable=False -> a run missed while the PC slept is dropped.
        Turn it on so a missed tick is caught up when the PC wakes.
    These are HKCU tasks, so no admin is needed to adjust them."""
    ps = (
        "$ErrorActionPreference='Stop';"
        f"Get-ScheduledTask -TaskPath '\\{FOLDER}\\' | ForEach-Object {{"
        "$s=$_.Settings;"
        "$s.DisallowStartIfOnBatteries=$false;"
        "$s.StopIfGoingOnBatteries=$false;"
        "$s.StartWhenAvailable=$true;"
        "Set-ScheduledTask -TaskName $_.TaskName -TaskPath $_.TaskPath "
        "-Settings $s | Out-Null}"
    )
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                        "-Command", ps], capture_output=True, text=True)
    print("  settings: run-on-battery + catch-up-missed enabled"
          if r.returncode == 0 else
          f"  FAILED to adjust settings -> {r.stderr.strip()}")


def install():
    write_bat()
    write_moneycontrol_bat()
    write_vbs()
    delete_all()
    remove_startup()
    times = load_times()
    mc_times = load_moneycontrol_times()
    print(f"Registering logon launcher + {len(times)} timed task(s): {times}")
    print(f"Registering {len(mc_times)} Moneycontrol task(s): {mc_times}")
    write_startup()
    register_protocol()
    for t in times:
        hhmm = t.replace(":", "")
        create(f"Time_{hhmm}",
               ["/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/ST", t], VBS)
    for t in mc_times:
        hhmm = t.replace(":", "")
        create(f"Moneycontrol_{hhmm}",
               ["/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/ST", t], MC_VBS)
    harden_settings()
    print("\nDone. Current EventFinder tasks:")
    status()


def status():
    names = list_tasks()
    if not names:
        print("  (no EventFinder tasks registered)")
    for n in names:
        print("  " + n)


def run_now():
    print("Running one pipeline pass now (output below)...")
    # --force so an explicit run-now works even on battery (no "Run now" toast).
    subprocess.run([PYEXE, os.path.join(BASE, "scheduler_run.py"), "--force"])


def main():
    action = (sys.argv[1] if len(sys.argv) > 1 else "status").lower()
    if action in ("install", "restart"):
        install()
    elif action == "uninstall":
        delete_all()
        remove_startup()
        unregister_protocol()
        print("Uninstalled.")
    elif action == "status":
        status()
        print("  logon launcher:",
              "present" if os.path.exists(STARTUP_VBS) else "absent")
        print("  click-to-open protocol:",
              "present" if _proto_present() else "absent")
    elif action in ("run-now", "run_now", "runnow"):
        run_now()
    else:
        print(__doc__)
        print(f"Unknown action: {action!r}. Use install|restart|uninstall|status|run-now.")


if __name__ == "__main__":
    main()
