"""
Detached Windows Service Launcher for Event Finder
=================================================
Spawns web_control_dashboard.py and background_event_manager.py as completely
independent, detached Windows OS processes (DETACHED_PROCESS | CREATE_NO_WINDOW).
They will continue running natively in Windows even after Antigravity or VS Code is closed!
"""

import os
import sys
import subprocess

BASE_DIR = r"C:\DATA\CODE\Stocks\EventFinder"
PYTHON_EXE = sys.executable

# Flags for completely detached windowless process on Windows:
# 0x00000008 = DETACHED_PROCESS
# 0x08000000 = CREATE_NO_WINDOW
DETACHED_FLAGS = 0x00000008 | 0x08000000

def launch_detached_services():
    print("=" * 70)
    print(" LAUNCHING DETACHED WINDOWS BACKGROUND SERVICES")
    print("=" * 70)

    # 1. Launch Web Control Dashboard (Detached)
    p1 = subprocess.Popen(
        [PYTHON_EXE, os.path.join(BASE_DIR, "utils", "web_control_dashboard.py")],
        cwd=BASE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=DETACHED_FLAGS,
        close_fds=True
    )
    print(f"  [SUCCESS] Started Web Dashboard Server (PID: {p1.pid})")

    # 2. Launch Background Event Manager (Detached)
    p2 = subprocess.Popen(
        [PYTHON_EXE, os.path.join(BASE_DIR, "utils", "background_event_manager.py")],
        cwd=BASE_DIR,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=DETACHED_FLAGS,
        close_fds=True
    )
    print(f"  [SUCCESS] Started Background Event Manager (PID: {p2.pid})")
    print("=" * 70)
    print(" These processes are detached from Antigravity and will KEEP RUNNING")
    print(" natively on your laptop even when Antigravity is completely closed!")
    print("=" * 70)

if __name__ == "__main__":
    launch_detached_services()
