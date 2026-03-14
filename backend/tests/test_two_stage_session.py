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



def test_parse_stage1_extracts_tags():
    from src.two_stage_session import _parse_stage1
    raw = "<user_said>恋愛について聞いた</user_said><response>手相に流れが見える</response>"
    user, response = _parse_stage1(raw)
    assert user == "恋愛について聞いた"
    assert response == "手相に流れが見える"


def test_parse_stage1_fallback_when_no_tags():
    from src.two_stage_session import _parse_stage1
    raw = "タグなしのテキスト"
    user, response = _parse_stage1(raw)
    assert user == ""
    assert response == "タグなしのテキスト"


# --- Stage1 system prompt tests ---

def test_build_stage1_system_contains_cold_reading_instructions():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    system = manager._build_stage1_system()
    assert "ぱむぱむ" in system
    assert "感情線" in system


def test_build_stage1_system_injects_history():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    manager._history = [
        {"role": "user", "parts": [{"text": "恋愛について聞きたい"}]},
        {"role": "model", "parts": [{"text": "感情線に流れが見えます"}]},
    ]
    system = manager._build_stage1_system()
    assert "恋愛について聞きたい" in system
    assert "感情線に流れが見えます" in system


def test_build_stage1_system_no_phase_mentions():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    system = manager._build_stage1_system()
    for word in ["INTRO", "CORE", "HYPE", "CLIMAX", "フェーズ"]:
        assert word not in system


# --- Stage2 prompt tests ---

def test_build_stage2_prompt_low_agitation():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=20, trend="stable", stage1_text="何かが見えます")
    assert "level" in prompt or "20" in prompt


def test_build_stage2_prompt_high_rising_agitation():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=75, trend="rising", stage1_text="あなたは孤独です")
    assert "75" in prompt or "rising" in prompt


def test_build_stage2_prompt_max_agitation():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=85, trend="rising", stage1_text="隠せません")
    assert "85" in prompt or "rising" in prompt


def test_build_stage2_prompt_falling_agitation():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=65, trend="falling", stage1_text="体が覚えています")
    assert "falling" in prompt or "65" in prompt


def test_build_stage2_prompt_ends_with_question_rule():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=50, trend="rising", stage1_text="何か感じます")
    assert "問いかけ" in prompt or "？" in prompt


def test_build_stage2_prompt_contains_stage1_text():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    stage1 = "あなたの感情線には秘密が刻まれています"
    prompt = manager._build_stage2_prompt(level=40, trend="rising", stage1_text=stage1)
    assert stage1 in prompt


# --- Integration: no phase attributes ---

def test_manager_has_no_phase_attributes():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    assert not hasattr(manager, "_phase")
    assert not hasattr(manager, "_phase_turns")


# --- helpers ---

async def _noop_tts(text: str):
    return (None, 0.0)
