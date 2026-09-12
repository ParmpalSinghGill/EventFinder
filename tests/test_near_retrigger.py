"""NEAR re-alert: 0.40% re-arm, or 1 hour while still inside 0.40%."""

import xauusd_event_finder as xf


def _scan(captured, state, ts, px, high=None, low=None):
    xf.event_settings(refresh=True)
    level = {
        "id": "PDH_100.00",
        "name": "Prev Day High (PDH)",
        "timeframe": "PrevDay",
        "type": "resistance",
        "price": 100.0,
    }
    xf._scan_bar_for_events(
        [level], state, px, ts, 0.0020, [], False, False, False,
        high if high is not None else px,
        low if low is not None else px,
        allow_rearm=True,
    )
    return captured


def _patch_capture():
    captured = []

    def _capture(evt, new_events, show_events, send_alerts):
        new_events.append(evt)
        captured.append((evt["timestamp"], evt["status"]))

    xf._fire_event = _capture
    return captured


def test_near_again_after_one_hour_while_still_inside():
    captured = _patch_capture()
    state = {}
    _scan(captured, state, "2026-09-08 10:00:00", 99.85)
    _scan(captured, state, "2026-09-08 10:30:00", 99.85)
    _scan(captured, state, "2026-09-08 10:59:00", 99.85)
    _scan(captured, state, "2026-09-08 11:00:00", 99.85)
    assert captured == [
        ("2026-09-08 10:00:00", "NEAR"),
        ("2026-09-08 11:00:00", "NEAR"),
    ]


def test_no_near_if_stays_inside_040_and_back_before_one_hour():
    captured = _patch_capture()
    state = {}
    _scan(captured, state, "2026-09-08 10:00:00", 99.85)
    _scan(captured, state, "2026-09-08 10:10:00", 99.70)
    _scan(captured, state, "2026-09-08 10:20:00", 99.85)
    assert captured == [("2026-09-08 10:00:00", "NEAR")]


def test_near_again_if_left_040_and_returned_within_hour():
    captured = _patch_capture()
    state = {}
    _scan(captured, state, "2026-09-08 10:00:00", 99.85)
    _scan(captured, state, "2026-09-08 10:10:00", 99.55)
    _scan(captured, state, "2026-09-08 10:20:00", 99.85)
    assert captured == [
        ("2026-09-08 10:00:00", "NEAR"),
        ("2026-09-08 10:20:00", "NEAR"),
    ]


def test_near_again_if_left_band_and_returned_after_one_hour():
    captured = _patch_capture()
    state = {}
    _scan(captured, state, "2026-09-08 10:00:00", 99.85)
    _scan(captured, state, "2026-09-08 10:10:00", 99.50)
    _scan(captured, state, "2026-09-08 11:05:00", 99.85)
    assert captured == [
        ("2026-09-08 10:00:00", "NEAR"),
        ("2026-09-08 11:05:00", "NEAR"),
    ]


def test_touch_stops_hourly_near():
    captured = _patch_capture()
    state = {}
    _scan(captured, state, "2026-09-08 10:00:00", 99.85)
    _scan(captured, state, "2026-09-08 10:05:00", 100.02, high=100.02, low=99.90)
    _scan(captured, state, "2026-09-08 11:05:00", 99.85)
    assert captured == [
        ("2026-09-08 10:00:00", "NEAR"),
        ("2026-09-08 10:05:00", "TOUCH"),
    ]
