import base64
import io
import wave
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from src.agitation_engine import AgitationEngine
from src.two_stage_session import TwoStageSessionManager, _pcm_to_wav_bytes, _save_tts_wav, _wav_duration


class _FakeModels:
    def __init__(self, responses: list[str]):
        self._responses = responses
        self.calls = 0

    def generate_content(self, model, contents, config):
        _ = (model, contents, config)
        text = self._responses[self.calls] if self.calls < len(self._responses) else ""
        self.calls += 1
        return SimpleNamespace(text=text)


class _FakeClient:
    def __init__(self, responses: list[str]):
        self.models = _FakeModels(responses)


@pytest.mark.asyncio
async def test_send_push_broadcasts_two_stage_text():
    engine = AgitationEngine()
    client = _FakeClient(["stage1 message", "stage2 follow up"])
    manager = TwoStageSessionManager(engine, client=client)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    manager.set_broadcast_callback(fake_broadcast)
    await manager.start_session()
    await manager.send_push(level=75, trend="rising")

    text = "".join(m["text"] for m in received if m["type"] == "ai_text")
    assert "stage1 message" in text
    assert "stage2 follow up" in text
    assert client.models.calls == 2


@pytest.mark.asyncio
async def test_send_push_without_callback_is_noop():
    engine = AgitationEngine()
    client = _FakeClient(["unused-1", "unused-2"])
    manager = TwoStageSessionManager(engine, client=client)

    await manager.start_session()
    await manager.send_push(level=60, trend="stable")

    assert client.models.calls == 0


@pytest.mark.asyncio
async def test_receive_audio_broadcasts_gemini_response():
    """receive_audio はGeminiに音声を渡し、テキスト応答をbroadcastする"""
    engine = AgitationEngine()
    client = _FakeClient(["占いの応答です。", "動揺データ踏まえた追い込み。"])
    manager = TwoStageSessionManager(engine, client=client)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    manager.set_broadcast_callback(fake_broadcast)
    await manager.start_session()
    await manager.receive_audio(b"fake_wav_bytes", "audio/wav")

    text = "".join(m["text"] for m in received if m["type"] == "ai_text")
    assert "占いの応答です。" in text
    assert client.models.calls == 2


@pytest.mark.asyncio
async def test_receive_audio_without_callback_is_noop():
    """broadcast callback が未設定なら何も起きない"""
    engine = AgitationEngine()
    client = _FakeClient(["unused", "unused"])
    manager = TwoStageSessionManager(engine, client=client)

    await manager.start_session()
    await manager.receive_audio(b"fake_wav_bytes", "audio/wav")

    assert client.models.calls == 0


@pytest.mark.asyncio
async def test_receive_audio_sends_ai_turn_end():
    """receive_audio の応答後に ai_turn_end がbroadcastされる"""
    engine = AgitationEngine()
    client = _FakeClient(["stage1 text", "stage2 text"])
    manager = TwoStageSessionManager(engine, client=client)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    manager.set_broadcast_callback(fake_broadcast)
    await manager.start_session()
    await manager.receive_audio(b"fake_wav", "audio/wav")

    assert any(m["type"] == "ai_turn_end" for m in received), \
        "ai_turn_end が届いていない"
    types = [m["type"] for m in received]
    assert types[-1] == "ai_turn_end", "ai_turn_end が最後のメッセージでない"


@pytest.mark.asyncio
async def test_start_session_sends_intro_and_ai_turn_end():
    """send_intro はイントロテキストと ai_turn_end をbroadcastする"""
    engine = AgitationEngine()
    client = _FakeClient(["手相には深い線が刻まれています。運命が動いています。"])
    manager = TwoStageSessionManager(engine, client=client)

    received = []

    async def fake_broadcast(data):
        received.append(data)

    manager.set_broadcast_callback(fake_broadcast)
    await manager.start_session()
    await manager.send_intro()

    assert any(m["type"] == "ai_text" for m in received), "イントロテキストが届いていない"
    assert any(m["type"] == "ai_turn_end" for m in received), "ai_turn_end が届いていない"
    types = [m["type"] for m in received]
    assert types[-1] == "ai_turn_end", "ai_turn_end が最後でない"


def test_pcm_to_wav_bytes_creates_valid_wav():
    pcm = bytes(24000 * 2)  # 1秒分のサイレント PCM
    wav_bytes = _pcm_to_wav_bytes(pcm, sample_rate=24000)
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 24000


def test_wav_duration():
    pcm = bytes(24000 * 2)  # 1秒
    assert abs(_wav_duration(_pcm_to_wav_bytes(pcm)) - 1.0) < 0.01


def test_save_tts_wav_returns_url_and_duration(tmp_path):
    with patch("src.two_stage_session.TTS_DIR", tmp_path):
        url, duration = _save_tts_wav(bytes(24000 * 2))
    assert url.startswith("/audio/tts/") and url.endswith(".wav")
    assert abs(duration - 1.0) < 0.01


def test_save_tts_wav_cleanup_old_files(tmp_path):
    with patch("src.two_stage_session.TTS_DIR", tmp_path):
        for _ in range(21):
            _save_tts_wav(bytes(24000 * 2))
        assert len(list(tmp_path.glob("*.wav"))) <= 20
