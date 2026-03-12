# ターン制会話システム 実装計画

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** AIとユーザーが交互に発話するターン制システムを実装し、AIの発話完了シグナル（`ai_turn_end`）でターンを遷移させる。

**Architecture:** バックエンドが各発話完了後に `ai_turn_end` WSメッセージを送信し、フロントエンドが `turn: 'ai' | 'user'` ステートマシンで管理する。ユーザーターンは自動録音＋タイマーで録音送信後に `setTurnToAi()` でAIターンへ戻る。スパイク割り込みは廃止し、動揺データは常時収集してAI応答の文脈として利用する。

**Tech Stack:** FastAPI + asyncio（バックエンド）、React + hooks（フロントエンド）、MediaRecorder API（録音）

---

## Task 1: mock_gemini_session — start_session をイントロ一回送信に変更

`_script_loop`（継続ループ）を廃止し、`start_session` でイントロを1回送信して `ai_turn_end` を送信する。

**Files:**
- Modify: `backend/src/mock_gemini_session.py`
- Test: `backend/tests/test_mock_gemini_session.py`

**Step 1: 失敗するテストを追加する**

`backend/tests/test_mock_gemini_session.py` の末尾に追加:

```python
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
```

**Step 2: テストが失敗することを確認する**

```bash
cd backend
uv run pytest tests/test_mock_gemini_session.py::test_start_session_sends_ai_turn_end -v
```

期待: FAILED（`ai_turn_end` はまだ送信されていない）

**Step 3: `start_session` を実装する**

`backend/src/mock_gemini_session.py` の `start_session` と `stop` を以下に差し替える。`_script_loop` は削除するが `_vibration_loop` は残す。

```python
async def start_session(self):
    """イントロ（台本1エントリ）を送信してからユーザーターンへ渡す。
    振動モックはバックグラウンドで継続する。"""
    self._running = True
    self._vibration_task = asyncio.create_task(self._vibration_loop())

    entry = _READING_SCRIPT[0]
    if self._broadcast_callback:
        await self._broadcast_callback({"type": "ai_audio", "url": entry["audio"]})
        for chunk in _chunks(entry["text"], size=8):
            await self._broadcast_callback({"type": "ai_text", "text": chunk})
            await asyncio.sleep(0.05)
        await self._broadcast_callback({"type": "ai_turn_end"})

def stop(self):
    """テスト用にループを止める"""
    self._running = False
    if self._task:
        self._task.cancel()
        self._task = None
    if self._vibration_task:
        self._vibration_task.cancel()
        self._vibration_task = None
```

また、クラスの `__init__` から `self._task` の初期化が必要なら確認する（既存コードに `self._task: asyncio.Task | None = None` がある）。`_script_loop` メソッド自体は削除してよい。

**Step 4: テストが通ることを確認する**

```bash
cd backend
uv run pytest tests/test_mock_gemini_session.py -v
```

期待: 全テスト PASSED

> **注意:** 既存テスト `test_start_session_calls_broadcast` はループ廃止後も `start_session` の awaitable 完了後にメッセージがすでに delivered されているため引き続き通過する。

**Step 5: コミットする**

```bash
git add backend/src/mock_gemini_session.py backend/tests/test_mock_gemini_session.py
git commit -m "feat: replace script_loop with one-shot intro + ai_turn_end in mock session"
```

---

## Task 2: mock_gemini_session — receive_audio に ai_turn_end を追加

**Files:**
- Modify: `backend/src/mock_gemini_session.py`
- Test: `backend/tests/test_mock_gemini_session.py`

**Step 1: 失敗するテストを追加する**

```python
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
```

**Step 2: テストが失敗することを確認する**

```bash
cd backend
uv run pytest tests/test_mock_gemini_session.py::test_receive_audio_sends_ai_turn_end -v
```

期待: FAILED

**Step 3: `receive_audio` の末尾に `ai_turn_end` 送信を追加する**

