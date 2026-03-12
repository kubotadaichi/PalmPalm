from types import SimpleNamespace

import pytest

from src.agitation_engine import AgitationEngine
from src.two_stage_session import TwoStageSessionManager


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
