"""Register logon startup and start the dashboard + event loop if they are down."""

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UTILS = ROOT / "utils"
VBS = UTILS / "start_event_finders_background.vbs"
LOG_DIR = UTILS / "logs"
STARTUP_DIR = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
SHORTCUT = STARTUP_DIR / "EventFinderBackground.lnk"
STALE = [
    STARTUP_DIR / "EventFinderBackground.lnk",
    STARTUP_DIR / "start_event_finders_background.vbs",
    ROOT / "start_event_finders_background.vbs",
]


def _pythonw() -> str:
    conda = Path(r"C:\Users\parmp\anaconda3\pythonw.exe")
    if conda.exists():
        return str(conda)
    sibling = Path(sys.executable).with_name("pythonw.exe")
    if sibling.exists():
        return str(sibling)
    return sys.executable


def write_shortcut() -> None:
    STARTUP_DIR.mkdir(parents=True, exist_ok=True)
    target = str(VBS)
    work = str(ROOT)
    # COM shortcut: WorkingDirectory must be EventFinder so relative gold/stock paths resolve.
    cmd = (
        "$s = (New-Object -COM WScript.Shell).CreateShortcut('"
        + str(SHORTCUT).replace("'", "''")
        + "'); "
        "$s.TargetPath = '" + target.replace("'", "''") + "'; "
        "$s.WorkingDirectory = '" + work.replace("'", "''") + "'; "
        "$s.WindowStyle = 7; "
        "$s.Description = 'EventFinder dashboard and gold/stock loop'; "
        "$s.Save()"
    )
    subprocess.run(["powershell", "-NoProfile", "-Command", cmd], check=True, cwd=str(ROOT))
    print(f"  Shortcut: {SHORTCUT}")
    print(f"  Target:   {VBS}")
    print(f"  Workdir:  {ROOT}")


def port_open(port: int = 5050) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(1)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def start_now() -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)
    py = _pythonw()
    flags = 0x00000008 | 0x08000000  # DETACHED_PROCESS | CREATE_NO_WINDOW
    if not port_open(5050):
        subprocess.Popen(
            [py, str(UTILS / "web_control_dashboard.py")],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        print("  Started web_control_dashboard.py")
    else:
        print("  Dashboard already listening on http://localhost:5050")

    running = _manager_running()
    if not running:
        subprocess.Popen(
            [py, str(UTILS / "background_event_manager.py")],
            cwd=str(ROOT),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
            close_fds=True,
        )
        print("  Started background_event_manager.py")
    else:
        print("  Background event manager already running")

    for _ in range(20):
        if port_open(5050):
            print("  Dashboard is up: http://localhost:5050")
            return
        time.sleep(0.25)
    print("  Warning: port 5050 not open yet. Check utils/logs/dashboard.log")


def _manager_running() -> bool:
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" | "
             "Select-Object -ExpandProperty CommandLine"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return False
    return "background_event_manager.py" in (out or "")


def main() -> int:
    os.chdir(ROOT)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    print("EventFinder startup install")
    print(f"  Root: {ROOT}")
    write_shortcut()
    start_now()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[ERROR] {exc}")
        raise SystemExit(1)
