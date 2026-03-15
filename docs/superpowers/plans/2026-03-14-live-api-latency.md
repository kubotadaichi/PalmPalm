# Live API レイテンシ改善 Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Gemini Live API + Tool Use への移行により、stage1 first audio を ~15s → ~2s に短縮し、2段階の gap を廃止する。

**Architecture:** Gemini Live API WebSocket セッションを占いセッション全体で持続させ、agitation データは `get_agitation` tool として AI が自律的に呼び出す。AgitationEngine にタイムウィンドウクエリを追加し、AI が発話し始めた時刻から tool call 時点までの振動データを返す。

**Tech Stack:** Python 3.11 / FastAPI / google-genai (Live API) / pytest / React / Web Audio API / AudioWorklet

---

## Chunk 1: AgitationEngine + AgitationServer 拡張

### Task 1: AgitationEngine に `_calc_trend` を切り出し

**Files:**
- Modify: `backend/src/agitation_engine.py`
- Test: `backend/tests/test_agitation_engine.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_agitation_engine.py` の末尾に追加：

```python
def test_calc_trend_rising():
    """_calc_trend: diff > 10 で rising"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 30
    assert engine._calc_trend(50) == "rising"


def test_calc_trend_falling():
    """_calc_trend: diff < -10 で falling"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 60
    assert engine._calc_trend(40) == "falling"


def test_calc_trend_stable():
    """_calc_trend: diff が ±10 以内で stable"""
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 50
    assert engine._calc_trend(55) == "stable"
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_agitation_engine.py::test_calc_trend_rising -v
```

Expected: `FAILED` / `AttributeError: 'AgitationEngine' object has no attribute '_calc_trend'`

- [ ] **Step 3: `_calc_trend` を実装**

`backend/src/agitation_engine.py` の `trend` プロパティの直前に追加し、`trend` プロパティは `_calc_trend` を使うよう変更：

```python
def _calc_trend(self, level: int) -> str:
    diff = level - self._previous_level
    if diff > 10:
        return "rising"
    elif diff < -10:
        return "falling"
    return "stable"

@property
def trend(self) -> str:
    return self._calc_trend(self.level)
```

- [ ] **Step 4: 全テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_agitation_engine.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 5: コミット**

```bash
git add backend/src/agitation_engine.py backend/tests/test_agitation_engine.py
git commit -m "refactor: extract _calc_trend from trend property"
```

---

### Task 2: AgitationEngine に `snapshot_window` を追加

**Files:**
- Modify: `backend/src/agitation_engine.py`
- Test: `backend/tests/test_agitation_engine.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_agitation_engine.py` の末尾に追加：

```python
def test_snapshot_window_counts_pulses_in_range():
    """指定期間内のパルスのみ集計する"""
    import time
    engine = AgitationEngine(window_seconds=60, max_pulses=10)
    before = time.time()
    for _ in range(5):
        engine.record_pulse()
    after = time.time()
    result = engine.snapshot_window(before, after)
    assert result["level"] == 50
    assert result["peak"] == 50
    assert result["trend"] in ("rising", "falling", "stable")


def test_snapshot_window_excludes_out_of_range():
    """ウィンドウ外のパルスは含まない"""
    import time
    engine = AgitationEngine(window_seconds=60, max_pulses=10)
    for _ in range(5):
        engine.record_pulse()
    # ウィンドウを未来に設定（パルスはすべて window 外）
    future = time.time() + 1000
    result = engine.snapshot_window(future, future + 1)
    assert result["level"] == 0


def test_snapshot_window_does_not_update_previous_level():
    """snapshot_window は _previous_level を更新しない"""
    import time
    engine = AgitationEngine(window_seconds=60, max_pulses=10)
    engine._previous_level = 42.0
    t = time.time()
    for _ in range(5):
        engine.record_pulse()
    engine.snapshot_window(t, time.time())
    assert engine._previous_level == 42.0
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_agitation_engine.py::test_snapshot_window_counts_pulses_in_range -v
```

