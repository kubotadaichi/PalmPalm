# Live VAD WebSocket Stabilization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Gemini Live API の自動 VAD を主導にして、2ターン目以降も安定して音声応答が返る WebSocket ストリーミングに整理する。

**Architecture:** ブラウザは PCM chunk を常時 WebSocket 送信し、ターン切替は Gemini Live API の `turn_complete` を基準にする。クライアント側の silence 判定と 10 秒タイマーは廃止し、バックエンドとフロントの両方に最小限の観測ログを加えて 2ターン目以降の不具合を切り分ける。

**Tech Stack:** Python 3.11 / FastAPI WebSocket / google-genai Live API / pytest / React / WebSocket / Web Audio API / AudioWorklet

---

## Chunk 1: 観測点を追加する

### Task 1: `live_session.py` に送受信ログを追加する

**Files:**
- Modify: `backend/src/live_session.py`

- [ ] **Step 1: 最小ログを追加**

以下を `print(..., flush=True)` で追加する。

- `send_audio_chunk()` 呼び出し時
- `receive()` で `audio_chunk` を yield する時
- `receive()` で `tool_call` を処理する時
- `receive()` で `turn_complete` を yield する時
- `disconnect()` 実行時

ログには event 種別と簡単なカウントまたは時刻を入れる。

- [ ] **Step 2: テストを実行**

```bash
cd backend && uv run pytest tests/test_live_session.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 3: コミット**

```bash
git add backend/src/live_session.py
git commit -m "chore: add live session debug logging"
```

---

### Task 2: `main.py` に WebSocket 接続理由ログを追加する

**Files:**
- Modify: `backend/src/main.py`

- [ ] **Step 1: 最小ログを追加**

以下を追加する。

- WebSocket accept 時
- binary frame 受信時
- text frame 受信時
- `WebSocketDisconnect` 捕捉時
- 例外時の stack trace
- finally 節で close 時

- [ ] **Step 2: テストを実行**

```bash
cd backend && uv run pytest tests/test_main.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 3: コミット**

```bash
git add backend/src/main.py
git commit -m "chore: add websocket session debug logging"
```

---

## Chunk 2: Live VAD 主導へ切り替える

### Task 3: `useSession.js` から client 側 silence 判定を削除する

**Files:**
- Modify: `frontend/src/hooks/useSession.js`

- [ ] **Step 1: 実装を簡素化**

以下を削除する。

- `SILENCE_THRESHOLD`
- `SILENCE_MS`
- `silenceTimerRef`
- `speechActiveRef`
- RMS 計算
- 無音で `setTurn('ai')` する処理
- `input_audio_end` 自動送信

`worklet.port.onmessage` は session ready かつ `turn === 'user'` なら PCM binary frame をそのまま送るだけにする。

- [ ] **Step 2: ビルド確認**

```bash
cd frontend && npm run build
```

Expected: 成功

- [ ] **Step 3: コミット**

```bash
git add frontend/src/hooks/useSession.js
git commit -m "refactor: remove client-side silence detection for live vad"
```

---

### Task 4: 10 秒タイマー依存を取り除く

**Files:**
- Modify: `frontend/src/hooks/useSession.js`
- Modify: `frontend/src/pages/SessionPage.jsx`
- Modify: `frontend/src/App.jsx`

- [ ] **Step 1: `useSession.js` から録音タイマー state を外す**

- `MAX_RECORD_SECONDS`
- `timeLeft`
- `countdownRef`
- `stopTimerRef`

を削除し、返り値は `{ turn, vadError }` にする。

- [ ] **Step 2: `SessionPage.jsx` と `App.jsx` の props を整理**

- `timeLeft` prop を削除
- 録音カウントダウン表示を削除

セッション全体の残り時間表示もこの時点で不要なら削除してよい。

- [ ] **Step 3: ビルド確認**

```bash
cd frontend && npm run build
```

Expected: 成功

- [ ] **Step 4: コミット**

```bash
git add frontend/src/hooks/useSession.js frontend/src/pages/SessionPage.jsx frontend/src/App.jsx
git commit -m "refactor: remove countdown-based turn control"
```

---

### Task 5: `main.py` の `input_audio_end` 依存を弱める

**Files:**
- Modify: `backend/src/main.py`

- [ ] **Step 1: `input_audio_end` を通常フローから外す**

`input_audio_end` を受けた時だけ `flush_input_audio()` を呼ぶ挙動は残してよいが、通常は binary frame の常時送信だけで会話が成立する前提にする。

コード上は以下を確認する。

- binary frame が主経路
- `session_end` は close 用
- `input_audio_end` は補助経路

- [ ] **Step 2: テストを実行**

```bash
cd backend && uv run pytest tests/test_main.py -v
```

Expected: 全テスト PASSED

- [ ] **Step 3: コミット**

```bash
git add backend/src/main.py
git commit -m "refactor: make websocket audio streaming primary path"
```

---

## Chunk 3: 実機確認

### Task 6: ブラウザで 2ターン目以降の再生を確認する

**Files:**
- Modify: 必要なら `frontend/src/hooks/useSession.js`
- Modify: 必要なら `backend/src/main.py`
- Modify: 必要なら `backend/src/live_session.py`

- [ ] **Step 1: バックエンド起動**

```bash
cd backend && uv run uvicorn src.main:app --host 127.0.0.1 --port 8000
```

- [ ] **Step 2: フロントエンド起動**

```bash
cd frontend && VITE_BACKEND_URL=http://127.0.0.1:8000 npm run dev -- --host 127.0.0.1 --port 5173
```

- [ ] **Step 3: Chrome で確認**

1. `http://127.0.0.1:5173` を開く
2. 1ターン目の音声再生を確認
3. 2ターン目の音声再生を確認
4. 無音時に固まらず `user` ターンのまま待機することを確認
5. AI 発話中に割り込めるか確認

- [ ] **Step 4: ログを確認**

バックエンドログから以下を確認する。

- 2ターン目でも binary frame を受けているか
- `audio_chunk` が返っているか
- `turn_complete` が返っているか
- close がどのタイミングで起きているか

- [ ] **Step 5: 必要なら最小修正**

ログから根因が出た場合のみ、最小修正を入れて再確認する。

- [ ] **Step 6: 全テスト**

```bash
cd backend && uv run pytest tests/ -v
cd ../frontend && npm run build
```

Expected: どちらも成功

- [ ] **Step 7: コミット**

```bash
git add -A
git commit -m "fix: stabilize websocket live vad turn handling"
```
