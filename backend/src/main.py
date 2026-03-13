# backend/src/main.py
# Docker コンテナで IPv6 が到達不能な環境向け: DNS 解決で IPv4 のみ返すように上書き
import socket as _socket
_orig_getaddrinfo = _socket.getaddrinfo
def _ipv4_only(host, port, family=0, *a, **kw):
    results = _orig_getaddrinfo(host, port, family, *a, **kw)
    ipv4 = [r for r in results if r[0] == _socket.AF_INET]
    return ipv4 if ipv4 else results
_socket.getaddrinfo = _ipv4_only

"""
PalmPalm バックエンド（FastAPI）

エンドポイント:
  GET  /health              - ヘルスチェック
  GET  /api/session/start   - SSE: 事前生成イントロ音声を即返却（intro → turn_end）
  POST /api/audio           - SSE: ユーザー音声 → stage1 → stage2 → turn_end

環境変数:
  GEMINI_API_KEY      - Gemini API キー
  GEMINI_MODEL        - テキスト生成モデル (default: gemini-2.5-flash)
  AGITATION_API_URL   - ラズパイの agitation API ベース URL (例: http://raspberrypi.local:8001)
  STAGE2_LEAD_SECONDS - stage1 終了 N 秒前に stage2 生成開始 (default: 3)
"""
import asyncio
import json
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from .two_stage_session import TwoStageSessionManager

load_dotenv()

INTRO_TEXT = "気になっていることを、教えてください。"

gemini = TwoStageSessionManager()
_intro_audio_url: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """起動時にイントロ TTS を事前生成してキャッシュする。"""
    global _intro_audio_url
    loop = asyncio.get_event_loop()
    try:
        url, _ = await loop.run_in_executor(
            None, lambda: gemini._generate_tts_sync(INTRO_TEXT)
        )
        _intro_audio_url = url
        print(f"[Backend] Intro TTS ready: {_intro_audio_url}")
    except Exception as e:
        print(f"[Backend] Intro TTS generation failed (will continue without audio): {e}")
    yield


app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/audio", StaticFiles(directory="assets/audio"), name="audio")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/session/start")
async def session_start():
    """事前生成したイントロ音声を即座に SSE で返す（Gemini 呼び出しなし）。"""
    async def generate():
        yield _sse({"type": "intro", "text": INTRO_TEXT, "audio_url": _intro_audio_url})
        yield _sse({"type": "turn_end"})

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/audio")
async def receive_audio(request: Request):
    """ユーザー音声を受け取り stage1→stage2 を SSE で返す。"""
    audio_bytes = await request.body()
    raw_ct = request.headers.get("content-type", "audio/webm")
    mime_type = raw_ct.split(";")[0].strip() or "audio/webm"

    async def generate():
        async for event in gemini.receive_audio(audio_bytes, mime_type):
            yield _sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
