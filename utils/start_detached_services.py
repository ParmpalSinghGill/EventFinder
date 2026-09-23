"""
Detached Windows Service Launcher for Event Finder
=================================================
Starts web_control_dashboard.py and background_event_manager.py as detached
Windows processes (no console). Safe to run after the gold/stock/utils split.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from utils.install_startup import start_now

if __name__ == "__main__":
    start_now()
