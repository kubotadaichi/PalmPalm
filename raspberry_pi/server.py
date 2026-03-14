"""
ラズパイ用 agitation サーバー

振動センサー検知時: POST /pulse
動揺度取得:         GET  /agitation

起動: uvicorn server:app --host 0.0.0.0 --port 8001
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from agitation_engine import AgitationEngine

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

engine = AgitationEngine(window_seconds=10, max_pulses=5)


@app.post("/pulse")
async def record_pulse():
    """振動センサー検知時に呼ぶ。GPIO スクリプトから叩く。"""
    engine.record_pulse()
    print(f"[Agitation] pulse received → level={engine.level}%", flush=True)
    return {"ok": True}


@app.get("/agitation")
async def get_agitation():
    snap = engine.snapshot()
    print(f"[Agitation] snapshot → level={snap['level']}%, trend={snap['trend']}", flush=True)
    return snap
