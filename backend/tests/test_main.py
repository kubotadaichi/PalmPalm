"""main.py WebSocket エンドポイントの統合テスト。LiveSessionManager はモック。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def mock_manager():
    manager = MagicMock()
    manager.connect = AsyncMock()
    manager.disconnect = AsyncMock()
    manager.send_audio_chunk = AsyncMock()
    manager.flush_input_audio = AsyncMock()

    async def fake_receive():
        if False:
            yield {}

    manager.receive = fake_receive
    return manager


def test_ws_session_sends_ready_event(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app

        client = TestClient(app)
        with client.websocket_connect("/ws/session") as ws:
            message = ws.receive_json()

    assert message["type"] == "session_ready"
    mock_manager.connect.assert_awaited_once()
