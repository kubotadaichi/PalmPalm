# Docker コンテナで IPv6 が到達不能な環境向け: DNS 解決で IPv4 のみ返すように上書き
import asyncio
import json
import socket as _socket
import traceback

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
    text_frame_count = 0
    stats = {
        "binary_frame_count": 0,
        "forwarded_audio_chunk_count": 0,
        "turn_complete_count": 0,
    }
    await websocket.accept()
    print("[WebSocket] accepted /ws/session", flush=True)
    manager = LiveSessionManager()
    await manager.connect()
    await websocket.send_json({"type": "session_ready"})

    receive_task = asyncio.create_task(_forward_live_events(websocket, manager, stats))
    try:
        while True:
            message = await websocket.receive()
            if message["type"] == "websocket.disconnect":
                break
            if message.get("bytes") is not None:
                stats["binary_frame_count"] += 1
                if stats["binary_frame_count"] % 200 == 0:
                    print(
                        f"[WebSocket] received binary_frame count={stats['binary_frame_count']} "
                        f"bytes={len(message['bytes'])}",
                        flush=True,
                    )
                await manager.send_audio_chunk(message["bytes"])
            if message.get("text") is not None:
                text_frame_count += 1
                payload = json.loads(message["text"])
                message_type = payload.get("type")
                print(
                    f"[WebSocket] received text_frame count={text_frame_count} "
                    f"type={message_type}",
                    flush=True,
                )
                if message_type == "session_end":
                    break
                # input_audio_end は補助経路として残す（通常は Live VAD が処理）
                if message_type == "input_audio_end":
                    await manager.flush_input_audio()
    except WebSocketDisconnect:
        print("[WebSocket] disconnected by client", flush=True)
    except Exception:
        print("[WebSocket] exception\n" + traceback.format_exc(), flush=True)
        raise
    finally:
        print("[WebSocket] closing session", flush=True)
        receive_task.cancel()
        try:
            await receive_task
        except asyncio.CancelledError:
            pass
        await manager.disconnect()


async def _forward_live_events(websocket: WebSocket, manager: LiveSessionManager, stats: dict):
    try:
        async for event in manager.receive():
            event_type = event.get("type")
            if event_type == "audio_chunk":
                stats["forwarded_audio_chunk_count"] += 1
                count = stats["forwarded_audio_chunk_count"]
                if count == 1 or count % 50 == 0:
                    print(
                        "[forward_live_events] forwarded audio_chunk "
                        f"count={count} binary_frames={stats['binary_frame_count']}",
                        flush=True,
                    )
            elif event_type == "turn_complete":
                stats["turn_complete_count"] += 1
                print(
                    "[forward_live_events] forwarded turn_complete "
                    f"count={stats['turn_complete_count']} "
                    f"binary_frames={stats['binary_frame_count']} "
                    f"audio_chunks={stats['forwarded_audio_chunk_count']}",
                    flush=True,
                )
            await websocket.send_json(event)
    except Exception:
        print("[forward_live_events] exception\n" + traceback.format_exc(), flush=True)
        try:
            await websocket.send_json({"type": "error", "message": "セッションエラーが発生しました"})
        except Exception:
            pass
