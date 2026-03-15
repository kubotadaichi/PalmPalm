# Live API WebSocket Migration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ブラウザから Gemini Live API まで音声を常時ストリーミングし、無音で AI ターン開始・割り込み・tool use を自然に扱えるようにする。

**Architecture:** フロントとバックエンドの間を `WebSocket /ws/session` に置き換え、ブラウザの `AudioWorklet` から出る PCM を binary frame で逐次送信する。バックエンドは接続ごとに `LiveSessionManager` を 1 本持続し、Gemini Live API へ chunk を流しつつ、返ってきた音声 chunk と `turn_complete` をクライアントへ中継する。`get_agitation` は当面ローリング集計を返す。

**Tech Stack:** Python 3.11 / FastAPI WebSocket / google-genai Live API / pytest / React / WebSocket / Web Audio API / AudioWorklet

---

## Chunk 1: LiveSessionManager を逐次送信対応にする

### Task 1: `send_audio_chunk()` と `flush_input_audio()` の赤テストを書く

**Files:**
- Modify: `backend/tests/test_live_session.py`
- Modify: `backend/src/live_session.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_live_session.py` の末尾に追加：

```python
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

    fake_session.send_realtime_input.assert_awaited_once_with(audio_stream_end=True)
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_live_session.py::test_send_audio_chunk_sends_single_pcm_chunk -v
```

Expected: `AttributeError: 'LiveSessionManager' object has no attribute 'send_audio_chunk'`

- [ ] **Step 3: 最小実装を書く**

`backend/src/live_session.py` に追加：

```python
async def send_audio_chunk(self, pcm_bytes: bytes) -> None:
    await self._session.send_realtime_input(
        audio=types.Blob(data=pcm_bytes, mime_type="audio/pcm;rate=16000")
    )


async def flush_input_audio(self) -> None:
    await self._session.send_realtime_input(audio_stream_end=True)
```

既存 `send_audio()` は削除するか、未使用なら呼び出し元をすべて置き換える。

- [ ] **Step 4: テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_live_session.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 5: コミット**

```bash
git add backend/src/live_session.py backend/tests/test_live_session.py
git commit -m "refactor: split LiveSessionManager audio send into chunk and flush"
```

---

### Task 2: `receive()` が音声イベントをそのまま中継できることを補強する

**Files:**
- Modify: `backend/tests/test_live_session.py`
- Modify: `backend/src/live_session.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_live_session.py` の末尾に追加：

```python
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
```

- [ ] **Step 2: テストが失敗することを確認**

必要なら一時的に順序バグを再現し、以下を実行：

```bash
cd backend && uv run pytest tests/test_live_session.py::test_receive_yields_multiple_audio_chunks_in_order -v
```

Expected: FAIL（順序や chunk 数の不整合があればそれを確認）

- [ ] **Step 3: 最小実装を書く**

`receive()` は既存の async generator を維持し、順序どおり `audio_chunk` と `turn_complete` を yield するよう整理する。必要なら `_extract_audio_data()` のみを使う形へ統一する。

- [ ] **Step 4: テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_live_session.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 5: コミット**

```bash
git add backend/src/live_session.py backend/tests/test_live_session.py
git commit -m "test: cover ordered audio chunk streaming"
```

---

## Chunk 2: FastAPI を WebSocket エンドポイント化する

### Task 3: `main.py` の WebSocket 接続テストを書く

**Files:**
- Modify: `backend/tests/test_main.py`
- Modify: `backend/src/main.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_main.py` を WebSocket 前提に更新し、末尾に追加：

```python
from fastapi.testclient import TestClient


def test_ws_session_sends_ready_event(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app

        client = TestClient(app)
        with client.websocket_connect("/ws/session") as ws:
            message = ws.receive_json()

    assert message["type"] == "session_ready"
    mock_manager.connect.assert_awaited_once()
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_main.py::test_ws_session_sends_ready_event -v
```

Expected: FAIL / `WebSocketDisconnect` or route not found

- [ ] **Step 3: 最小実装を書く**

`backend/src/main.py` に `@app.websocket("/ws/session")` を追加し、接続時に:

```python
await websocket.accept()
manager = LiveSessionManager()
await manager.connect()
await websocket.send_json({"type": "session_ready"})
```

既存の `POST /api/session/start` は削除する。

- [ ] **Step 4: テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_main.py::test_ws_session_sends_ready_event -v
```

Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add backend/src/main.py backend/tests/test_main.py
git commit -m "feat: add websocket session endpoint"
```

---

### Task 4: binary frame を `send_audio_chunk()` に中継する

**Files:**
- Modify: `backend/tests/test_main.py`
- Modify: `backend/src/main.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_main.py` の末尾に追加：

```python
def test_ws_binary_audio_calls_send_audio_chunk(mock_manager):
    with patch("src.main.LiveSessionManager", return_value=mock_manager):
        from src.main import app

        client = TestClient(app)
        with client.websocket_connect("/ws/session") as ws:
            ws.receive_json()
            ws.send_bytes(b"\x00\x01" * 100)

    mock_manager.send_audio_chunk.assert_awaited()
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_main.py::test_ws_binary_audio_calls_send_audio_chunk -v
```

Expected: FAIL / `send_audio_chunk` not called

