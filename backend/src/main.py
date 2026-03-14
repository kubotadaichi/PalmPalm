# Docker コンテナで IPv6 が到達不能な環境向け: DNS 解決で IPv4 のみ返すように上書き
import socket as _socket

_orig_getaddrinfo = _socket.getaddrinfo


def _ipv4_only(host, port, family=0, *args, **kwargs):
    results = _orig_getaddrinfo(host, port, family, *args, **kwargs)
    ipv4 = [result for result in results if result[0] == _socket.AF_INET]
    return ipv4 if ipv4 else results


_socket.getaddrinfo = _ipv4_only

import json
import uuid

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .live_session import LiveSessionManager

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

sessions: dict[str, LiveSessionManager] = {}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/session/start")
async def session_start():
    """Live API セッションを確立し session_id を返す。"""
    session_id = str(uuid.uuid4())
    manager = LiveSessionManager()
    await manager.connect()
    sessions[session_id] = manager
    print(f"[Main] session started: {session_id}", flush=True)
    return {"session_id": session_id}


@app.post("/api/audio")
async def receive_audio(session_id: str, request: Request):
    """PCM 音声を受け取り、Live API 経由で応答を SSE でストリーム返却。"""
    manager = sessions.get(session_id)
    if not manager:
        raise HTTPException(status_code=404, detail="session not found")

    pcm_bytes = await request.body()
    await manager.send_audio(pcm_bytes)

    async def generate():
        async for event in manager.receive():
            yield _sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/session")
async def session_delete(session_id: str):
    """セッションを終了・破棄する。"""
    manager = sessions.pop(session_id, None)
    if manager:
        await manager.disconnect()
    print(f"[Main] session deleted: {session_id}", flush=True)
    return {"ok": True}