```python
async def receive_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav"):
    """ユーザー音声を受け取り、台本の次のセリフを返す（音声内容は無視）"""
    if not self._broadcast_callback:
        return
    if not hasattr(self, '_audio_idx'):
        self._audio_idx = 0
    entry = _READING_SCRIPT[self._audio_idx % len(_READING_SCRIPT)]
    self._audio_idx += 1
    await self._broadcast_callback({"type": "ai_audio", "url": entry["audio"]})
    for chunk in _chunks(entry["text"], size=8):
        await self._broadcast_callback({"type": "ai_text", "text": chunk})
        await asyncio.sleep(0.05)
    await self._broadcast_callback({"type": "ai_turn_end"})
```

**Step 4: テストが通ることを確認する**

```bash
cd backend
uv run pytest tests/test_mock_gemini_session.py -v
```

期待: 全テスト PASSED

**Step 5: コミットする**

```bash
git add backend/src/mock_gemini_session.py backend/tests/test_mock_gemini_session.py
git commit -m "feat: send ai_turn_end after receive_audio response in mock session"
```

---

## Task 3: two_stage_session — receive_audio に ai_turn_end を追加

**Files:**
- Modify: `backend/src/two_stage_session.py`
- Test: `backend/tests/test_two_stage_session.py`

**Step 1: 失敗するテストを追加する**

`backend/tests/test_two_stage_session.py` の末尾に追加:

```python
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
```

**Step 2: テストが失敗することを確認する**

```bash
cd backend
uv run pytest tests/test_two_stage_session.py::test_receive_audio_sends_ai_turn_end -v
```

期待: FAILED

**Step 3: `receive_audio` の末尾に `ai_turn_end` 送信を追加する**

`backend/src/two_stage_session.py` の `receive_audio` メソッド末尾（`self._history = self._history[-12:]` の後）に追加:

```python
await self._broadcast_callback({"type": "ai_turn_end"})
```

**Step 4: テストが通ることを確認する**

```bash
cd backend
uv run pytest tests/test_two_stage_session.py -v
```

期待: 全テスト PASSED

**Step 5: コミットする**

```bash
git add backend/src/two_stage_session.py backend/tests/test_two_stage_session.py
git commit -m "feat: send ai_turn_end after receive_audio response in two_stage_session"
```

---

## Task 4: main.py — スパイク割り込みを削除

`/ws/sensor` ハンドラの `is_spike()` チェックと `send_push()` 呼び出しを削除する。センサーパルスの記録と `agitation_update` 配信は継続する。

**Files:**
- Modify: `backend/src/main.py`

**Step 1: 変更箇所を確認する**

`main.py` の `sensor_ws` 関数内、以下のブロックを削除する:

```python
# 削除対象
if engine.is_spike():
    asyncio.create_task(
        gemini.send_push(snapshot["level"], snapshot["trend"])
    )
```

**Step 2: 削除後の `sensor_ws` 全体**

```python
@app.websocket("/ws/sensor")
async def sensor_ws(websocket: WebSocket):
    """ラズパイからの振動データを受信する"""
    await websocket.accept()
    print("[Sensor WS] Raspberry Pi connected")
    try:
        while True:
            data = await websocket.receive_text()
            if data.strip() == "1":
                engine.record_pulse()
                snapshot = engine.snapshot()
                await broadcast_to_frontend({
                    "type": "agitation_update",
                    "level": snapshot["level"],
                    "trend": snapshot["trend"]
                })
    except WebSocketDisconnect:
        print("[Sensor WS] Raspberry Pi disconnected")
```

**Step 3: バックエンドテストをすべて実行する**

```bash
cd backend
uv run pytest tests -v
```

期待: 21+ PASSED（既存テストが引き続き通過）

**Step 4: コミットする**

```bash
git add backend/src/main.py
git commit -m "feat: remove spike interrupt from sensor handler"
```

---

## Task 5: useBackendWS.js — turn ステートと ai_turn_end ハンドリング

**Files:**
- Modify: `frontend/src/hooks/useBackendWS.js`

**Step 1: 現在のファイルを確認する**

`frontend/src/hooks/useBackendWS.js` を開き、現在の実装を確認する。現在は `agitationLevel`, `agitationTrend`, `aiText`, `aiAudioUrl`, `connected` を返している。

**Step 2: `turn` ステートと `ai_turn_end` ハンドラを追加する**

