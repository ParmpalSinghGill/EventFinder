"""NEAR: one alert, then wait for TOUCH or a real pullback past watch_exit."""

import sys
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


import gold.xauusd_event_finder as xf


def _scan(captured, state, ts, px, high=None, low=None, levels=None):
    xf.event_settings(refresh=True)
    if levels is None:
        levels = [{
            "id": "PDH_100.00",
            "name": "Prev Day High (PDH)",
            "timeframe": "PrevDay",
            "type": "resistance",
            "price": 100.0,
        }]
    xf._scan_bar_for_events(
        levels, state, px, ts, 0.0020, [], False, False, False,
        high if high is not None else px,
        low if low is not None else px,
        allow_rearm=True,
    )
    return captured


def _patch_capture():
    captured = []

    def _capture(evt, new_events, show_events, send_alerts):
        new_events.append(evt)
        captured.append((evt["timestamp"], evt["status"], evt.get("level_id")))

    xf._fire_event = _capture
    return captured


def test_no_second_near_while_still_inside():
    captured = _patch_capture()
    state = {}
    _scan(captured, state, "2026-09-08 10:00:00", 99.85)
    _scan(captured, state, "2026-09-08 10:30:00", 99.85)
    _scan(captured, state, "2026-09-08 11:00:00", 99.85)
    _scan(captured, state, "2026-09-17 17:50:48", 99.85)
    assert [c[:2] for c in captured] == [("2026-09-08 10:00:00", "NEAR")]


def test_utc_bar_then_local_live_does_not_double_near():
    captured = _patch_capture()
    state = {}
    _scan(captured, state, "2026-09-17 12:20:00+00:00", 99.85)
    _scan(captured, state, "2026-09-17 17:50:48", 99.85)
    assert [c[:2] for c in captured] == [("2026-09-17 12:20:00+00:00", "NEAR")]


def test_near_again_if_left_040_and_returned():
    captured = _patch_capture()
    state = {}
    _scan(captured, state, "2026-09-08 10:00:00", 99.85)
    _scan(captured, state, "2026-09-08 10:10:00", 99.55)
    _scan(captured, state, "2026-09-08 10:20:00", 99.85)
    assert [c[:2] for c in captured] == [
        ("2026-09-08 10:00:00", "NEAR"),
        ("2026-09-08 10:20:00", "NEAR"),
    ]


def test_touch_stops_near():
    captured = _patch_capture()
    state = {}
    _scan(captured, state, "2026-09-08 10:00:00", 99.85)
    _scan(captured, state, "2026-09-08 10:05:00", 100.02, high=100.02, low=99.90)
    _scan(captured, state, "2026-09-08 11:05:00", 99.85)
    assert [c[:2] for c in captured] == [
        ("2026-09-08 10:00:00", "NEAR"),
        ("2026-09-08 10:05:00", "TOUCH"),
    ]


def test_same_price_daily_and_pdh_send_one_near():
    captured = _patch_capture()
    state = {}
    levels = [
        {
            "id": "D_R_4380.00",
            "name": "Daily Resistance",
            "timeframe": "Daily",
            "type": "resistance",
            "price": 4380.0,
        },
        {
            "id": "PDH_4380.00",
            "name": "Prev Day High (PDH)",
            "timeframe": "PrevDay",
            "type": "resistance",
            "price": 4380.0,
        },
    ]
    _scan(captured, state, "2026-09-17 17:50:48", 4372.0, levels=levels)
    assert len(captured) == 1
    assert captured[0][1] == "NEAR"
    assert state["D_R_4380.00"]["near_triggered"] is True
    assert state["PDH_4380.00"]["near_triggered"] is True
