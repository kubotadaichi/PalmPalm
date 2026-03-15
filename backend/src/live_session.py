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
- すぐに「手が反応している」とは言わない。「体が正直に答えています」程度に留める

【出力】
2〜3文、必ず問いかけで締める。
"""

GET_AGITATION_DECLARATION = types.FunctionDeclaration(
    name="get_agitation",
    description=(
        "ユーザーの手から身体的動揺度を読み取る。"
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
        self._sent_audio_chunks = 0
        self._received_audio_chunks = 0
        self._tool_call_count = 0

    async def connect(self) -> None:
        """Live API セッションを確立する。"""
        if self._client is None:
            self._client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[types.Tool(function_declarations=[GET_AGITATION_DECLARATION])],
            input_audio_transcription=types.AudioTranscriptionConfig(),
            realtime_input_config=types.RealtimeInputConfig(
                activity_handling=types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS,
                turn_coverage=types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY,
            ),
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
        # 初手: AI が先に話し始めるよう促す
        await self._session.send_client_content(
            turns={"role": "user", "parts": [{"text": "占いを始めてください。"}]},
            turn_complete=True,
        )
        print(f"[LiveSession] sent initial greeting prompt ts={time.time():.3f}", flush=True)

    async def disconnect(self) -> None:
        """セッションを終了する。"""
        print(
            f"[LiveSession] disconnect ts={time.time():.3f} "
            f"sent_chunks={self._sent_audio_chunks} received_chunks={self._received_audio_chunks}",
            flush=True,
        )
        if self._ctx:
            await self._ctx.__aexit__(None, None, None)
            self._ctx = None
            self._session = None

    async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
        """PCM 16kHz mono int16 の 1 chunk を Live API へ送信。"""
        self._ai_speak_start = None
        self._sent_audio_chunks += 1
        print(
            f"[LiveSession] send_audio_chunk count={self._sent_audio_chunks} "
            f"bytes={len(pcm_bytes)} ts={time.time():.3f}",
            flush=True,
        )
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
        )

    async def flush_input_audio(self) -> None:
        """入力音声の一区切りを Live API へ通知する。"""
        await self._session.send_realtime_input(activity_end=types.ActivityEnd())

    async def start_input_audio(self) -> None:
        """入力音声の開始を Live API へ通知する。"""
        await self._session.send_realtime_input(activity_start=types.ActivityStart())

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """互換用: PCM を 1 回送って flush する。"""
        await self.send_audio_chunk(pcm_bytes)
        await self.flush_input_audio()

    async def receive(self) -> AsyncGenerator[dict, None]:
        """
        受信イベントを yield する:
          {"type": "audio_chunk", "data": "<base64 PCM 24kHz>"}
          {"type": "turn_complete"}

        google-genai SDK の session.receive() は 1 ターン分で終了するため、
        while True でターンをまたいで再呼び出しする。
        """
        while True:
            got_response = False
            async for response in self._session.receive():  # type: ignore[attr-defined]
                got_response = True
                server_content = getattr(response, "server_content", None)
                should_emit_turn_complete = False
                input_transcription = getattr(server_content, "input_transcription", None)
                input_text = getattr(input_transcription, "text", None)
                if input_text:
                    print(
                        f"[LiveSession] input_transcription text={input_text!r} ts={time.time():.3f}",
                        flush=True,
                    )
                if server_content:
                    waiting_for_input = getattr(server_content, "waiting_for_input", None)
                    if waiting_for_input is not None:
                        print(
                            f"[LiveSession] waiting_for_input value={waiting_for_input} ts={time.time():.3f}",
                            flush=True,
                        )
                    interrupted = getattr(server_content, "interrupted", None)
                    if interrupted:
                        print(
                            f"[LiveSession] interrupted ts={time.time():.3f}",
                            flush=True,
                        )
                    generation_complete = getattr(server_content, "generation_complete", None)
                    if generation_complete:
                        print(
                            f"[LiveSession] generation_complete ts={time.time():.3f}",
                            flush=True,
                        )
                        should_emit_turn_complete = True
                    turn_complete_reason = getattr(server_content, "turn_complete_reason", None)
                    if turn_complete_reason:
                        print(
                            f"[LiveSession] turn_complete_reason value={turn_complete_reason} "
                            f"ts={time.time():.3f}",
                            flush=True,
                        )
                audio_data = self._extract_audio_data(response)
                if audio_data:
                    if self._ai_speak_start is None:
                        self._ai_speak_start = time.time()
                    self._received_audio_chunks += 1
                    print(
                        f"[LiveSession] receive_audio_chunk count={self._received_audio_chunks} "
                        f"bytes={len(audio_data)} ts={time.time():.3f}",
                        flush=True,
                    )
                    yield {
                        "type": "audio_chunk",
                        "data": base64.b64encode(audio_data).decode(),
                    }

                if response.tool_call:
                    for call in response.tool_call.function_calls:
                        self._tool_call_count += 1
                        print(
                            f"[LiveSession] receive_tool_call count={self._tool_call_count} "
                            f"name={call.name} ts={time.time():.3f}",
                            flush=True,
                        )
                        await self._handle_tool_call(call)

                if server_content and server_content.turn_complete:
                    should_emit_turn_complete = True

                if should_emit_turn_complete:
                    print(
                        f"[LiveSession] receive_turn_complete ts={time.time():.3f}",
                        flush=True,
                    )
                    yield {"type": "turn_complete"}
                    self._ai_speak_start = None

            if not got_response:
                print(
                    f"[LiveSession] receive got no response, session may have ended ts={time.time():.3f}",
                    flush=True,
                )
                break

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