ファイル全体を以下に差し替える:

```javascript
import { useCallback, useEffect, useRef, useState } from 'react'

export function useBackendWS() {
  const [agitationLevel, setAgitationLevel] = useState(0)
  const [agitationTrend, setAgitationTrend] = useState('stable')
  const [aiText, setAiText] = useState('')
  const [aiAudioUrl, setAiAudioUrl] = useState(null)
  const [connected, setConnected] = useState(false)
  const [turn, setTurn] = useState('ai')
  const wsRef = useRef(null)

  useEffect(() => {
    const wsUrl = import.meta.env.VITE_BACKEND_WS_URL ?? 'ws://localhost:8000/ws/frontend'
    const httpBase = wsUrl.replace(/^ws/, 'http').replace(/\/ws\/.*$/, '')

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'agitation_update') {
          setAgitationLevel(msg.level ?? 0)
          setAgitationTrend(msg.trend ?? 'stable')
        } else if (msg.type === 'ai_text') {
          setAiText((prev) => prev + msg.text)
        } else if (msg.type === 'ai_audio') {
          setAiAudioUrl(httpBase + msg.url)
        } else if (msg.type === 'ai_turn_end') {
          setTurn('user')
          setAiText('')
        }
      } catch {
        // ignore parse errors
      }
    }

    return () => {
      ws.close()
    }
  }, [])

  const setTurnToAi = useCallback(() => setTurn('ai'), [])

  return { agitationLevel, agitationTrend, aiText, aiAudioUrl, connected, turn, setTurnToAi }
}
```

**Step 3: フロントビルドが通ることを確認する**

```bash
cd frontend
npm run build
```

期待: ビルド成功（エラーなし）

**Step 4: コミットする**

```bash
git add frontend/src/hooks/useBackendWS.js
git commit -m "feat: add turn state and ai_turn_end handling to useBackendWS"
```

---

## Task 6: useVAD.js — ユーザーターン開始時に自動録音

**Files:**
- Modify: `frontend/src/hooks/useVAD.js`

**Step 1: 現在のシグネチャを確認する**

現在: `useVAD({ httpBase, maxSeconds = DEFAULT_MAX_SECONDS })`
変更後: `useVAD({ httpBase, maxSeconds = DEFAULT_MAX_SECONDS, turn, onRecordingComplete })`

**Step 2: `turn` が `'user'` になったときに自動録音開始する `useEffect` を追加する**

既存の cleanup `useEffect`（最後の `useEffect`）の直前に以下を追加する:

```javascript
// turn が 'user' になったら自動録音開始
useEffect(() => {
  if (turn === 'user') {
    startRecording()
  }
  // turn が 'ai' に戻ったとき録音中なら停止
  if (turn === 'ai') {
    stopRecording()
  }
}, [turn]) // eslint-disable-line react-hooks/exhaustive-deps
```

**Step 3: `recorder.onstop` に `onRecordingComplete` 呼び出しを追加する**

既存の `recorder.onstop` を以下に差し替える:

```javascript
recorder.onstop = async () => {
  clearTimers()
  setIsSpeaking(false)
  setTimeLeft(maxSeconds)

  const blob = new Blob(chunksRef.current, {
    type: recorder.mimeType || 'audio/webm',
  })
  chunksRef.current = []
  await sendRecordedAudio(blob)
  onRecordingComplete?.()
}
```

**Step 4: 関数シグネチャを更新する**

ファイル先頭の関数定義を:
```javascript
export function useVAD({ httpBase, maxSeconds = DEFAULT_MAX_SECONDS }) {
```
↓
```javascript
export function useVAD({ httpBase, maxSeconds = DEFAULT_MAX_SECONDS, turn, onRecordingComplete }) {
```

**Step 5: フロントビルドが通ることを確認する**

```bash
cd frontend
npm run build
```

期待: ビルド成功

**Step 6: コミットする**

```bash
git add frontend/src/hooks/useVAD.js
git commit -m "feat: auto-start recording when turn becomes user in useVAD"
```

---

## Task 7: SessionPage.jsx — 録音ボタン削除・ターン別UI

**Files:**
- Modify: `frontend/src/pages/SessionPage.jsx`

