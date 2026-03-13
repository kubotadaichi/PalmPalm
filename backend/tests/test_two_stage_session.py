import io
import wave
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from src.two_stage_session import (
    TwoStageSessionManager,
    _pcm_to_wav_bytes,
    _save_tts_wav,
    _wav_duration,
)


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


# --- receive_audio() tests ---

@pytest.mark.asyncio
async def test_receive_audio_yields_stage1_stage2_turn_end():
    client = _FakeClient(["stage1 text", "stage2 text"])
    manager = TwoStageSessionManager(client=client)
    manager._generate_tts = lambda text: _noop_tts(text)

    events = []
    async for event in manager.receive_audio(b"fake_audio", "audio/webm"):
        events.append(event)

    types = [e["type"] for e in events]
    assert types == ["stage1", "stage2", "turn_end"]
    assert events[0]["text"] == "stage1 text"
    assert events[1]["text"] == "stage2 text"


@pytest.mark.asyncio
async def test_receive_audio_fallback_on_empty_stage1():
    client = _FakeClient(["", "stage2 text"])
    manager = TwoStageSessionManager(client=client)
    manager._generate_tts = lambda text: _noop_tts(text)

    events = []
    async for event in manager.receive_audio(b"fake_audio", "audio/webm"):
        events.append(event)

    assert events[0]["type"] == "stage1"
    assert len(events[0]["text"]) > 0


# --- WAV helper tests ---

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


# --- helpers ---

async def _noop_tts(text: str):
    return (None, 0.0)