Expected: `FAILED` / `AttributeError: ... no attribute 'snapshot_window'`

- [ ] **Step 3: `snapshot_window` を実装**

`backend/src/agitation_engine.py` に追加（`snapshot` メソッドの下）：

```python
def snapshot_window(self, from_ts: float, to_ts: float) -> dict:
    """指定期間内のパルスから level/peak/trend を算出。_previous_level は更新しない。"""
    pulses_in_window = [t for t in self._pulses if from_ts <= t <= to_ts]
    level = min(100, int(len(pulses_in_window) / self.max_pulses * 100))
    return {"level": level, "peak": level, "trend": self._calc_trend(level)}
```

- [ ] **Step 4: 全テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_agitation_engine.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 5: コミット**

```bash
git add backend/src/agitation_engine.py backend/tests/test_agitation_engine.py
git commit -m "feat: add snapshot_window to AgitationEngine"
```

---

### Task 3: AgitationServer に `/agitation/window` エンドポイントを追加

**Files:**
- Modify: `backend/src/agitation_server.py`
- Test: `backend/tests/test_agitation_server.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_agitation_server.py` の末尾に追加：

```python
@pytest.mark.asyncio
async def test_agitation_window_empty():
    """ウィンドウ内にパルスなし → level=0"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        import time
        t = time.time()
        resp = await ac.get(f"/agitation/window?from_ts={t}&to_ts={t + 1}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] == 0
    assert "trend" in data
    assert "peak" in data


@pytest.mark.asyncio
async def test_agitation_window_with_pulses():
    """ウィンドウ内にパルスあり → level > 0"""
    import time
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as ac:
        t_start = time.time()
        for _ in range(5):
            await ac.post("/pulse")
        t_end = time.time()
        resp = await ac.get(f"/agitation/window?from_ts={t_start}&to_ts={t_end}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] > 0
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_agitation_server.py::test_agitation_window_empty -v
```

Expected: `FAILED` / 404

- [ ] **Step 3: エンドポイントを実装**

`backend/src/agitation_server.py` に追加：

```python
@app.get("/agitation/window")
def get_agitation_window(from_ts: float, to_ts: float):
    snap = engine.snapshot_window(from_ts, to_ts)
    print(f"[Agitation] window({from_ts:.1f},{to_ts:.1f}) → level={snap['level']}%, trend={snap['trend']}", flush=True)
    return snap
```

- [ ] **Step 4: 全テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_agitation_server.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 5: コミット**

```bash
git add backend/src/agitation_server.py backend/tests/test_agitation_server.py
git commit -m "feat: add /agitation/window endpoint"
```

---

## Chunk 2: LiveSessionManager

### Task 4: `live_session.py` の骨格とモックテスト環境を作る

**Files:**
- Create: `backend/src/live_session.py`
- Create: `backend/tests/test_live_session.py`

- [ ] **Step 1: モッククライアントの設計を理解する**

`google.genai` の Live API は以下のパターンで使う：

```python
async with client.aio.live.connect(model=MODEL, config=config) as session:
    await session.send_realtime_input(audio=types.Blob(data=pcm, mime_type="audio/pcm;rate=16000"))
    async for response in session.receive():
        # response.data: audio chunk bytes
        # response.tool_call: FunctionCall オブジェクト
        # response.server_content.turn_complete: bool
```

テストではこの `session` をモックする。

- [ ] **Step 2: モックと骨格テストを書く**

新規ファイル `backend/tests/test_live_session.py` を作成：

