"""Project folder and the live settings file both sides read."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE_EVENT_CONFIG = ROOT / "gold" / "data" / "event_config.json"
