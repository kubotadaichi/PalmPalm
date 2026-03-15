# backend/tests/test_agitation_engine.py
import time
import pytest
from src.agitation_engine import AgitationEngine


def test_initial_level_is_zero():
    """初期状態では動揺率0"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    assert engine.level == 0


def test_initial_trend_is_stable():
    """初期状態ではtrendはstable"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    assert engine.trend == "stable"


def test_pulse_increases_level():
    """パルスを10回記録すると動揺率50%"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    for _ in range(10):
        engine.record_pulse()
    assert engine.level == 50


def test_level_capped_at_100():
    """最大値は100"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    for _ in range(30):  # max_pulsesを超えても100まで
        engine.record_pulse()
    assert engine.level == 100


def test_trend_rising():
    """前回比+11以上でrising"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 20
    for _ in range(8):  # level=40, diff=+20
        engine.record_pulse()
    assert engine.trend == "rising"


def test_trend_falling():
    """前回比-11以上でfalling"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 80
    for _ in range(3):  # level=15, diff=-65
        engine.record_pulse()
    assert engine.trend == "falling"


def test_trend_stable_small_change():
    """前回比±10以内でstable"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 50
    for _ in range(11):  # level=55, diff=+5
        engine.record_pulse()
    assert engine.trend == "stable"


def test_is_spike_when_jump_over_30():
    """前回比+30以上でis_spike=True"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 10
    for _ in range(18):  # level=90, diff=+80
        engine.record_pulse()
    assert engine.is_spike() is True


def test_is_not_spike_small_jump():
    """前回比+29以下でis_spike=False"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 40
    for _ in range(13):  # level=65, diff=+25
        engine.record_pulse()
    assert engine.is_spike() is False


def test_snapshot_returns_level_and_trend():
    """snapshotはlevelとtrendを含む辞書を返す"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    for _ in range(5):
        engine.record_pulse()
    result = engine.snapshot()
    assert "level" in result
    assert "trend" in result
    assert isinstance(result["level"], int)
    assert result["trend"] in ("rising", "falling", "stable")


def test_snapshot_updates_previous_level():
    """snapshot呼び出し後、_previous_levelが更新される"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    for _ in range(10):
        engine.record_pulse()
    engine.snapshot()
    assert engine._previous_level == 50


def test_calc_trend_rising():
    """_calc_trend: diff > 10 で rising"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 30
    assert engine._calc_trend(50) == "rising"


def test_calc_trend_falling():
    """_calc_trend: diff < -10 で falling"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 60
    assert engine._calc_trend(40) == "falling"


def test_calc_trend_stable():
    """_calc_trend: diff が ±10 以内で stable"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 50
    assert engine._calc_trend(55) == "stable"


def test_snapshot_window_counts_pulses_in_range():
    """指定期間内のパルスのみ集計する"""
    engine = AgitationEngine(window_seconds=60, max_pulses=10)
    before = time.time()
    for _ in range(5):
        engine.record_pulse()
    after = time.time()
    result = engine.snapshot_window(before, after)
    assert result["level"] == 50
    assert result["peak"] == 50
    assert result["trend"] in ("rising", "falling", "stable")


def test_snapshot_window_excludes_out_of_range():
    """ウィンドウ外のパルスは含まない"""
    engine = AgitationEngine(window_seconds=60, max_pulses=10)
    for _ in range(5):
        engine.record_pulse()
    future = time.time() + 1000
    result = engine.snapshot_window(future, future + 1)
    assert result["level"] == 0


def test_snapshot_window_does_not_update_previous_level():
    """snapshot_window は _previous_level を更新しない"""
    engine = AgitationEngine(window_seconds=60, max_pulses=10)
    engine._previous_level = 42.0
    t = time.time()
    for _ in range(5):
        engine.record_pulse()
    engine.snapshot_window(t, time.time())
    assert engine._previous_level == 42.0
