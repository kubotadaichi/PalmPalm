import pytest
from httpx import ASGITransport, AsyncClient

from src.agitation_server import app, engine


@pytest.fixture(autouse=True)
def reset_engine():
    """各テスト前にエンジンをリセット"""
    engine._pulses.clear()
    engine._previous_level = 0


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_agitation_initial():
    """初期状態は level=0, trend=stable"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        resp = await ac.get("/agitation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] == 0
    assert data["trend"] == "stable"


@pytest.mark.asyncio
async def test_pulse_increases_level():
    """POST /pulse を10回叩くと level が上がる"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        for _ in range(10):
            await ac.post("/pulse")
        resp = await ac.get("/agitation")
    data = resp.json()
    assert data["level"] > 0


@pytest.mark.asyncio
async def test_pulse_returns_ok():
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        resp = await ac.post("/pulse")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}


@pytest.mark.asyncio
async def test_agitation_window_empty():
    """ウィンドウ内にパルスなし → level=0"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        import time

        t = time.time()
        resp = await ac.get(f"/agitation/window?from_ts={t}&to_ts={t + 1}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] == 0
    assert "trend" in data
    assert "peak" in data


@pytest.mark.asyncio
async def test_agitation_window_with_pulses():
    """ウィンドウ内にパルスあり → level > 0"""
    import time

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        t_start = time.time()
        for _ in range(5):
            await ac.post("/pulse")
        t_end = time.time()
        resp = await ac.get(f"/agitation/window?from_ts={t_start}&to_ts={t_end}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] > 0
