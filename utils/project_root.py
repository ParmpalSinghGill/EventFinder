"""Project folder, live settings, and a stable working directory."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "utils" / "logs"
LIVE_EVENT_CONFIG = ROOT / "gold" / "data" / "event_config.json"


def ensure_runtime() -> Path:
    """chdir to EventFinder and create the log folder so pythonw can start."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(ROOT)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    return ROOT
