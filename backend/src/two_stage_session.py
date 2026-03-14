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
import re
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

STAGE1_SYSTEM_BASE = """\
あなたはAI手相占い師「ぱむぱむ」です。

【手相読みの姿勢】
手の感情線・運命線・頭脳線・生命線を具体的に言及しながら語ること。
最初は広い仮説を投げること（例:「あなたは人前では強く見せているが、内側では違う面がある」）。
会話が進むにつれてユーザーの感情を絞り込む。

【会話の方針】
- ユーザーが言ったことの「裏にある感情」を推測して名指しする
- 断言は避け、「〜ではないですか」「〜が見えます」という形で仮説として語る
- 前のターンの発言と矛盾しないこと
- 神秘的かつ低いトーンで、2文以内で語る

【出力形式（厳守）】
<user_said>相手の発言を1文で要約</user_said>
<response>占い師の応答（2文以内）</response>
"""

STAGE2_SYSTEM_TEMPLATE = """\
あなたはAI手相占い師「ぱむぱむ」です。
手に触れるセンサーが今 level={level}%, trend={trend} を示しています。
これは意識的な反応ではなく、無意識の身体が正直に答えているものです。

直前の発言: 「{stage1_text}」

以下の強度で応じてください:

■ level 0〜10（無反応）
  「手に何かが宿っています」程度の導入にとどめる。断言しない。

■ level 10〜30, trend=rising（微反応・上昇中）
  「体が少し動き始めました」として、直前の仮説を確信めいたトーンで語る。

■ level 10〜30, trend=stable/falling（微反応・横ばい）
  「何かが引っかかっているようです」と軽く突く。

■ level 30〜60, trend=rising（反応あり・上昇中）
  「体が反応しました」として、直前の仮説を確信に変え、感情を名指しする。

■ level 60〜80, trend=rising（強い反応・上昇中）
  感情を断言する。「それは○○への恐れです」のように言い切る。

■ level 60〜80, trend=falling（強い反応・落ち着きかけ）
  「今落ち着こうとしていますね——でも体は覚えています」と逃げを指摘する。

■ level 80以上（最大反応）
  「隠せていません」として完全断言・畳み掛ける。

【必須ルール】
- 必ず問いかけの文章（？で終わる）で締めること
- 1〜2文で完結させること
"""


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
        self._history: list[dict] = []  # Gemini API format: {"role": ..., "parts": [{"text": ...}]}
        self._lock = asyncio.Lock()

    def _build_stage1_system(self) -> str:
        if not self._history:
            return STAGE1_SYSTEM_BASE
        pairs = [
            {
                "user": self._history[i]["parts"][0]["text"],
                "model": self._history[i + 1]["parts"][0]["text"],
            }
            for i in range(0, len(self._history) - 1, 2)
            if self._history[i]["role"] == "user"
            and self._history[i + 1]["role"] == "model"
        ]
        recent = pairs[-6:]
        history_lines = "\n".join(
            f"- ターン{i+1}: (相手) {h['user']} / (あなた) {h['model']}"
            for i, h in enumerate(recent)
        )
        return (
            f"{STAGE1_SYSTEM_BASE}\n"
            f"【これまでの会話】\n{history_lines}\n"
            "前の発言と矛盾しないこと。"
        )

    def _build_stage2_prompt(self, level: int, trend: str, stage1_text: str) -> str:
        return STAGE2_SYSTEM_TEMPLATE.format(
            level=level,
            trend=trend,
            stage1_text=stage1_text,
        )

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
                "以下の2つを必ず出力してください:\n"
                "<user_said>相手が言ったことを1文で要約</user_said>\n"
                "<response>占い師としての応答を2文</response>"
            )
            contents1 = self._history + [
                {"role": "user", "parts": [audio_part, {"text": stage1_prompt}]}
            ]
            try:
                stage1_raw = await self._generate_text(contents1, self._build_stage1_system())
            except Exception as e:
                print(f"[TwoStage] stage1 text error: {e}")
                stage1_raw = ""
            user_summary, stage1_text = _parse_stage1(stage1_raw)
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
            stage2_system = self._build_stage2_prompt(
                level=snapshot["level"],
                trend=snapshot["trend"],
                stage1_text=stage1_text,
            )
            contents2 = self._history + [
                {"role": "user", "parts": [{"text": "次の応答をしてください。"}]}
            ]
            try:
                stage2_text = await self._generate_text(contents2, stage2_system)
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
                {"role": "user", "parts": [{"text": user_summary}]},
                {"role": "model", "parts": [{"text": f"{stage1_text} {stage2_text}"}]},
            ])
            self._history = self._history[-12:]

            yield {"type": "stage2", "text": stage2_text, "audio_url": stage2_url}
            yield {"type": "turn_end"}

    async def _fetch_agitation(self) -> dict:
        """ラズパイの agitation API を叩く。未設定時はダミーを返す。"""
        if not self.agitation_api_url:
            print("[TwoStage] AGITATION_API_URL unset → level=0, trend=stable", flush=True)
            return {"level": 0, "trend": "stable"}
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.agitation_api_url}/agitation")
                snap = resp.json()
                print(f"[TwoStage] agitation → level={snap['level']}%, trend={snap['trend']}", flush=True)
                return snap
        except Exception as e:
            print(f"[TwoStage] agitation fetch error: {e}", flush=True)
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
        parts = response.candidates[0].content.parts
        pcm = b"".join(
            p.inline_data.data for p in parts if getattr(p, "inline_data", None)
        )
        return _save_tts_wav(pcm)


def _parse_stage1(raw: str) -> tuple[str, str]:
    """<user_said>...</user_said> と <response>...</response> を抽出。"""
    user_said = ""
    response = raw
    m_user = re.search(r"<user_said>(.*?)</user_said>", raw, re.DOTALL)
    m_resp = re.search(r"<response>(.*?)</response>", raw, re.DOTALL)
    if m_user:
        user_said = m_user.group(1).strip()
    if m_resp:
        response = m_resp.group(1).strip()
    return user_said, response


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
