"""
Gemini通常APIを使った2段階応答セッション管理。
- Stage 1: 会話文脈に沿った即時リアクション
- Stage 2: 動揺スナップショットを踏まえた補足
"""

from __future__ import annotations

import asyncio
import base64
import os

from google import genai
from google.genai import types

from .agitation_engine import AgitationEngine

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

STAGE1_SYSTEM = (
    "あなたはAI手相占い師「ぱむぱむ」です。"
    "まずは会話の流れに沿って、低いトーンで神秘的に2文程度で語ってください。"
)

STAGE2_SYSTEM = (
    "あなたはAI手相占い師「ぱむぱむ」です。"
    "動揺データ(level, trend)を踏まえ、占いが当たっている証拠として"
    "テンションを少し上げて1〜2文で追い込みコメントを返してください。"
)


class TwoStageSessionManager:
    def __init__(self, agitation_engine: AgitationEngine, client: genai.Client | None = None):
        self.engine = agitation_engine
        self.client = client or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self._broadcast_callback = None
        self._history: list[dict] = []
        self._lock = asyncio.Lock()

    def set_broadcast_callback(self, callback):
        self._broadcast_callback = callback

    async def start_session(self):
        """初期化のみ。"""
        return

    async def send_intro(self):
        """フロントエンド接続時にGeminiでイントロを生成して送信する。"""
        if not self._broadcast_callback:
            return
        intro_prompt = (
            "手相占いを始めます。相手の手を見て、神秘的なイントロを2文で述べてください。"
        )
        contents = [{"role": "user", "parts": [{"text": intro_prompt}]}]
        intro_text = await self._generate_text(contents, STAGE1_SYSTEM)
        if not intro_text:
            intro_text = "あなたの手のひらには、深い運命の線が刻まれています。今日は特別なものが見えます。"
        await self._broadcast_text(intro_text)
        await self._broadcast_callback({"type": "ai_turn_end"})
        self._history.extend([
            {"role": "user", "parts": [{"text": intro_prompt}]},
            {"role": "model", "parts": [{"text": intro_text}]},
        ])

    async def send_push(self, level: int, trend: str):
        """急上昇イベント時に2段階のテキスト応答を生成して配信。"""
        if not self._broadcast_callback:
            return

        async with self._lock:
            stage1_prompt = (
                "占いの続きを一言ください。"
                "まだ相手を煽りすぎず、神秘的なトーンを維持してください。"
            )
            contents1 = self._history + [{"role": "user", "parts": [{"text": stage1_prompt}]}]
            stage1_text = await self._generate_text(contents1, STAGE1_SYSTEM)
            if not stage1_text:
                stage1_text = "手のひらに、まだ語られていない流れが見えます。"

            stage2_prompt = (
                f"動揺データ: level={level}, trend={trend}。"
                f"直前の発言: {stage1_text}"
                "この情報を踏まえ、当たっている実感を強める補足をしてください。"
            )
            contents2 = self._history + [{"role": "user", "parts": [{"text": stage2_prompt}]}]
            stage2_text = await self._generate_text(contents2, STAGE2_SYSTEM)
            if not stage2_text:
                stage2_text = f"今の揺れは{level}%です。反応がもう答えになっています。"

            await self._broadcast_text(stage1_text)
            await self._broadcast_text(" ")
            await self._broadcast_text(stage2_text)

            self._history.extend(
                [
                    {"role": "user", "parts": [{"text": stage1_prompt}]},
                    {"role": "model", "parts": [{"text": f"{stage1_text} {stage2_text}"}]},
                ]
            )
            # 履歴肥大化を防ぐ
            self._history = self._history[-12:]

    async def receive_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav"):
        """ユーザー音声を受け取りGeminiに渡して2段階応答を生成・broadcast"""
        if not self._broadcast_callback:
            return

        async with self._lock:
            audio_part = {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(audio_bytes).decode(),
                }
            }

            stage1_prompt = (
                "占いの続きを一言ください。"
                "まだ相手を煽りすぎず、神秘的なトーンを維持してください。"
            )
            contents1 = self._history + [
                {"role": "user", "parts": [audio_part, {"text": stage1_prompt}]}
            ]
            stage1_text = await self._generate_text(contents1, STAGE1_SYSTEM)
            if not stage1_text:
                stage1_text = "手のひらに、まだ語られていない流れが見えます。"

            snapshot = self.engine.snapshot()
            stage2_prompt = (
                f"動揺データ: level={snapshot['level']}, trend={snapshot['trend']}。"
                f"直前の発言: {stage1_text}"
                "この情報を踏まえ、当たっている実感を強める補足をしてください。"
            )
            contents2 = self._history + [
                {"role": "user", "parts": [{"text": stage2_prompt}]}
            ]
            stage2_text = await self._generate_text(contents2, STAGE2_SYSTEM)
            if not stage2_text:
                stage2_text = f"揺れは{snapshot['level']}%です。反応がもう答えになっています。"

            await self._broadcast_text(stage1_text)
            await self._broadcast_text(" ")
            await self._broadcast_text(stage2_text)

            self._history.extend([
                {"role": "user", "parts": [audio_part]},
                {"role": "model", "parts": [{"text": f"{stage1_text} {stage2_text}"}]},
            ])
            self._history = self._history[-12:]
            await self._broadcast_callback({"type": "ai_turn_end"})

    async def _generate_text(self, contents: list, system_instruction: str) -> str:
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._generate_text_sync(contents, system_instruction),
        )

    def _generate_text_sync(self, contents: list, system_instruction: str) -> str:
        response = self.client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_instruction),
        )
        text = getattr(response, "text", "") or ""
        return text.strip()

    async def _broadcast_text(self, text: str, size: int = 10):
        for chunk in _chunks(text, size=size):
            await self._broadcast_callback({"type": "ai_text", "text": chunk})
            await asyncio.sleep(0.03)


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]