**Step 1: 現在の SessionPage を確認する**

現在は `useVAD` から `startRecording`, `stopRecording` を受け取り、ボタンで制御している。これを削除してターン表示に変える。

**Step 2: `SessionPage` を以下に差し替える**

```jsx
import { useEffect, useRef } from 'react'
import { KirbyMock } from '../components/KirbyMock'
import { useVAD } from '../hooks/useVAD'

const SESSION_SECONDS = 120

export function SessionPage({ agitationLevel, aiText, aiAudioUrl, httpBase, turn, setTurnToAi, onEnd }) {
  const [timeLeft, setTimeLeft] = useState(SESSION_SECONDS)
  const isTalking = aiText.length > 0
  const audioRef = useRef(null)
  const { isSpeaking, vadError, isSending, timeLeft: recordingTimeLeft } =
    useVAD({ httpBase, maxSeconds: 10, turn, onRecordingComplete: setTurnToAi })

  useEffect(() => {
    if (timeLeft <= 0) {
      onEnd()
      return
    }
    const t = setTimeout(() => setTimeLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [timeLeft, onEnd])

  useEffect(() => {
    if (!aiAudioUrl) return
    if (audioRef.current) {
      audioRef.current.pause()
    }
    const audio = new Audio(aiAudioUrl)
    audioRef.current = audio
    audio.play().catch(() => {})
  }, [aiAudioUrl])

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-800 text-white relative">
      <div className="absolute top-4 right-4 text-gray-400 text-sm bg-gray-900 px-3 py-1 rounded">
        残り {timeLeft}s
      </div>
      <div className="absolute top-4 left-4 text-xs text-gray-500">
        動揺率: {agitationLevel}%
      </div>
      {vadError && (
        <div className="absolute bottom-16 left-1/2 -translate-x-1/2 text-xs text-yellow-400 bg-black/60 px-3 py-1 rounded max-w-xs text-center">
          マイク: {vadError}
        </div>
      )}
      {turn === 'user' && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-red-400 bg-black/60 px-3 py-1 rounded">
          🎤 話してください... 残り {recordingTimeLeft}s
          {isSending && <span className="ml-2 text-gray-300">送信中...</span>}
        </div>
      )}
      <KirbyMock isTalking={isTalking} />
      <div className="mt-8 max-w-md text-center min-h-[4rem] px-4">
        <p className="text-lg leading-relaxed">{aiText}</p>
      </div>
    </div>
  )
}
```

> **注意:** `useState` の import が必要。ファイル先頭の `import { useEffect, useRef, useState } from 'react'` に `useState` があることを確認すること。

**Step 3: App.jsx で turn / setTurnToAi を SessionPage に渡す**

`App.jsx` で `useBackendWS()` の戻り値に `turn`, `setTurnToAi` が含まれているはずなので、`SessionPage` にpropsとして渡す。

現在の `App.jsx` を確認して、`SessionPage` の呼び出し箇所に `turn={turn} setTurnToAi={setTurnToAi}` を追加する。

**Step 4: フロントビルドが通ることを確認する**

```bash
cd frontend
npm run build
```

期待: ビルド成功

**Step 5: コミットする**

```bash
git add frontend/src/pages/SessionPage.jsx frontend/src/App.jsx
git commit -m "feat: turn-based UI in SessionPage, remove recording button"
```

---

## Task 8: 統合動作確認

**Step 1: バックエンド全テストを実行する**

```bash
cd backend
uv run pytest tests -v
```

期待: 全テスト PASSED

**Step 2: docker compose で起動して動作確認する**

```bash
docker compose up --build
```

ブラウザで `http://localhost:5173` を開き、以下を確認する:

- [ ] セッション開始時にAIがイントロを喋る
- [ ] イントロ終了後に「話してください 🎤」と録音カウントダウンが表示される
- [ ] 10秒後に自動的に録音停止・送信され、AIが応答する
- [ ] AIの応答後に再度「話してください 🎤」表示に戻る
- [ ] 動揺率が画面左上に表示され続ける

**Step 3: 完了**

問題があれば `superpowers:systematic-debugging` スキルを使ってデバッグする。