```python
"""LiveSessionManager のユニットテスト（Gemini API はモック）。"""
import asyncio
import time
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
        self.turn_complete = turn_complete


class FakeResponse:
    def __init__(self, audio_data=None, tool_call=None, turn_complete=False):
        self.data = audio_data  # raw bytes or None
        # tool_call は FakeToolCallWrapper でラップして .function_calls を持たせる
        self.tool_call = FakeToolCallWrapper(tool_call) if tool_call else None
        self.server_content = FakeServerContent(audio_data, turn_complete)


def make_fake_session(responses):
    """指定した responses を順に返す AsyncContextManager モック。"""
    session = AsyncMock()

    async def fake_receive():
        for r in responses:
            yield r

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

    assert any(e["type"] == "audio_chunk" for e in events)
    assert any(e["type"] == "turn_complete" for e in events)


@pytest.mark.asyncio
async def test_receive_sets_ai_speak_start_on_first_audio(manager):
    """最初の audio chunk 受信時に _ai_speak_start がセットされる。"""
    pcm = b"\x00\x01" * 100
    responses = [FakeResponse(audio_data=pcm), FakeResponse(turn_complete=True)]
    fake_session = make_fake_session(responses)
    manager._session = fake_session
    assert manager._ai_speak_start is None

    async for _ in manager.receive():
        pass

    assert manager._ai_speak_start is not None


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
    fake_session.send_realtime_input.assert_called_once()
```

- [ ] **Step 3: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_live_session.py -v
```

Expected: `FAILED` / `ModuleNotFoundError: No module named 'src.live_session'`

- [ ] **Step 4: コミット（テストのみ）**

```bash
git add backend/tests/test_live_session.py
git commit -m "test: add LiveSessionManager unit tests (red)"
```

---

### Task 5: `live_session.py` を実装する

**Files:**
- Create: `backend/src/live_session.py`

- [ ] **Step 1: `live_session.py` を作成**

```python
"""
Gemini Live API を使った占いセッション管理。
- 1ターン = 1つの自然な応答（stage1/stage2 の区別なし）
- get_agitation tool を AI が自律的に呼ぶ
"""
from __future__ import annotations

import base64
import os
import time
from typing import AsyncGenerator

import httpx
from google import genai
from google.genai import types

MODEL = "gemini-2.5-flash-live"
AGITATION_API_URL = os.getenv("AGITATION_API_URL", "")

SYSTEM_INSTRUCTION = """\
あなたはAI手相占い師「ぱむぱむ」です。

【基本姿勢】
手の感情線・運命線・頭脳線・生命線を具体的に言及しながら語る。
断言は避け「〜ではないですか」「〜が見えます」という仮説として語る。
神秘的かつ低いトーンで、2〜3文で語る。

【get_agitation ツールの使い方（最重要）】
- 毎ターン必ず1回呼び出すこと
- 呼び出すタイミングは「感情の核心に近づいた」と感じた瞬間（ターンの中盤〜後半）
- 呼び出す前に一般的な読みを展開し、結果を見てから核心を突く
- すぐに「センサーが〜」とは言わない。「体が正直に答えています」程度に留める

【出力】
2〜3文、必ず問いかけで締める。
"""

GET_AGITATION_DECLARATION = types.FunctionDeclaration(
    name="get_agitation",
    description=(
        "ユーザーの手の振動センサーから身体的動揺度を読み取る。"
        "占いの重要なタイミング（感情の核心に触れる直前）で呼び出すこと。"
        "呼び出すタイミング自体が演出の一部。毎ターン1回は必ず呼び出すこと。"
    ),
    parameters=types.Schema(type=types.Type.OBJECT, properties={}),
)


