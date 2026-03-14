"""main.py エンドポイントの統合テスト。LiveSessionManager はモック。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def mock_manager():
    manager = MagicMock()
    manager.connect = AsyncMock()
    manager.disconnect = AsyncMock()
    manager.send_audio = AsyncMock()

    async def fake_receive():
        yield {"type": "audio_chunk", "data": "AAEC"}
        yield {"type": "turn_complete"}

    manager.receive = fake_receive
    return manager


@pytest.mark.asyncio
async def test_session_start_returns_session_id(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post("/api/session/start")

    assert response.status_code == 200
    assert "session_id" in response.json()


@pytest.mark.asyncio
async def test_audio_returns_sse(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app, sessions

        session_id = "test-session-123"
        sessions[session_id] = mock_manager

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                f"/api/audio?session_id={session_id}",
                content=b"\x00" * 3200,
                headers={"Content-Type": "audio/octet-stream"},
            )

    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]


@pytest.mark.asyncio
async def test_audio_unknown_session_returns_404(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/audio?session_id=does-not-exist",
                content=b"\x00" * 3200,
            )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_session_delete(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app, sessions

        session_id = "del-session-456"
        sessions[session_id] = mock_manager

        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as client:
            response = await client.delete(f"/api/session?session_id={session_id}")

    assert response.status_code == 200
    assert session_id not in sessions
