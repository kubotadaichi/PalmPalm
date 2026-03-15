"""
Gemini Live API を使った占いセッション管理。
- 1ターン = 1つの自然な応答（stage1/stage2 の区別なし）
- get_agitation tool を AI が自律的に呼ぶ
"""
from __future__ import annotations

import base64
import os
import time
from typing import AsyncGenerator

import httpx
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"
AGITATION_API_URL = os.getenv("AGITATION_API_URL", "")

SYSTEM_INSTRUCTION = """\
あなたはAI手相占い師「ぱむぱむ」です。

【基本姿勢】
手の感情線・運命線・頭脳線・生命線を具体的に言及しながら語る。
断言は避け「〜ではないですか」「〜が見えます」という仮説として語る。
神秘的かつ低いトーンで、2〜3文で語る。

【get_agitation ツールの使い方（最重要）】
- 毎ターン必ず1回呼び出すこと
- 呼び出すタイミングは「感情の核心に近づいた」と感じた瞬間（ターンの中盤〜後半）
- 呼び出す前に一般的な読みを展開し、結果を見てから核心を突く
- すぐに「センサーが〜」とは言わない。「体が正直に答えています」程度に留める

【出力】
2〜3文、必ず問いかけで締める。
"""

GET_AGITATION_DECLARATION = types.FunctionDeclaration(
    name="get_agitation",
    description=(
        "ユーザーの手の振動センサーから身体的動揺度を読み取る。"
        "占いの重要なタイミング（感情の核心に触れる直前）で呼び出すこと。"
        "呼び出すタイミング自体が演出の一部。毎ターン1回は必ず呼び出すこと。"
    ),
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)


class LiveSessionManager:
    """Gemini Live API を使った占いセッション管理。"""

    def __init__(
        self,
        agitation_api_url: str = AGITATION_API_URL,
        client: genai.Client | None = None,
    ):
        self.agitation_api_url = agitation_api_url
        self._client = client
        self._session = None
        self._ai_speak_start: float | None = None
        self._text_history: list[dict] = []
        self._ctx = None

    async def connect(self) -> None:
        """Live API セッションを確立する。"""
        if self._client is None:
            self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[types.Tool(function_declarations=[GET_AGITATION_DECLARATION])],
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=100000,
                sliding_window=types.SlidingWindow(target_tokens=80000),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
        )
        self._ctx = self._client.aio.live.connect(model=MODEL, config=config)
        self._session = await self._ctx.__aenter__()

    async def disconnect(self) -> None:
        """セッションを終了する。"""
        if self._ctx:
            await self._ctx.__aexit__(None, None, None)
            self._ctx = None
            self._session = None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """PCM 16kHz mono int16 を Live API へ送信。"""
        self._ai_speak_start = None
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
        )
        await self._session.send_realtime_input(audio_stream_end=True)

    async def receive(self) -> AsyncGenerator[dict, None]:
        """
        受信イベントを yield する:
          {"type": "audio_chunk", "data": "<base64 PCM 24kHz>"}
          {"type": "turn_complete"}
        """
        async for response in self._session.receive():
            audio_data = self._extract_audio_data(response)
            if audio_data:
                if self._ai_speak_start is None:
                    self._ai_speak_start = time.time()
                yield {
                    "type": "audio_chunk",
                    "data": base64.b64encode(audio_data).decode(),
                }

            if response.tool_call:
                for call in response.tool_call.function_calls:
                    await self._handle_tool_call(call)

            if response.server_content and response.server_content.turn_complete:
                yield {"type": "turn_complete"}
                self._ai_speak_start = None

    def _extract_audio_data(self, response) -> bytes | None:
        """Live API レスポンスから音声バイト列を取り出す。"""
        if getattr(response, "data", None):
            return response.data

        server_content = getattr(response, "server_content", None)
        model_turn = getattr(server_content, "model_turn", None)
        parts = getattr(model_turn, "parts", None) or []
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            data = getattr(inline_data, "data", None)
            if data:
                return data
        return None

    async def _handle_tool_call(self, call) -> None:
        """get_agitation tool call を処理してラズパイに問い合わせ、結果を返す。"""
        from_ts = self._ai_speak_start if self._ai_speak_start else time.time() - 3.0
        to_ts = time.time()
        snap = await self._fetch_agitation_window(from_ts, to_ts)
        await self._session.send_tool_response(
            function_responses=[
                types.FunctionResponse(
                    id=call.id,
                    name=call.name,
                    response=snap,
                )
            ]
        )

    async def _fetch_agitation_window(self, from_ts: float, to_ts: float) -> dict:
        """ラズパイの /agitation/window を HTTP 呼び出し。失敗時はデフォルト値を返す。"""
        if not self.agitation_api_url:
            return {"level": 0, "peak": 0, "trend": "stable"}
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                response = await client.get(
                    f"{self.agitation_api_url}/agitation/window",
                    params={"from_ts": from_ts, "to_ts": to_ts},
                )
                return response.json()
        except Exception as exc:
            print(f"[LiveSession] agitation fetch error: {exc}", flush=True)
            return {"level": 0, "peak": 0, "trend": "stable"}