class LiveSessionManager:
    """Gemini Live API を使った占いセッション管理。"""

    def __init__(
        self,
        agitation_api_url: str = AGITATION_API_URL,
        client: genai.Client | None = None,
    ):
        self.agitation_api_url = agitation_api_url
        self._client = client or genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self._session = None
        self._ai_speak_start: float | None = None
        self._text_history: list[dict] = []  # 切断復帰用（直近6ターン）
        self._ctx = None  # async context manager

    async def connect(self) -> None:
        """Live API セッションを確立する。"""
        config = types.LiveConnectConfig(
            response_modalities=["AUDIO"],
            system_instruction=SYSTEM_INSTRUCTION,
            tools=[types.Tool(function_declarations=[GET_AGITATION_DECLARATION])],
            context_window_compression=types.ContextWindowCompressionConfig(
                trigger_tokens=100000,
                sliding_window=types.SlidingWindow(target_tokens=80000),
            ),
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
                )
            ),
        )
        self._ctx = self._client.aio.live.connect(model=MODEL, config=config)
        self._session = await self._ctx.__aenter__()

    async def disconnect(self) -> None:
        """セッションを終了する。"""
        if self._ctx:
            await self._ctx.__aexit__(None, None, None)
            self._ctx = None
            self._session = None

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """PCM 16kHz mono int16 を Live API へ送信。"""
        self._ai_speak_start = None  # 次の AI 発話の start をリセット
        await self._session.send_realtime_input(
            audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
        )

    async def receive(self) -> AsyncGenerator[dict, None]:
        """
        受信イベントを yield する:
          {"type": "audio_chunk", "data": "<base64 PCM 24kHz>"}
          {"type": "turn_complete"}
        """
        async for response in self._session.receive():
            # audio chunk
            if response.data:
                if self._ai_speak_start is None:
                    self._ai_speak_start = time.time()
                yield {
                    "type": "audio_chunk",
                    "data": base64.b64encode(response.data).decode(),
                }

            # tool call
            if response.tool_call:
                for call in response.tool_call.function_calls:
                    await self._handle_tool_call(call)

            # turn complete
            if (
                response.server_content
                and response.server_content.turn_complete
            ):
                yield {"type": "turn_complete"}
                self._ai_speak_start = None

    async def _handle_tool_call(self, call) -> None:
        """get_agitation tool call を処理してラズパイに問い合わせ、結果を返す。"""
        from_ts = self._ai_speak_start if self._ai_speak_start else time.time() - 3.0
        to_ts = time.time()
        snap = await self._fetch_agitation_window(from_ts, to_ts)
        await self._session.send_tool_response(
            function_responses=[
                types.FunctionResponse(
                    id=call.id,
                    name=call.name,
                    response=snap,
                )
            ]
        )

    async def _fetch_agitation_window(self, from_ts: float, to_ts: float) -> dict:
        """ラズパイの /agitation/window を HTTP 呼び出し。失敗時はデフォルト値を返す。"""
        if not self.agitation_api_url:
            return {"level": 0, "peak": 0, "trend": "stable"}
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.get(
                    f"{self.agitation_api_url}/agitation/window",
                    params={"from_ts": from_ts, "to_ts": to_ts},
                )
                return resp.json()
        except Exception as e:
            print(f"[LiveSession] agitation fetch error: {e}", flush=True)
            return {"level": 0, "peak": 0, "trend": "stable"}
```

- [ ] **Step 2: テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_live_session.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 3: コミット**

```bash
git add backend/src/live_session.py
git commit -m "feat: implement LiveSessionManager with get_agitation tool"
```

---

## Chunk 3: main.py エンドポイント更新

### Task 6: `main.py` を Live API エンドポイントに置き換える

**Files:**
- Modify: `backend/src/main.py`
- Test: `backend/tests/test_main.py`（新規）

- [ ] **Step 1: 失敗するテストを書く**

新規ファイル `backend/tests/test_main.py` を作成：

```python
"""main.py エンドポイントの統合テスト。LiveSessionManager はモック。"""
import pytest
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_manager():
    m = MagicMock()
    m.connect = AsyncMock()
    m.disconnect = AsyncMock()
    m.send_audio = AsyncMock()

    async def fake_receive():
        yield {"type": "audio_chunk", "data": "AAEC"}
        yield {"type": "turn_complete"}

    m.receive = fake_receive
    return m


