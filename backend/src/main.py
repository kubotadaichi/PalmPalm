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
  GET  /health    - ヘルスチェック
  POST /api/audio - ユーザー音声 → stage1 → stage2 → turn_end

環境変数:
  GEMINI_API_KEY      - Gemini API キー
  GEMINI_MODEL        - テキスト生成モデル (default: gemini-2.5-flash)
  AGITATION_API_URL   - ラズパイの agitation API ベース URL (例: http://raspberrypi.local:8001)
  STAGE2_LEAD_SECONDS - stage1 終了 N 秒前に stage2 生成開始 (default: 3)
"""
import json

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from .two_stage_session import TwoStageSessionManager

load_dotenv()

gemini = TwoStageSessionManager()

app = FastAPI()
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
