"""
Gemini Live APIのモック実装。
MOCK_MODE=true のときに GeminiSessionManager の代わりに使う。
GeminiSessionManager と同じインターフェース(start_session / send_push / set_broadcast_callback)を持つ。
"""

import asyncio
import random

from .agitation_engine import AgitationEngine

# 通常の手相占い台本（神秘的・低トーン）
_READING_SCRIPT = [
    {"text": "あなたの手相には、深い感情線が刻まれています。", "audio": "/audio/line1.m4a"},
    {"text": "生命線は力強く、長い旅路を示しています。", "audio": "/audio/line2.m4a"},
    {"text": "知能線が少し湾曲している。創造性の証です。", "audio": "/audio/line3.m4a"},
    {"text": "小指の付け根に薄い縦線が…コミュニケーション運が高い。", "audio": "/audio/line4.m4a"},
    {"text": "運命線がはっきりと中央を走っている。強い意志を感じます。", "audio": "/audio/line5.m4a"},
    {"text": "太陽線が複数本ある。多才で、人を惹きつける力があります。", "audio": "/audio/line6.m4a"},
]

# 動揺急上昇時の豹変セリフ
_SPIKE_RESPONSES = [
    {"text": "ほら！震えてますよね！？当たったでしょ！！", "audio": "/audio/spike1.m4a"},
    {"text": "手が揺れてる！この反応、隠せないですよ！", "audio": "/audio/spike2.m4a"},
    {"text": "やっぱり！今の線のこと、心当たりがあるでしょ！？", "audio": "/audio/spike3.m4a"},
    {"text": "動揺してますよね？当たりすぎて怖いですか？", "audio": "/audio/spike4.m4a"},
]


class MockGeminiSessionManager:
    def __init__(self, agitation_engine: AgitationEngine):
        self.engine = agitation_engine
        self._broadcast_callback = None
        self._task: asyncio.Task | None = None
        self._vibration_task: asyncio.Task | None = None
        self._running = False

    def set_broadcast_callback(self, callback):
        self._broadcast_callback = callback

    async def start_session(self):
        """台本ループと振動モックをバックグラウンドで起動"""
        self._running = True
        self._task = asyncio.create_task(self._script_loop())
        self._vibration_task = asyncio.create_task(self._vibration_loop())

    def stop(self):
        """テスト用にループを止める"""
        self._running = False
        if self._task:
            self._task.cancel()
        if self._vibration_task:
            self._vibration_task.cancel()

    async def send_push(self, level: int, trend: str):
        """動揺急上昇時の豹変セリフを送信"""
        if not self._broadcast_callback:
            return

        entry = random.choice(_SPIKE_RESPONSES)
        await self._broadcast_callback({"type": "ai_audio", "url": entry["audio"]})
        for chunk in _chunks(entry["text"], size=10):
            await self._broadcast_callback({"type": "ai_text", "text": chunk})
            await asyncio.sleep(0.05)

    async def _script_loop(self):
        """3〜6秒ごとに台本テキストをチャンクで送信。終わったら先頭に戻る"""
        idx = 0
        while self._running:
            # テストが短時間で成立するよう最初の1行は即時送信する
            if idx > 0:
                await asyncio.sleep(random.uniform(3.0, 6.0))
                if not self._running:
                    break
            entry = _READING_SCRIPT[idx % len(_READING_SCRIPT)]
            idx += 1
            if self._broadcast_callback:
                await self._broadcast_callback({"type": "ai_audio", "url": entry["audio"]})
                for chunk in _chunks(entry["text"], size=8):
                    await self._broadcast_callback({"type": "ai_text", "text": chunk})
                    await asyncio.sleep(0.05)

    async def _vibration_loop(self):
        """ランダムに振動イベントを発生させてフロントに配信"""
        while self._running:
            await asyncio.sleep(random.uniform(0.5, 2.0))
            if not self._running:
                break
            self.engine.record_pulse()
            snapshot = self.engine.snapshot()
            if self._broadcast_callback:
                await self._broadcast_callback(
                    {
                        "type": "agitation_update",
                        "level": snapshot["level"],
                        "trend": snapshot["trend"],
                    }
                )


def _chunks(text: str, size: int) -> list[str]:
    """テキストをsize文字単位のチャンクに分割（ストリーミング風）"""
    return [text[i : i + size] for i in range(0, len(text), size)]
