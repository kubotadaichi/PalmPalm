from fastapi import FastAPI

from .agitation_engine import AgitationEngine

engine = AgitationEngine(window_seconds=15, max_pulses=5)

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/agitation")
def get_agitation():
    snap = engine.snapshot()
    print(f"[Agitation] snapshot → level={snap['level']}%, trend={snap['trend']}", flush=True)
    return snap


@app.get("/agitation/window")
def get_agitation_window(from_ts: float, to_ts: float):
    snap = engine.snapshot_window(from_ts, to_ts)
    print(
        f"[Agitation] window({from_ts:.1f},{to_ts:.1f}) → level={snap['level']}%, trend={snap['trend']}",
        flush=True,
    )
    return snap


@app.post("/pulse")
def post_pulse():
    engine.record_pulse()
    print(f"[Agitation] pulse received → level={engine.level}%", flush=True)
    return {"ok": True}
