import asyncio
from unittest.mock import AsyncMock

import pytest

from src.agitation_engine import AgitationEngine
from src.mock_gemini_session import MockGeminiSessionManager


@pytest.mark.asyncio
async def test_start_session_calls_broadcast():
    """start_session後、ai_textがbroadcastされる"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    mock.set_broadcast_callback(fake_broadcast)
    await mock.start_session()

    # 少し待ってメッセージが届くか確認
    await asyncio.sleep(0.1)
    mock.stop()

    assert any(m["type"] == "ai_text" for m in received)


@pytest.mark.asyncio
async def test_send_push_broadcasts_spike_text():
    """send_push後、豹変セリフがbroadcastされる"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    mock.set_broadcast_callback(fake_broadcast)
    await mock.start_session()
    await mock.send_push(level=80, trend="rising")

    await asyncio.sleep(0.1)
    mock.stop()

    texts = [m["text"] for m in received if m["type"] == "ai_text"]
    assert any(texts), "豹変セリフが届いていない"


@pytest.mark.asyncio
async def test_set_broadcast_callback():
    """set_broadcast_callbackで登録したコールバックが使われる"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    cb = AsyncMock()
    mock.set_broadcast_callback(cb)
    await mock.start_session()
    await asyncio.sleep(0.1)
    mock.stop()

    assert cb.called


@pytest.mark.asyncio
async def test_start_session_sends_ai_audio():
    """台本テキストに対応する ai_audio が broadcast される"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    mock.set_broadcast_callback(fake_broadcast)
    await mock.start_session()
    await asyncio.sleep(0.3)
    mock.stop()

    audio_msgs = [m for m in received if m["type"] == "ai_audio"]
    assert len(audio_msgs) >= 1
    assert audio_msgs[0]["url"].startswith("/audio/line")
    assert audio_msgs[0]["url"].endswith(".m4a")


@pytest.mark.asyncio
async def test_send_push_sends_ai_audio():
    """send_push で spike 用 ai_audio が broadcast される"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    mock.set_broadcast_callback(fake_broadcast)
    await mock.start_session()
    await mock.send_push(level=80, trend="rising")
    await asyncio.sleep(0.1)
    mock.stop()

    audio_msgs = [m for m in received if m["type"] == "ai_audio"]
    assert any(m["url"].startswith("/audio/spike") for m in audio_msgs)
