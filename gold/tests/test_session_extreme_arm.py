"""Today's High/Low arm only after current price has been 2% away — then keep for retest."""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


from gold.xauusd_event_finder import (
    _new_session_arm,
    event_settings,
    session_extreme_levels,
    update_session_extreme_arm,
)


def test_new_low_not_armed_just_because_session_range_is_2pct():
    event_settings(refresh=True)
    armed = _new_session_arm()
    low, high = 4351.12, 4446.54  # session range ~2.2%
    px_at_low = 4355.90  # 0.11% above the low
    update_session_extreme_arm(armed, high, low, px_at_low)
    levels = session_extreme_levels(high, low, px_at_low, armed)
    names = [l["name"] for l in levels]
    assert "Today's Low" not in names


def test_todays_low_arms_after_2pct_rally_and_stays_for_retest():
    event_settings(refresh=True)
    armed = _new_session_arm()
    low, high = 4351.12, 4446.54
    update_session_extreme_arm(armed, high, low, 4355.90)
    assert armed["low"] is None

    rally = low * 1.021
    update_session_extreme_arm(armed, high, low, rally)
    assert armed["low"] == low
    names = [l["name"] for l in session_extreme_levels(high, low, rally, armed)]
    assert "Today's Low" in names

    retest = 4355.90
    update_session_extreme_arm(armed, high, low, retest)
    names = [l["name"] for l in session_extreme_levels(high, low, retest, armed)]
    assert "Today's Low" in names


def test_new_lower_low_starts_unarmed():
    event_settings(refresh=True)
    armed = _new_session_arm()
    low = 4351.12
    update_session_extreme_arm(armed, 4446.54, low, low * 1.021)
    assert armed["low"] == low
    new_low = 4315.55
    update_session_extreme_arm(armed, 4446.54, new_low, new_low + 4)
    assert armed["low"] is None
    names = [l["name"] for l in session_extreme_levels(4446.54, new_low, new_low + 4, armed)]
    assert "Today's Low" not in names
