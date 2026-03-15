"""LiveSessionManager のユニットテスト（Gemini API はモック）。"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.live_session import LiveSessionManager


class FakeToolCall:
    def __init__(self):
        self.id = "call-001"
        self.name = "get_agitation"
        self.args = {}


class FakeToolCallWrapper:
    """live_session.py の `for call in response.tool_call.function_calls` に対応。"""

    def __init__(self, call):
        self.function_calls = [call]


class FakeServerContent:
    def __init__(self, audio_data=None, turn_complete=False):
        self.parts = [MagicMock(inline_data=MagicMock(data=audio_data))] if audio_data else []
        self.model_turn = MagicMock(parts=self.parts) if audio_data else None
        self.turn_complete = turn_complete


class FakeResponse:
    def __init__(self, audio_data=None, tool_call=None, turn_complete=False):
        self.data = audio_data
        self.tool_call = FakeToolCallWrapper(tool_call) if tool_call else None
        self.server_content = FakeServerContent(audio_data, turn_complete)


def make_fake_session(responses):
    """指定した responses を順に返す AsyncContextManager モック。"""
    session = AsyncMock()

    async def fake_receive():
        for response in responses:
            yield response

    session.receive = fake_receive
    session.send_realtime_input = AsyncMock()
    session.send_tool_response = AsyncMock()
    return session


@pytest.fixture
def manager():
    return LiveSessionManager(agitation_api_url="http://localhost:8001")


@pytest.mark.asyncio
async def test_receive_yields_audio_chunk(manager):
    """audio データが来たら audio_chunk イベントを yield する。"""
    pcm = b"\x00\x01" * 100
    responses = [
        FakeResponse(audio_data=pcm),
        FakeResponse(turn_complete=True),
    ]
    fake_session = make_fake_session(responses)
    manager._session = fake_session

    events = []
    async for event in manager.receive():
        events.append(event)

    assert any(event["type"] == "audio_chunk" for event in events)
    assert any(event["type"] == "turn_complete" for event in events)


@pytest.mark.asyncio
async def test_receive_yields_audio_chunk_from_model_turn_parts(manager):
    """response.data が空でも model_turn.parts.inline_data から audio_chunk を取り出す。"""
    pcm = b"\x00\x01" * 100
    responses = [
        FakeResponse(audio_data=None),
        FakeResponse(turn_complete=True),
    ]
    responses[0].server_content = FakeServerContent(audio_data=pcm)
    responses[0].data = None
    fake_session = make_fake_session(responses)
    manager._session = fake_session

    events = []
    async for event in manager.receive():
        events.append(event)

    assert any(event["type"] == "audio_chunk" for event in events)


@pytest.mark.asyncio
async def test_receive_sets_ai_speak_start_on_first_audio(manager):
    """最初の audio chunk 受信時に _ai_speak_start がセットされる。"""
    pcm = b"\x00\x01" * 100
    responses = [FakeResponse(audio_data=pcm), FakeResponse(turn_complete=True)]
    fake_session = make_fake_session(responses)
    manager._session = fake_session
    assert manager._ai_speak_start is None

    receive_iter = manager.receive()
    first_event = await anext(receive_iter)

    assert first_event["type"] == "audio_chunk"
    assert manager._ai_speak_start is not None
    await receive_iter.aclose()


@pytest.mark.asyncio
async def test_receive_resets_ai_speak_start_on_turn_complete(manager):
    """turn_complete 受信後は _ai_speak_start をリセットする。"""
    pcm = b"\x00\x01" * 100
    responses = [FakeResponse(audio_data=pcm), FakeResponse(turn_complete=True)]
    fake_session = make_fake_session(responses)
    manager._session = fake_session

    async for _ in manager.receive():
        pass

    assert manager._ai_speak_start is None


@pytest.mark.asyncio
async def test_receive_handles_tool_call(manager):
    """tool_call を受け取ったら send_tool_response を呼ぶ。"""
    tool_call = FakeToolCall()
    responses = [
        FakeResponse(tool_call=tool_call),
        FakeResponse(turn_complete=True),
    ]
    fake_session = make_fake_session(responses)
    manager._session = fake_session

    with patch.object(manager, "_fetch_agitation_window", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = {"level": 42, "peak": 42, "trend": "rising"}
        async for _ in manager.receive():
            pass

    fake_session.send_tool_response.assert_called_once()


@pytest.mark.asyncio
async def test_send_audio_calls_send_realtime_input(manager):
    """send_audio() は send_realtime_input() を呼ぶ。"""
    fake_session = make_fake_session([])
    manager._session = fake_session
    pcm = b"\x00" * 3200
    await manager.send_audio(pcm)
    first_args, first_kwargs = fake_session.send_realtime_input.await_args_list[0]
    assert not first_args
    assert first_kwargs["audio"].mime_type == "audio/pcm;rate=16000"


@pytest.mark.asyncio
async def test_send_audio_flushes_audio_stream_end(manager):
    """録音バッファ送信後に audio_stream_end=True を送って flush する。"""
    fake_session = make_fake_session([])
    manager._session = fake_session

    await manager.send_audio(b"\x00" * 3200)

    assert fake_session.send_realtime_input.await_count == 2
    _, last_kwargs = fake_session.send_realtime_input.await_args_list[-1]
    assert last_kwargs == {"audio_stream_end": True}
