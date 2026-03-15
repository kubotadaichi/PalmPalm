"""LiveSessionManager のユニットテスト（Gemini API はモック）。"""
import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from google.genai import types

from src.live_session import LiveSessionManager, SYSTEM_INSTRUCTION


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
    def __init__(
        self,
        audio_data=None,
        turn_complete=False,
        generation_complete=False,
        turn_complete_reason=None,
    ):
        self.parts = [MagicMock(inline_data=MagicMock(data=audio_data))] if audio_data else []
        self.model_turn = MagicMock(parts=self.parts) if audio_data else None
        self.turn_complete = turn_complete
        self.generation_complete = generation_complete
        self.turn_complete_reason = turn_complete_reason


class FakeResponse:
    def __init__(
        self,
        audio_data=None,
        tool_call=None,
        turn_complete=False,
        generation_complete=False,
        turn_complete_reason=None,
    ):
        self.data = audio_data
        self.tool_call = FakeToolCallWrapper(tool_call) if tool_call else None
        self.server_content = FakeServerContent(
            audio_data,
            turn_complete,
            generation_complete,
            turn_complete_reason,
        )


def make_fake_session(responses):
    """指定した responses を順に返す AsyncContextManager モック。
    receive() は 1 ターン分を yield して終了する SDK の仕様を再現するため、
    2 回目以降の呼び出しでは空のイテレータを返す（while True ループを終了させる）。
    """
    session = AsyncMock()

    call_count = 0

    async def fake_receive():
        nonlocal call_count
        if call_count > 0:
            return  # 2回目以降は空 → got_response=False → break
        call_count += 1
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
async def test_receive_treats_generation_complete_as_turn_complete(manager):
    pcm = b"\x00\x01" * 100
    responses = [FakeResponse(audio_data=pcm), FakeResponse(generation_complete=True)]
    fake_session = make_fake_session(responses)
    manager._session = fake_session

    events = []
    async for event in manager.receive():
        events.append(event)

    assert any(event["type"] == "turn_complete" for event in events)


@pytest.mark.asyncio
async def test_receive_suppresses_duplicate_turn_complete_in_single_turn(manager):
    fake_session = make_fake_session(
        [
            FakeResponse(generation_complete=True, turn_complete_reason="done"),
            FakeResponse(turn_complete=True, turn_complete_reason="done"),
        ]
    )
    manager._session = fake_session

    receive_iter = manager.receive()
    first_event = await anext(receive_iter)
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(anext(receive_iter), timeout=0.01)
    await receive_iter.aclose()

    assert first_event == {"type": "turn_complete"}


@pytest.mark.asyncio
async def test_receive_logs_turn_complete_without_audio(manager, capsys):
    fake_session = make_fake_session([FakeResponse(generation_complete=True)])
    manager._session = fake_session

    events = []
    receive_iter = manager.receive()
    events.append(await anext(receive_iter))
    await receive_iter.aclose()

    captured = capsys.readouterr()
    assert events == [{"type": "turn_complete"}]
    assert "turn completed without audio" in captured.out


@pytest.mark.asyncio
async def test_receive_logs_all_response_shapes_for_silent_turn(manager, capsys):
    first = FakeResponse()
    first.server_content.input_transcription = MagicMock(text="仕事")
    second = FakeResponse(generation_complete=True)
    fake_session = make_fake_session([first, second])
    manager._session = fake_session

    receive_iter = manager.receive()
    assert await anext(receive_iter) == {"type": "turn_complete"}
    await receive_iter.aclose()

    captured = capsys.readouterr()
    assert "responses=[" in captured.out
    assert "#1" in captured.out
    assert "#2" in captured.out


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
    """録音バッファ送信後に activity_end を送って flush する。"""
    fake_session = make_fake_session([])
    manager._session = fake_session

    await manager.send_audio(b"\x00" * 3200)

    assert fake_session.send_realtime_input.await_count == 2
    _, last_kwargs = fake_session.send_realtime_input.await_args_list[-1]
    assert isinstance(last_kwargs["activity_end"], types.ActivityEnd)


@pytest.mark.asyncio
async def test_send_audio_chunk_sends_single_pcm_chunk(manager):
    fake_session = make_fake_session([])
    manager._session = fake_session

    await manager.send_audio_chunk(b"\x01\x02" * 100)

    fake_session.send_realtime_input.assert_awaited_once()
    _, kwargs = fake_session.send_realtime_input.await_args
    assert kwargs["audio"].mime_type == "audio/pcm;rate=16000"


@pytest.mark.asyncio
async def test_flush_input_audio_sends_audio_stream_end(manager):
    fake_session = make_fake_session([])
    manager._session = fake_session

    await manager.flush_input_audio()

    fake_session.send_realtime_input.assert_awaited_once()
    _, kwargs = fake_session.send_realtime_input.await_args
    assert isinstance(kwargs["activity_end"], types.ActivityEnd)


@pytest.mark.asyncio
async def test_start_input_audio_sends_activity_start(manager):
    fake_session = make_fake_session([])
    manager._session = fake_session

    await manager.start_input_audio()

    fake_session.send_realtime_input.assert_awaited_once()
    _, kwargs = fake_session.send_realtime_input.await_args
    assert isinstance(kwargs["activity_start"], types.ActivityStart)


@pytest.mark.asyncio
async def test_receive_yields_multiple_audio_chunks_in_order(manager):
    pcm1 = b"\x00\x01" * 10
    pcm2 = b"\x02\x03" * 10
    fake_session = make_fake_session(
        [
            FakeResponse(audio_data=pcm1),
            FakeResponse(audio_data=pcm2),
            FakeResponse(turn_complete=True),
        ]
    )
    manager._session = fake_session

    events = []
    async for event in manager.receive():
        events.append(event)

    audio_events = [event for event in events if event["type"] == "audio_chunk"]
    assert len(audio_events) == 2


@pytest.mark.asyncio
async def test_connect_configures_server_side_vad():
    fake_session = AsyncMock()
    fake_ctx = AsyncMock()
    fake_ctx.__aenter__.return_value = fake_session

    fake_client = MagicMock()
    fake_client.aio.live.connect.return_value = fake_ctx

    manager = LiveSessionManager(client=fake_client)

    await manager.connect()

    _, kwargs = fake_client.aio.live.connect.call_args
    config = kwargs["config"]
    realtime_input_config = config.realtime_input_config

    assert kwargs["model"] == "gemini-2.5-flash-native-audio-preview-09-2025"
    assert realtime_input_config is not None
    assert (
        realtime_input_config.activity_handling
        == types.ActivityHandling.START_OF_ACTIVITY_INTERRUPTS
    )
    assert (
        realtime_input_config.turn_coverage
        == types.TurnCoverage.TURN_INCLUDES_ONLY_ACTIVITY
    )

    # automatic_activity_detection は設定しない → Gemini Live API の自動 VAD を有効にする
    assert realtime_input_config.automatic_activity_detection is None


def test_system_instruction_uses_assertive_palm_reading():
    assert "断言を避け" not in SYSTEM_INSTRUCTION
    assert "各線がはっきり見えている前提で断言口調で語る" in SYSTEM_INSTRUCTION
    assert "感情線は" in SYSTEM_INSTRUCTION
