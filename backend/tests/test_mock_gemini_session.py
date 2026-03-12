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


@pytest.mark.asyncio
async def test_receive_audio_broadcasts_script_line():
    """receive_audio は音声を無視して台本の次のセリフを返す"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    mock.set_broadcast_callback(fake_broadcast)
    await mock.start_session()
    mock.stop()  # script_loop を止めて receive_audio だけテスト

    received.clear()

    await mock.receive_audio(b"dummy_audio_bytes", "audio/wav")

    text_msgs = [m for m in received if m["type"] == "ai_text"]
    audio_msgs = [m for m in received if m["type"] == "ai_audio"]
    assert len(text_msgs) >= 1
    assert len(audio_msgs) == 1
    assert audio_msgs[0]["url"].startswith("/audio/")


@pytest.mark.asyncio
async def test_start_session_sends_ai_turn_end():
    """start_session後に ai_turn_end がbroadcastされる"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    mock.set_broadcast_callback(fake_broadcast)
    await mock.start_session()
    mock.stop()

    assert any(m["type"] == "ai_turn_end" for m in received), \
        "ai_turn_end が届いていない"


@pytest.mark.asyncio
async def test_receive_audio_sends_ai_turn_end():
    """receive_audio の応答後に ai_turn_end がbroadcastされる"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    mock.set_broadcast_callback(fake_broadcast)
    await mock.start_session()
    mock.stop()
    received.clear()

    await mock.receive_audio(b"dummy", "audio/wav")

    assert any(m["type"] == "ai_turn_end" for m in received), \
        "receive_audio 後に ai_turn_end が届いていない"
    # ai_turn_end はテキスト送信の後でなければならない
    types = [m["type"] for m in received]
    assert types[-1] == "ai_turn_end", "ai_turn_end が最後のメッセージでない"