@pytest.mark.asyncio
async def test_session_start_returns_session_id(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post("/api/session/start")
    assert resp.status_code == 200
    assert "session_id" in resp.json()


@pytest.mark.asyncio
async def test_audio_returns_sse(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app, sessions
        session_id = "test-session-123"
        sessions[session_id] = mock_manager

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                f"/api/audio?session_id={session_id}",
                content=b"\x00" * 3200,
                headers={"Content-Type": "audio/octet-stream"},
            )
    assert resp.status_code == 200
    assert "text/event-stream" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_audio_unknown_session_returns_404(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.post(
                "/api/audio?session_id=does-not-exist",
                content=b"\x00" * 3200,
            )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_session_delete(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app, sessions
        session_id = "del-session-456"
        sessions[session_id] = mock_manager

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            resp = await ac.delete(f"/api/session?session_id={session_id}")
    assert resp.status_code == 200
    assert session_id not in sessions
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_main.py -v
```

Expected: `FAILED` / 404 or import error

- [ ] **Step 3: `main.py` を書き換える**

`backend/src/main.py` を以下に置き換える：

```python
# backend/src/main.py
# Docker コンテナで IPv6 が到達不能な環境向け: DNS 解決で IPv4 のみ返すように上書き
import socket as _socket
_orig_getaddrinfo = _socket.getaddrinfo
def _ipv4_only(host, port, family=0, *a, **kw):
    results = _orig_getaddrinfo(host, port, family, *a, **kw)
    ipv4 = [r for r in results if r[0] == _socket.AF_INET]
    return ipv4 if ipv4 else results
_socket.getaddrinfo = _ipv4_only

import json
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from dotenv import load_dotenv

from .live_session import LiveSessionManager

load_dotenv()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)

# セッション管理（session_id → LiveSessionManager）
sessions: dict[str, LiveSessionManager] = {}


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.post("/api/session/start")
async def session_start():
    """Live API セッションを確立し session_id を返す。"""
    session_id = str(uuid.uuid4())
    manager = LiveSessionManager()
    await manager.connect()
    sessions[session_id] = manager
    print(f"[Main] session started: {session_id}", flush=True)
    return {"session_id": session_id}


@app.post("/api/audio")
async def receive_audio(session_id: str, request: Request):
    """PCM 音声を受け取り、Live API 経由で応答を SSE でストリーム返却。"""
    manager = sessions.get(session_id)
    if not manager:
        raise HTTPException(status_code=404, detail="session not found")

    pcm_bytes = await request.body()
    await manager.send_audio(pcm_bytes)

    async def generate():
        async for event in manager.receive():
            yield _sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.delete("/api/session")
async def session_delete(session_id: str):
    """セッションを終了・破棄する。"""
    manager = sessions.pop(session_id, None)
    if manager:
        await manager.disconnect()
    print(f"[Main] session deleted: {session_id}", flush=True)
    return {"ok": True}
```

- [ ] **Step 4: テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_main.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 5: 全バックエンドテストが通ることを確認**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: 全テスト PASSED（`test_two_stage_session.py` は既存のままなので影響なし）

- [ ] **Step 6: コミット**

```bash
git add backend/src/main.py backend/tests/test_main.py
git commit -m "feat: replace main.py with Live API session endpoints"
```

---

## Chunk 4: フロントエンド更新

### Task 7: AudioWorklet プロセッサを作成する

**Files:**
- Create: `frontend/public/pcm-processor.js`

フロントエンドのテストは手動（ブラウザ）で確認する。

- [ ] **Step 1: AudioWorklet プロセッサを作成**

新規ファイル `frontend/public/pcm-processor.js` を作成：

```javascript
/**
 * AudioWorklet プロセッサ：マイク入力を 16kHz mono int16 PCM に変換して送信する。
 * AudioContext sampleRate=16000 で使うこと。
 */
class PcmProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true
    const float32 = input[0]
    // float32 [-1, 1] → int16
    const int16 = new Int16Array(float32.length)
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768))
    }
    this.port.postMessage(int16.buffer, [int16.buffer])
    return true
  }
}

