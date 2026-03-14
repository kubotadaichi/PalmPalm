# backend/src/agitation_engine.py
import time
from collections import deque


class AgitationEngine:
    """
    振動センサーの0/1パルスを受け取り、動揺率(0-100)とトレンドを算出する。
    スライディングウィンドウ（直近N秒）で集計。
    """
    SPIKE_THRESHOLD = 30  # 前回比+30以上で急上昇と判定

    def __init__(self, window_seconds: int = 10, max_pulses: int = 5):
        self.window_seconds = window_seconds
        self.max_pulses = max_pulses
        self._pulses: deque[float] = deque()
        self._previous_level: float = 0

    def record_pulse(self):
        """センサーから1を受け取ったときに呼ぶ"""
        now = time.time()
        self._pulses.append(now)
        self._cleanup()

    def _cleanup(self):
        """ウィンドウ外のパルスを削除"""
        cutoff = time.time() - self.window_seconds
        while self._pulses and self._pulses[0] < cutoff:
            self._pulses.popleft()

    @property
    def level(self) -> int:
        self._cleanup()
        return min(100, int(len(self._pulses) / self.max_pulses * 100))

    @property
    def trend(self) -> str:
        current = self.level
        diff = current - self._previous_level
        if diff > 10:
            return "rising"
        elif diff < -10:
            return "falling"
        return "stable"

    def is_spike(self) -> bool:
        """前回比+30以上で急上昇と判定"""
        return (self.level - self._previous_level) >= self.SPIKE_THRESHOLD

    def snapshot(self) -> dict:
        """Geminiに渡す動揺率スナップショット。呼び出すと_previous_levelが更新される。"""
        current = self.level
        result = {"level": current, "trend": self.trend}
        self._previous_level = float(current)
        return result
