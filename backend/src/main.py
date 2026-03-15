# Docker コンテナで IPv6 が到達不能な環境向け: DNS 解決で IPv4 のみ返すように上書き
import asyncio
import socket as _socket

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

from .live_session import LiveSessionManager

_orig_getaddrinfo = _socket.getaddrinfo


def _ipv4_only(host, port, family=0, *args, **kwargs):
    results = _orig_getaddrinfo(host, port, family, *args, **kwargs)
    ipv4 = [result for result in results if result[0] == _socket.AF_INET]
    return ipv4 if ipv4 else results


_socket.getaddrinfo = _ipv4_only

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.websocket("/ws/session")
async def ws_session(websocket: WebSocket):
    await websocket.accept()
    manager = LiveSessionManager()
    await manager.connect()
    await websocket.send_json({"type": "session_ready"})

    receive_task = asyncio.create_task(_forward_live_events(websocket, manager))
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                await manager.send_audio_chunk(message["bytes"])
    except WebSocketDisconnect:
        pass
    finally:
        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        await manager.disconnect()


async def _forward_live_events(websocket: WebSocket, manager: LiveSessionManager):
    async for event in manager.receive():
        await websocket.send_json(event)