registerProcessor('pcm-processor', PcmProcessor)
```

- [ ] **Step 2: コミット**

```bash
git add frontend/public/pcm-processor.js
git commit -m "feat: add AudioWorklet PCM processor"
```

---

### Task 8: `SessionPage.jsx` と `App.jsx` の `aiText` 依存を除去する

Live API は音声のみを返すため `aiText` は不要になる。
`SessionPage.jsx` の `KirbyMock` アニメーションは `turn === 'ai'` で制御する。

**Files:**
- Modify: `frontend/src/pages/SessionPage.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: `SessionPage.jsx` を修正**

`frontend/src/pages/SessionPage.jsx` の以下の行を変更：

```jsx
// 変更前
<KirbyMock isTalking={turn === 'ai' && aiText.length > 0} />
<div className="mt-8 max-w-md text-center min-h-[4rem] px-4">
  <p className="text-lg leading-relaxed">{aiText}</p>
</div>

// 変更後
<KirbyMock isTalking={turn === 'ai'} />
<div className="mt-8 max-w-md text-center min-h-[4rem] px-4" />
```

関数シグネチャからも `aiText` を削除：

```jsx
// 変更前
export function SessionPage({ turn, aiText, vadError, timeLeft, onEnd }) {

// 変更後
export function SessionPage({ turn, vadError, timeLeft, onEnd }) {
```

- [ ] **Step 2: `App.jsx` を修正**

`frontend/src/App.jsx` の以下の行を変更：

```jsx
// 変更前
const { turn, aiText, vadError, timeLeft } = useSession({

// 変更後
const { turn, vadError, timeLeft } = useSession({
```

```jsx
// 変更前（SessionPage への props）
<SessionPage
  turn={turn}
  aiText={aiText}
  vadError={vadError}
  timeLeft={timeLeft}
  onEnd={() => setPage('end')}
/>

// 変更後
<SessionPage
  turn={turn}
  vadError={vadError}
  timeLeft={timeLeft}
  onEnd={() => setPage('end')}
/>
```

- [ ] **Step 3: コミット**

```bash
git add frontend/src/pages/SessionPage.jsx frontend/src/App.jsx
git commit -m "refactor: remove aiText from SessionPage (Live API is audio-only)"
```

---

### Task 10: `useSession.js` を Live API 対応に書き換える

**Files:**
- Modify: `frontend/src/hooks/useSession.js`

- [ ] **Step 1: `useSession.js` を書き換える**

`frontend/src/hooks/useSession.js` を以下に置き換える：