- [ ] **Step 3: 最小実装を書く**

`main.py` の WebSocket 受信ループで binary frame を受けたら:

```python
data = await websocket.receive()
if "bytes" in data and data["bytes"] is not None:
    await manager.send_audio_chunk(data["bytes"])
```

- [ ] **Step 4: テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_main.py::test_ws_binary_audio_calls_send_audio_chunk -v
```

Expected: PASS

- [ ] **Step 5: コミット**

```bash
git add backend/src/main.py backend/tests/test_main.py
git commit -m "feat: stream websocket audio chunks to LiveSessionManager"
```

---

### Task 5: Live API 受信イベントを WebSocket へ転送する

**Files:**
- Modify: `backend/tests/test_main.py`
- Modify: `backend/src/main.py`

- [ ] **Step 1: 失敗するテストを書く**

`backend/tests/test_main.py` の `mock_manager.receive` を以下のように使うテストを追加：

```python
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
```

- [ ] **Step 2: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_main.py::test_ws_forwards_audio_chunk_and_turn_complete -v
```

Expected: FAIL / 受信イベントが来ない

- [ ] **Step 3: 最小実装を書く**

WebSocket 接続ごとにバックグラウンド task を起動し、`manager.receive()` を読みながら:

```python
await websocket.send_json(event)
```

切断時は task を cancel し、`disconnect()` を呼ぶ。

- [ ] **Step 4: テストが通ることを確認**

```bash
cd backend && uv run pytest tests/test_main.py -v
```

Expected: WebSocket 系テスト PASSED

- [ ] **Step 5: コミット**

```bash
git add backend/src/main.py backend/tests/test_main.py
git commit -m "feat: forward live audio events over websocket"
```

---

## Chunk 3: フロントを WebSocket ストリーミングへ移行する

### Task 6: `useSession.js` の送受信を WebSocket ベースに書き換える

**Files:**
- Modify: `frontend/src/hooks/useSession.js`

- [ ] **Step 1: 動作確認用の失敗条件を決める**

ブラウザ手動確認で以下を満たさない現状を確認:
- `session_ready` 前に録音が流れない
- `POST /api/audio` が呼ばれている

- [ ] **Step 2: 最小実装を書く**

`frontend/src/hooks/useSession.js` を以下の方針で更新：

- `fetch('/api/session/start')` を削除
- `new WebSocket(`${wsBase}/ws/session`)` を使う
- `socket.binaryType = 'arraybuffer'`
- `session_ready` を受けるまで PCM を送らない
- `worklet.port.onmessage` で `socket.send(event.data)`
- サーバーからの JSON で `audio_chunk` / `turn_complete` / `error` を処理

`VITE_BACKEND_URL` が `http://127.0.0.1:8000` の場合は `ws://127.0.0.1:8000/ws/session` に変換する小さな helper を入れる。

- [ ] **Step 3: ビルド確認**

```bash
cd frontend && npm run build
```

Expected: 成功

- [ ] **Step 4: コミット**

```bash
git add frontend/src/hooks/useSession.js
git commit -m "feat: stream microphone and live audio over websocket"
```

---

### Task 7: セッション終了時の cleanup を WebSocket 前提で整える

**Files:**
- Modify: `frontend/src/hooks/useSession.js`

- [ ] **Step 1: 手動で不具合を確認**

ブラウザでページを離れたときに:
- WebSocket が閉じない
- 録音が止まらない
- AudioContext が残る

のいずれかがあれば再現手順を確認する。

- [ ] **Step 2: 最小実装を書く**

`useEffect` cleanup で以下を実行：

```javascript
socketRef.current?.send(JSON.stringify({ type: 'session_end' }))
socketRef.current?.close()
streamRef.current?.getTracks().forEach((track) => track.stop())
captureCtxRef.current?.close()
audioCtxRef.current?.close()
```

- [ ] **Step 3: ビルド確認**

```bash
cd frontend && npm run build
```

Expected: 成功

- [ ] **Step 4: コミット**

```bash
git add frontend/src/hooks/useSession.js
git commit -m "fix: clean up websocket audio session on unmount"
```

---

## Chunk 4: 手動確認

### Task 8: ローカルで WebSocket 音声ストリーミングを確認する

**Files:**
- Modify: 必要なら `frontend/vite.config.js`

- [ ] **Step 1: バックエンドを起動**

```bash
cd backend && uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: フロントエンドを起動**

```bash
cd frontend && VITE_BACKEND_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5173
```

- [ ] **Step 3: Chrome で確認**

1. `http://127.0.0.1:5173` を開く
2. DevTools の Network で `ws://127.0.0.1:8000/ws/session` が `101 Switching Protocols`
3. Console に `session_ready` 相当のログが出る
4. 発話を止めると AI 音声が再生される
5. AI 発話中に割り込み発話できる
6. バックエンドログに 500 が出ない

- [ ] **Step 4: 全バックエンドテスト**

```bash
cd backend && uv run pytest tests/ -v
```

Expected: 全テスト PASSED

- [ ] **Step 5: コミット**

```bash
git add -A
git commit -m "feat: migrate live audio flow to websocket streaming"
```

---

## Follow-up

- [ ] 動揺度を「AI が話し始めてから tool call 時点まで」で集計する再設計を別セッションで行う
