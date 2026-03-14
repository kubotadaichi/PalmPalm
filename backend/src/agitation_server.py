from fastapi import FastAPI

from .agitation_engine import AgitationEngine

engine = AgitationEngine(window_seconds=10, max_pulses=5)

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/agitation")
def get_agitation():
    return engine.snapshot()


@app.post("/pulse")
def post_pulse():
    engine.record_pulse()
    return {"ok": True}
