# backend/src/main.py
"""
PalmPalm バックエンド（FastAPI）

エンドポイント:
  GET  /health         - ヘルスチェック
  WS   /ws/sensor      - ラズパイ振動センサー受信
  WS   /ws/frontend    - フロントエンドへのリアルタイム配信

環境変数:
  GEMINI_API_KEY  - Gemini APIキー
  MOCK_MODE       - "true" のときランダム振動モックを有効化
"""
import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv

from .agitation_engine import AgitationEngine
from .mock_gemini_session import MockGeminiSessionManager
from .two_stage_session import TwoStageSessionManager

load_dotenv()

engine = AgitationEngine(window_seconds=10, max_pulses=20)
_mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
gemini = MockGeminiSessionManager(engine) if _mock_mode else TwoStageSessionManager(engine)
frontend_clients: list[WebSocket] = []


async def broadcast_to_frontend(data: dict):
    """接続中の全フロントエンドクライアントにJSONを送信"""
    for ws in frontend_clients[:]:
        try:
            await ws.send_json(data)
        except Exception:
            if ws in frontend_clients:
                frontend_clients.remove(ws)


@asynccontextmanager
async def lifespan(app: FastAPI):
    gemini.set_broadcast_callback(broadcast_to_frontend)
    if _mock_mode:
        await gemini.start_session()
        print("[Backend] Mock mode - MockGeminiSessionManager started")
    else:
        try:
            await gemini.start_session()
            print("[Backend] Two-stage Gemini session manager started")
        except Exception as e:
            print(f"[Backend] Failed to start two-stage session manager: {e}")
    yield


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "mock_mode": os.getenv("MOCK_MODE", "false").lower() == "true",
        "frontend_clients": len(frontend_clients)
    }


@app.websocket("/ws/sensor")
async def sensor_ws(websocket: WebSocket):
    """ラズパイからの振動データを受信する"""
    await websocket.accept()
    print("[Sensor WS] Raspberry Pi connected")
    try:
        while True:
            data = await websocket.receive_text()
            if data.strip() == "1":
                engine.record_pulse()
                snapshot = engine.snapshot()
                await broadcast_to_frontend({
                    "type": "agitation_update",
                    "level": snapshot["level"],
                    "trend": snapshot["trend"]
                })
                # 急上昇チェック: Push割り込みを送る
                if engine.is_spike():
                    asyncio.create_task(
                        gemini.send_push(snapshot["level"], snapshot["trend"])
                    )
    except WebSocketDisconnect:
        print("[Sensor WS] Raspberry Pi disconnected")


@app.websocket("/ws/frontend")
async def frontend_ws(websocket: WebSocket):
    """フロントエンドへのリアルタイム配信WebSocket"""
    await websocket.accept()
    frontend_clients.append(websocket)
    print(f"[Frontend WS] Client connected (total: {len(frontend_clients)})")
    try:
        while True:
            await websocket.receive_text()  # keep-alive ping受信
    except WebSocketDisconnect:
        if websocket in frontend_clients:
            frontend_clients.remove(websocket)
        print(f"[Frontend WS] Client disconnected (total: {len(frontend_clients)})")
