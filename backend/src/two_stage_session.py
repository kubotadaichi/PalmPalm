"""
Gemini通常APIを使った2段階応答セッション管理。
- Stage 1: 会話文脈に沿った即時リアクション（TTS付き）
- Stage 2: 動揺スナップショットを踏まえた補足（TTS付き）
SSE AsyncGenerator として各イベントを yield する。
"""

from __future__ import annotations

import asyncio
import base64 as _b64
import io
import os
import uuid
import wave
from pathlib import Path
from typing import AsyncGenerator

import httpx
from google import genai
from google.genai import types
from google.genai.types import HttpOptions

MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_VOICE = "Kore"
STAGE2_LEAD_SECONDS = float(os.getenv("STAGE2_LEAD_SECONDS", "3"))
AGITATION_API_URL = os.getenv("AGITATION_API_URL", "")  # 例: http://raspberrypi.local:8001

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
    def __init__(self, agitation_api_url: str = AGITATION_API_URL, client=None):
        self.agitation_api_url = agitation_api_url
        self.client = client or genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options=HttpOptions(
                timeout=30000,  # ms
                httpx_client=httpx.Client(http2=False, timeout=30),
                httpx_async_client=httpx.AsyncClient(http2=False, timeout=30),
            ),
        )
        self._history: list[dict] = []
        self._lock = asyncio.Lock()

    async def intro(self) -> AsyncGenerator[dict, None]:
        """イントロを生成して SSE イベントを yield する。"""
        prompt = "手相占いを始めます。相手の手を見て、神秘的なイントロを2文で述べてください。"
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        try:
            text = await self._generate_text(contents, STAGE1_SYSTEM)
        except Exception as e:
            print(f"[TwoStage] intro text error: {e}")
            text = ""
        if not text:
            text = "あなたの手のひらには、深い運命の線が刻まれています。今日は特別なものが見えます。"

        try:
            audio_url, _ = await self._generate_tts(text)
        except Exception as e:
            print(f"[TwoStage] intro TTS error: {e}")
            audio_url = None

        self._history.extend([
            {"role": "user", "parts": [{"text": prompt}]},
            {"role": "model", "parts": [{"text": text}]},
        ])
        yield {"type": "intro", "text": text, "audio_url": audio_url}
        yield {"type": "turn_end"}

    async def receive_audio(
        self, audio_bytes: bytes, mime_type: str = "audio/webm"
    ) -> AsyncGenerator[dict, None]:
        """ユーザー音声を受け取り stage1 → stage2 を SSE イベントで yield する。"""
        async with self._lock:
            audio_part = {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": _b64.b64encode(audio_bytes).decode(),
                }
            }

            # Stage 1
            stage1_prompt = (
                "占いの続きを一言ください。"
                "まだ相手を煽りすぎず、神秘的なトーンを維持してください。"
            )
            contents1 = self._history + [
                {"role": "user", "parts": [audio_part, {"text": stage1_prompt}]}
            ]
            try:
                stage1_text = await self._generate_text(contents1, STAGE1_SYSTEM)
            except Exception as e:
                print(f"[TwoStage] stage1 text error: {e}")
                stage1_text = ""
            if not stage1_text:
                stage1_text = "手のひらに、まだ語られていない流れが見えます。"

            try:
                stage1_url, stage1_duration = await self._generate_tts(stage1_text)
            except Exception as e:
                print(f"[TwoStage] stage1 TTS error: {e}")
                stage1_url, stage1_duration = None, 0.0

            yield {"type": "stage1", "text": stage1_text, "audio_url": stage1_url}

            # stage1 再生中に stage2 生成開始するまで待機
            wait_sec = max(0.0, stage1_duration - STAGE2_LEAD_SECONDS)
            if wait_sec > 0:
                await asyncio.sleep(wait_sec)

            # Stage 2（最新動揺度を取得）
            snapshot = await self._fetch_agitation()
            stage2_prompt = (
                f"動揺データ: level={snapshot['level']}, trend={snapshot['trend']}。"
                f"直前の発言: {stage1_text} "
                "この情報を踏まえ、当たっている実感を強める補足をしてください。"
            )
            contents2 = self._history + [
                {"role": "user", "parts": [{"text": stage2_prompt}]}
            ]
            try:
                stage2_text = await self._generate_text(contents2, STAGE2_SYSTEM)
            except Exception as e:
                print(f"[TwoStage] stage2 text error: {e}")
                stage2_text = ""
            if not stage2_text:
                stage2_text = f"揺れは{snapshot['level']}%です。反応がもう答えになっています。"

            try:
                stage2_url, _ = await self._generate_tts(stage2_text)
            except Exception as e:
                print(f"[TwoStage] stage2 TTS error: {e}")
                stage2_url = None

            self._history.extend([
                {"role": "user", "parts": [audio_part]},
                {"role": "model", "parts": [{"text": f"{stage1_text} {stage2_text}"}]},
            ])
            self._history = self._history[-12:]

            yield {"type": "stage2", "text": stage2_text, "audio_url": stage2_url}
            yield {"type": "turn_end"}

    async def _fetch_agitation(self) -> dict:
        """ラズパイの agitation API を叩く。未設定時はダミーを返す。"""
        if not self.agitation_api_url:
            return {"level": 0, "trend": "stable"}
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.agitation_api_url}/agitation")
                return resp.json()
        except Exception as e:
            print(f"[TwoStage] agitation fetch error: {e}")
            return {"level": 0, "trend": "stable"}

    async def _generate_text(self, contents: list, system_instruction: str) -> str:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: self._generate_text_sync(contents, system_instruction),
            ),
            timeout=20.0,
        )

    def _generate_text_sync(self, contents: list, system_instruction: str) -> str:
        response = self.client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_instruction),
        )
        return (getattr(response, "text", "") or "").strip()

    async def _generate_tts(self, text: str) -> tuple[str, float]:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: self._generate_tts_sync(text)),
            timeout=20.0,
        )

    def _generate_tts_sync(self, text: str) -> tuple[str, float]:
        response = self.client.models.generate_content(
            model=TTS_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=TTS_VOICE
                        )
                    )
                ),
            ),
        )
        pcm = _b64.b64decode(response.candidates[0].content.parts[0].inline_data.data)
        return _save_tts_wav(pcm)


def _chunks(text: str, size: int) -> list[str]:
    return [text[i : i + size] for i in range(0, len(text), size)]


TTS_DIR = Path("assets/audio/tts")
TTS_SAMPLE_RATE = 24000


def _pcm_to_wav_bytes(pcm: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _wav_duration(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        return wf.getnframes() / wf.getframerate()


def _save_tts_wav(pcm: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> tuple[str, float]:
    """PCM を WAV として保存し (url_path, duration_sec) を返す。古いファイルは20件超で削除。"""
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(TTS_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    while len(files) >= 20:
        files.pop(0).unlink(missing_ok=True)
    filename = f"tts_{uuid.uuid4().hex}.wav"
    wav_bytes = _pcm_to_wav_bytes(pcm, sample_rate)
    (TTS_DIR / filename).write_bytes(wav_bytes)
    return f"/audio/tts/{filename}", _wav_duration(wav_bytes)
