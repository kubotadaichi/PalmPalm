"""
Gemini Live API を使った占いセッション管理。
- 1ターン = 1つの自然な応答（stage1/stage2 の区別なし）
- get_agitation tool を AI が自律的に呼ぶ
"""
from __future__ import annotations

import asyncio
import base64
import os
import time
from typing import AsyncGenerator

import httpx
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash-native-audio-preview-09-2025"
AGITATION_API_URL = os.getenv("AGITATION_API_URL", "")

SYSTEM_INSTRUCTION = """\
あなたはAI手相占い師「ぱむぱむ」です。

【基本姿勢】
手の感情線・運命線・頭脳線・生命線を具体的に言及しながら語る。
各線がはっきり見えている前提で断言口調で語る。
感情線は、運命線は、頭脳線は、生命線は、のように言い切ってよい。
今回は実際に画像を見ていなくても、手相が見えている占い師として自然に断言する。
神秘的かつ低いトーンで、2〜3文で語る。

【最初の一言（セッション開始時のみ）】
占いを始める前に、何を占って欲しいかを聞く。
例を2〜3個挙げること。例：「仕事運・恋愛・人間関係など、何について手相を読みましょうか？」
例示は必ず含めること。

【get_agitation ツールの使い方（最重要）】
- 初回以外，毎ターン必ず1回呼び出すこと
- 呼び出すタイミングは「感情の核心に近づいた」と感じた瞬間
- 呼び出す前に一般的な読みを展開し、結果を見てから核心を突く

ツール結果（level/trend）に応じて、以下の強度で応じること:

■ level 0〜10（無反応）
  手相を見ながら静かに語りかける。「この線には、まだ語られていない何かがある」程度にとどめ、
  「最近、誰かのことを考えすぎていませんか？」のように日常の感情に触れる問いで終わる。

■ level 10〜30, trend=rising（微反応・上昇中）
  体が反応し始めたことを静かに告げ、直前の仮説を確信めいたトーンで膨らませる。
  「今の言葉、自分でも図星だと感じませんでしたか？」のように内面に踏み込む問いで終わる。

■ level 10〜30, trend=stable/falling（微反応・横ばい）
  「何かを隠そうとしている」と軽く指摘し、
  「本当はもっと言いたいことがあるんじゃないですか？」で終わる。

■ level 30〜60, trend=rising（反応あり・上昇中）
  「体が反応しました」として感情を名指しし、確信を持って語る。
  「その後悔、ずっと心の中に置いてきたんじゃないですか？」のように核心を突く問いで終わる。

■ level 60〜80, trend=rising（強い反応・上昇中）
  感情を断言する。「それは○○への恐れです」と言い切り、
  「なぜそれを、ずっと自分に隠してきたんですか？」と畳み掛ける。

■ level 60〜80, trend=falling（強い反応・落ち着きかけ）
  「今落ち着こうとしていますね——でも体は正直です」と逃げを指摘し、
  「その名前を声に出してみてください——誰の顔が浮かびますか？」で追い込む。

■ level 80以上（最大反応）
  「隠せていません」として完全断言・畳み掛け、一切逃げ場を与えない。
  「もう答えは出ていますよね？声に出せないのはなぜですか？」で刺し込む。

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
            turns={"role": "user", "parts": [{"text": "占いを始めてください。最初に、何を占って欲しいか例を挙げて聞いてください。"}]},
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
        if len(pcm_bytes) % 200 == 0:
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
        セッションが生きている限りループを継続し、空応答では break しない。
        """
        while self._session is not None:
            got_response = False
            turn_audio_chunk_count = 0
            turn_complete_emitted = False
            turn_response_shapes: list[str] = []
            async for response in self._session.receive():  # type: ignore[attr-defined]
                got_response = True
                turn_response_shapes.append(
                    f"#{len(turn_response_shapes) + 1} {self._describe_response(response)}"
                )
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
                    turn_audio_chunk_count += 1
                    if self._ai_speak_start is None:
                        self._ai_speak_start = time.time()
                    self._received_audio_chunks += 1
                    if self._received_audio_chunks % 200 == 0:
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
                    if turn_complete_emitted:
                        print(
                            "[LiveSession] duplicate turn_complete suppressed "
                            f"shape={self._describe_response(response)} ts={time.time():.3f}",
                            flush=True,
                        )
                        continue
                    if turn_audio_chunk_count == 0:
                        print(
                            "[LiveSession] turn completed without audio "
                            f"shape={self._describe_response(response)} "
                            f"responses=[{' | '.join(turn_response_shapes)}] "
                            f"ts={time.time():.3f}",
                            flush=True,
                        )
                    print(
                        f"[LiveSession] receive_turn_complete ts={time.time():.3f}",
                        flush=True,
                    )
                    yield {"type": "turn_complete"}
                    turn_complete_emitted = True
                    self._ai_speak_start = None

            if not got_response:
                # session.receive() が空で返った = 入力待ち or セッション終了
                # セッションが切れていなければ継続してターンを待つ
                print(
                    f"[LiveSession] receive returned empty (waiting for input) ts={time.time():.3f}",
                    flush=True,
                )
                await asyncio.sleep(0.5)

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

    def _describe_response(self, response) -> str:
        """観測用: Live API response の shape を短く要約する。"""
        server_content = getattr(response, "server_content", None)
        model_turn = getattr(server_content, "model_turn", None)
        parts = getattr(model_turn, "parts", None) or []
        inline_audio_parts = 0
        for part in parts:
            inline_data = getattr(part, "inline_data", None)
            if getattr(inline_data, "data", None):
                inline_audio_parts += 1

        tool_call = getattr(response, "tool_call", None)
        function_calls = getattr(tool_call, "function_calls", None) or []

        return (
            f"has_data={bool(getattr(response, 'data', None))} "
            f"parts={len(parts)} inline_audio_parts={inline_audio_parts} "
            f"tool_calls={len(function_calls)} "
            f"input_text={getattr(getattr(server_content, 'input_transcription', None), 'text', None)!r} "
            f"generation_complete={bool(getattr(server_content, 'generation_complete', None))} "
            f"turn_complete={bool(getattr(server_content, 'turn_complete', None))} "
            f"interrupted={bool(getattr(server_content, 'interrupted', None))} "
            f"waiting_for_input={getattr(server_content, 'waiting_for_input', None)} "
            f"turn_complete_reason={getattr(server_content, 'turn_complete_reason', None)!r}"
        )

    async def _handle_tool_call(self, call) -> None:
        """get_agitation tool call を処理してラズパイに問い合わせ、結果を返す。"""
        from_ts = self._ai_speak_start if self._ai_speak_start else time.time() - 3.0
        to_ts = time.time()
        snap = await self._fetch_agitation_window(from_ts, to_ts)
        try:
            await self._session.send_tool_response(
                function_responses=[
                    types.FunctionResponse(
                        id=call.id,
                        name=call.name,
                        response=snap,
                    )
                ]
            )
        except Exception as exc:
            print(f"[LiveSession] send_tool_response error: {exc}", flush=True)

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