```javascript
/**
 * useSession.js
 * Live API 対応版:
 * - AudioWorklet で PCM 16kHz をキャプチャ
 * - POST /api/audio で送信 → SSE で audio_chunk (base64 PCM 24kHz) を受信
 * - Web Audio API で PCM チャンクをスケジュール再生
 */
import { useCallback, useEffect, useRef, useState } from 'react'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || ''
const MAX_RECORD_SECONDS = 10

async function* readSseStream(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try { yield JSON.parse(line.slice(6)) } catch { /* ignore */ }
      }
    }
  }
}

export function useSession({ enabled = false } = {}) {
  const [turn, setTurn] = useState('user')
  const [vadError, setVadError] = useState(null)
  const [timeLeft, setTimeLeft] = useState(MAX_RECORD_SECONDS)

  const sessionIdRef = useRef(null)
  const audioCtxRef = useRef(null)       // 再生用 AudioContext (24kHz)
  const captureCtxRef = useRef(null)     // キャプチャ用 AudioContext (16kHz)
  const workletNodeRef = useRef(null)
  const streamRef = useRef(null)
  const pcmChunksRef = useRef([])        // 録音中の PCM chunks
  const nextPlayTimeRef = useRef(0)      // 次の audio chunk を再生する時刻
  const countdownRef = useRef(null)
  const stopTimerRef = useRef(null)
  const enabledRef = useRef(enabled)

  useEffect(() => { enabledRef.current = enabled }, [enabled])

  // ── セッション開始 ──────────────────────────────────────
  const startSession = useCallback(async () => {
    try {
      const resp = await fetch(`${BACKEND_URL}/api/session/start`, { method: 'POST' })
      const { session_id } = await resp.json()
      sessionIdRef.current = session_id
      console.log('[useSession] session started:', session_id)
    } catch (err) {
      setVadError('セッション開始失敗: ' + err.message)
    }
  }, [])

  // ── セッション終了 ──────────────────────────────────────
  const stopSession = useCallback(async () => {
    const sid = sessionIdRef.current
    if (!sid) return
    sessionIdRef.current = null
    try {
      await fetch(`${BACKEND_URL}/api/session?session_id=${sid}`, { method: 'DELETE' })
    } catch { /* ignore */ }
  }, [])

  // ── 録音開始 ───────────────────────────────────────────
  const startRecording = useCallback(async () => {
    setVadError(null)
    const mediaDevices = globalThis.navigator?.mediaDevices
    if (!mediaDevices?.getUserMedia) {
      setVadError('マイクが利用できません。HTTPS または localhost で開いてください。')
      return
    }
    try {
      if (!streamRef.current) {
        streamRef.current = await mediaDevices.getUserMedia({ audio: true })
      }
      // キャプチャ用 AudioContext (16kHz)
      if (!captureCtxRef.current || captureCtxRef.current.state === 'closed') {
        captureCtxRef.current = new AudioContext({ sampleRate: 16000 })
      }
      const captureCtx = captureCtxRef.current
      await captureCtx.audioWorklet.addModule('/pcm-processor.js')

      const source = captureCtx.createMediaStreamSource(streamRef.current)
      const worklet = new AudioWorkletNode(captureCtx, 'pcm-processor')
      workletNodeRef.current = worklet

      pcmChunksRef.current = []
      worklet.port.onmessage = (e) => {
        pcmChunksRef.current.push(new Int16Array(e.data))
      }
      source.connect(worklet)
      worklet.connect(captureCtx.destination)

      setTimeLeft(MAX_RECORD_SECONDS)
      countdownRef.current = setInterval(
        () => setTimeLeft((t) => Math.max(0, t - 1)),
        1000,
      )
      stopTimerRef.current = setTimeout(() => stopRecording(), MAX_RECORD_SECONDS * 1000)
    } catch (err) {
      setVadError(err?.message ?? 'マイク初期化失敗')
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── 録音停止 → 送信 ────────────────────────────────────
  const stopRecording = useCallback(async () => {
    if (countdownRef.current) { clearInterval(countdownRef.current); countdownRef.current = null }
    if (stopTimerRef.current) { clearTimeout(stopTimerRef.current); stopTimerRef.current = null }
    setTimeLeft(MAX_RECORD_SECONDS)

    const worklet = workletNodeRef.current
    if (worklet) { worklet.disconnect(); workletNodeRef.current = null }

    const chunks = pcmChunksRef.current
    pcmChunksRef.current = []
    if (!enabledRef.current || chunks.length === 0) { setTurn('user'); return }

    // Int16Array を結合して ArrayBuffer に
    const total = chunks.reduce((s, c) => s + c.length, 0)
    const merged = new Int16Array(total)
    let offset = 0
    for (const c of chunks) { merged.set(c, offset); offset += c.length }

    await sendAudio(merged.buffer)
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // ── PCM 送信 → SSE 受信 → 再生 ─────────────────────────
  const sendAudio = useCallback(async (pcmBuffer) => {
    const sid = sessionIdRef.current
    if (!sid) return
    setTurn('ai')

    // 再生用 AudioContext (24kHz)
    if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
      audioCtxRef.current = new AudioContext({ sampleRate: 24000 })
    }
    const audioCtx = audioCtxRef.current
    nextPlayTimeRef.current = audioCtx.currentTime

    try {
      const resp = await fetch(`${BACKEND_URL}/api/audio?session_id=${sid}`, {
        method: 'POST',
        headers: { 'Content-Type': 'audio/octet-stream' },
        body: pcmBuffer,
      })
      for await (const event of readSseStream(resp)) {
        if (event.type === 'audio_chunk') {
          // base64 → Int16Array → Float32Array → AudioBuffer → スケジュール再生
          const raw = atob(event.data)
          const int16 = new Int16Array(raw.length / 2)
          for (let i = 0; i < int16.length; i++) {
            int16[i] = (raw.charCodeAt(i * 2)) | (raw.charCodeAt(i * 2 + 1) << 8)
          }
          const float32 = new Float32Array(int16.length)
          for (let i = 0; i < int16.length; i++) {
            float32[i] = int16[i] / 32768
          }
          const buffer = audioCtx.createBuffer(1, float32.length, 24000)
          buffer.copyToChannel(float32, 0)
          const source = audioCtx.createBufferSource()
          source.buffer = buffer
          source.connect(audioCtx.destination)
          const startAt = Math.max(audioCtx.currentTime, nextPlayTimeRef.current)
          source.start(startAt)
          nextPlayTimeRef.current = startAt + buffer.duration
        } else if (event.type === 'turn_complete') {
          // 再生終了後にユーザーターンへ
          const remaining = nextPlayTimeRef.current - audioCtx.currentTime
          setTimeout(() => setTurn('user'), Math.max(0, remaining * 1000))
        }
      }
    } catch (err) {
      console.error('[useSession] sendAudio error:', err)
      setTurn('user')
    }
  }, [])

  // ── ライフサイクル ─────────────────────────────────────
  useEffect(() => {
    if (!enabled) {
      stopSession()
      setVadError(null)
      setTimeLeft(MAX_RECORD_SECONDS)
      setTurn('user')
      return
    }
    startSession()
  }, [enabled, startSession, stopSession])

  useEffect(() => {
    if (!enabled) return
    if (turn === 'user') {
      startRecording()
    } else {
      if (workletNodeRef.current) { workletNodeRef.current.disconnect(); workletNodeRef.current = null }
    }
  }, [enabled, turn, startRecording])

  useEffect(() => {
    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current)
      if (stopTimerRef.current) clearTimeout(stopTimerRef.current)
      streamRef.current?.getTracks().forEach((t) => t.stop())
      captureCtxRef.current?.close()
      audioCtxRef.current?.close()
    }
  }, [])

  return { turn, vadError, timeLeft }
}
```

