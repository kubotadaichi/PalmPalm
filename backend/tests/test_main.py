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


def test_ws_binary_audio_calls_send_audio_chunk(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app

        client = TestClient(app)
        with client.websocket_connect("/ws/session") as ws:
            ws.receive_json()
            ws.send_bytes(b"\x00\x01" * 100)

    mock_manager.send_audio_chunk.assert_awaited()


def test_ws_forwards_audio_chunk_and_turn_complete(mock_manager):
    async def fake_receive():
        yield {"type": "audio_chunk", "data": "AAEC"}
        yield {"type": "turn_complete"}

    mock_manager.receive = fake_receive

    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app

        client = TestClient(app)
        with client.websocket_connect("/ws/session") as ws:
            assert ws.receive_json()["type"] == "session_ready"
            assert ws.receive_json()["type"] == "audio_chunk"
            assert ws.receive_json()["type"] == "turn_complete"