- [ ] **Step 2: コミット**

```bash
git add frontend/src/hooks/useSession.js
git commit -m "feat: rewrite useSession for Live API (AudioWorklet + Web Audio API)"
```

---

### Task 11: フロントエンド動作確認

**ブラウザ手動テスト（Chrome 推奨）**

- [ ] **Step 1: バックエンドを起動**

```bash
cd backend && uv run uvicorn src.main:app --reload --port 8000
```

- [ ] **Step 2: フロントエンドを起動**

```bash
cd frontend && npm run dev
```

- [ ] **Step 3: Chrome DevTools で確認**

1. `http://localhost:5173` を開く
2. Network タブで `POST /api/session/start` が 200 を返すことを確認
3. 話しかけて `POST /api/audio` が SSE を返すことを確認
4. Console に `[useSession] session started: <uuid>` が出ることを確認
5. 音声が再生されることを確認（first audio まで ~2-3s が目標）
6. agitation server が動いていれば、AI がコールドリーディングで言及することを確認

- [ ] **Step 4: 問題なければコミット**

```bash
git add -A
git commit -m "feat: Live API migration complete"
```

---

## 最終確認

- [ ] **全バックエンドテストが通る**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: 全テスト PASSED

- [ ] **プロンプトチューニングタスクを登録する**

実装完了後、以下の内容で別ブレストセッションを行う：
- agitation レベル別のトーン調整
- tool call タイミングの誘導強化（WHEN_IDLE vs blocking の選択）
- コールドリーディング精度向上
