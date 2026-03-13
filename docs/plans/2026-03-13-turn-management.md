# Turn Management Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `useVAD` を廃止し、録音・音声再生・SSE受信・ターン管理を `useSession` に統合する。セッションはユーザーターンから開始し、イントロを廃止する。

**Architecture:** `useSession` が turn state・MediaRecorder・音声キュー・SSE を全て ref ベースで管理し、stale closure バグを排除する。バックエンドの `/api/session/start` と `intro()` メソッドも同時に削除する。

**Tech Stack:** React (useCallback/useEffect/useRef/useState), MediaRecorder API, fetch ReadableStream (SSE), FastAPI, pytest

---

### Task 1: バックエンド — `intro()` と `/api/session/start` を削除

**Files:**
- Modify: `backend/src/two_stage_session.py`
- Modify: `backend/src/main.py`
- Modify: `backend/tests/test_two_stage_session.py`

**Step 1: `two_stage_session.py` から `intro()` メソッドを削除**

`TwoStageSessionManager` クラスの `intro()` メソッド（56〜79行目）を丸ごと削除する。

**Step 2: `main.py` から `/api/session/start` と INTRO_AUDIO_URL を削除**

削除対象:
```python
INTRO_AUDIO_URL = "/audio/tts/intro.wav"
```
および `session_start()` 関数全体:
```python
@app.get("/api/session/start")
async def session_start():
    ...
```

**Step 3: テストから `intro()` 関連を削除**

`test_two_stage_session.py` から以下を削除:
- `# --- intro() tests ---` ブロック（`test_intro_yields_intro_and_turn_end` と `test_intro_uses_fallback_text_on_empty_response`）

**Step 4: テストが通ることを確認**

```bash
cd .worktrees/feat/sse-tts-no-websocket/backend
uv run pytest tests -v
```

期待: 削除した2テスト分が減り、残り全件 PASS

**Step 5: コミット**

```bash
git add backend/src/main.py backend/src/two_stage_session.py backend/tests/test_two_stage_session.py
git commit -m "feat: remove intro endpoint and TwoStageSessionManager.intro()"
```

---

### Task 2: フロントエンド — `useSession.js` を全面書き直し

**Files:**
- Modify: `frontend/src/hooks/useSession.js`

**Step 1: 以下のコードで `useSession.js` を丸ごと置き換える**

```javascript
import { useCallback, useEffect, useRef, useState } from 'react'

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

export function useSession() {
  const [turn, setTurn] = useState('user')   // 最初からユーザーターン
  const [aiText, setAiText] = useState('')
  const [vadError, setVadError] = useState(null)
  const [timeLeft, setTimeLeft] = useState(MAX_RECORD_SECONDS)

  // 録音 refs
  const streamRef = useRef(null)
  const recorderRef = useRef(null)
  const chunksRef = useRef([])
  const countdownRef = useRef(null)
  const stopTimerRef = useRef(null)

  // 音声再生 refs
  const audioQueueRef = useRef([])
  const isPlayingRef = useRef(false)
  const sseCompleteRef = useRef(false)

  // ----- 音声再生 -----

  const playNext = useCallback(() => {
    if (isPlayingRef.current) return
    const url = audioQueueRef.current.shift()
    if (!url) {
      if (sseCompleteRef.current) setTurn('user')
      return
    }
    isPlayingRef.current = true
    const audio = new Audio(url)
    const onDone = () => {
      isPlayingRef.current = false
      playNext()
    }
    audio.onended = onDone
    audio.onerror = onDone
    audio.play().catch(onDone)
  }, [])

  // ----- 録音 -----

  const clearTimers = useCallback(() => {
    if (countdownRef.current) { clearInterval(countdownRef.current); countdownRef.current = null }
    if (stopTimerRef.current) { clearTimeout(stopTimerRef.current); stopTimerRef.current = null }
  }, [])

  const startRecording = useCallback(async () => {
    setVadError(null)
    try {
      if (!streamRef.current) {
        streamRef.current = await navigator.mediaDevices.getUserMedia({ audio: true })
      }
      const preferredType = 'audio/webm;codecs=opus'
      const options = MediaRecorder.isTypeSupported(preferredType) ? { mimeType: preferredType } : undefined
      const recorder = new MediaRecorder(streamRef.current, options)
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => { if (e.data?.size > 0) chunksRef.current.push(e.data) }
      recorder.onerror = (e) => setVadError(e.error?.message ?? '録音エラー')
      recorder.onstop = async () => {
        clearTimers()
        setTimeLeft(MAX_RECORD_SECONDS)
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || 'audio/webm' })
        chunksRef.current = []
        if (blob.size > 0) await sendAudio(blob, recorder.mimeType || 'audio/webm')
        else setTurn('user') // 空なら即ユーザーターンに戻す
      }

      recorder.start()
      setTimeLeft(MAX_RECORD_SECONDS)
      countdownRef.current = setInterval(() => setTimeLeft((t) => Math.max(0, t - 1)), 1000)
      stopTimerRef.current = setTimeout(() => {
        if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
      }, MAX_RECORD_SECONDS * 1000)
    } catch (err) {
      setVadError(err?.message ?? 'マイク初期化失敗')
    }
  }, [clearTimers]) // sendAudio は後で ref 経由で参照

  // sendAudio を ref 経由で呼ぶことで useCallback の循環依存を回避
  const sendAudioRef = useRef(null)

  const sendAudio = useCallback(async (blob, mimeType) => {
    // AI ターン開始
    audioQueueRef.current = []
    isPlayingRef.current = false
    sseCompleteRef.current = false
    setTurn('ai')
    setAiText('')

    try {
      const response = await fetch('/api/audio', {
        method: 'POST',
        headers: { 'Content-Type': mimeType },
        body: blob,
      })
      for await (const event of readSseStream(response)) {
        if (event.type === 'stage1' || event.type === 'stage2') {
          setAiText((prev) => prev + event.text)
          if (event.audio_url) {
            audioQueueRef.current.push(event.audio_url)
            playNext()
          }
        } else if (event.type === 'turn_end') {
          sseCompleteRef.current = true
          if (!isPlayingRef.current && audioQueueRef.current.length === 0) setTurn('user')
        }
      }
    } catch (err) {
      console.error('[useSession] sendAudio error:', err)
      setTurn('user')
    }
  }, [playNext])

  // startRecording の onstop から sendAudio を呼べるよう ref に保持
  useEffect(() => { sendAudioRef.current = sendAudio }, [sendAudio])

  // ----- turn 変化で録音開始/停止 -----

  const startRecordingRef = useRef(startRecording)
  useEffect(() => { startRecordingRef.current = startRecording }, [startRecording])

  useEffect(() => {
    if (turn === 'user') {
      startRecordingRef.current()
    } else {
      clearTimers()
      if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
    }
  }, [turn, clearTimers])

  // ----- アンマウント時クリーンアップ -----

  useEffect(() => {
    return () => {
      clearTimers()
      if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
      streamRef.current?.getTracks().forEach((t) => t.stop())
    }
  }, [clearTimers])

  return { turn, aiText, vadError, timeLeft }
}
```

**注意点:**
- `startRecording` の `onstop` 内で `sendAudio` を呼ぶため、`sendAudioRef` を経由して循環依存を回避する
- `startRecordingRef` を経由して `turn` effect から `startRecording` を呼ぶことで stale closure を回避する
- `turn='user'` が初期値なのでマウント直後に録音が始まる

**Step 2: ブラウザで動作確認（docker compose up 後）**

- `http://localhost:5173` でセッション画面に遷移
- 「🎤 話してください... 残り 10s」が表示されカウントが減ること
- 10秒後に AI が返答すること

**Step 3: コミット**

```bash
git add frontend/src/hooks/useSession.js
git commit -m "feat: integrate recording and audio playback into useSession, start with user turn"
```

---

### Task 3: フロントエンド — `useVAD.js` 削除と `SessionPage.jsx` 整理

**Files:**
- Delete: `frontend/src/hooks/useVAD.js`
- Modify: `frontend/src/pages/SessionPage.jsx`
- Modify: `frontend/src/App.jsx`

**Step 1: `useVAD.js` を削除**

```bash
rm .worktrees/feat/sse-tts-no-websocket/frontend/src/hooks/useVAD.js
```

**Step 2: `SessionPage.jsx` を以下に置き換え**

```jsx
import { useEffect, useState } from 'react'
import { KirbyMock } from '../components/KirbyMock'

const SESSION_SECONDS = 120

export function SessionPage({ turn, aiText, vadError, timeLeft, onEnd }) {
  const [sessionTimeLeft, setSessionTimeLeft] = useState(SESSION_SECONDS)

  useEffect(() => {
    if (sessionTimeLeft <= 0) { onEnd(); return }
    const t = setTimeout(() => setSessionTimeLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [sessionTimeLeft, onEnd])

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-800 text-white relative">
      <div className="absolute top-4 right-4 text-gray-400 text-sm bg-gray-900 px-3 py-1 rounded">
        残り {sessionTimeLeft}s
      </div>
      {vadError && (
        <div className="absolute bottom-16 left-1/2 -translate-x-1/2 text-xs text-yellow-400 bg-black/60 px-3 py-1 rounded max-w-xs text-center">
          マイク: {vadError}
        </div>
      )}
      {turn === 'user' && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-red-400 bg-black/60 px-3 py-1 rounded">
          🎤 話してください... 残り {timeLeft}s
        </div>
      )}
      <KirbyMock isTalking={turn === 'ai' && aiText.length > 0} />
      <div className="mt-8 max-w-md text-center min-h-[4rem] px-4">
        <p className="text-lg leading-relaxed">{aiText}</p>
      </div>
    </div>
  )
}
```

**Step 3: `App.jsx` を以下に置き換え**

```jsx
import { useState } from 'react'
import { useSession } from './hooks/useSession'
import { TitlePage } from './pages/TitlePage'
import { RulesPage } from './pages/RulesPage'
import { SessionPage } from './pages/SessionPage'
import { EndPage } from './pages/EndPage'

export default function App() {
  const [page, setPage] = useState('title')
  const { turn, aiText, vadError, timeLeft } = useSession()

  return (
    <div>
      {page === 'title' && <TitlePage onStart={() => setPage('rules')} />}
      {page === 'rules' && <RulesPage onReady={() => setPage('session')} />}
      {page === 'session' && (
        <SessionPage
          turn={turn}
          aiText={aiText}
          vadError={vadError}
          timeLeft={timeLeft}
          onEnd={() => setPage('end')}
        />
      )}
      {page === 'end' && <EndPage onBack={() => setPage('title')} />}
    </div>
  )
}
```

**Step 4: ブラウザで動作確認**

- ページ遷移が正常に動くこと
- セッションページでターンが繰り返されること

**Step 5: コミット**

```bash
git add frontend/src/hooks/ frontend/src/pages/SessionPage.jsx frontend/src/App.jsx
git commit -m "feat: remove useVAD, simplify SessionPage and App"
```

---

### Task 4: `useSession` の sendAudio 循環依存を修正

**注意:** Task 2 の実装で `recorder.onstop` が `sendAudio` を直接呼んでいるが、
`sendAudioRef` を使った間接呼び出しになっていない。以下を確認・修正する。

**Files:**
- Modify: `frontend/src/hooks/useSession.js`

**Step 1: `recorder.onstop` 内の sendAudio 呼び出しを `sendAudioRef.current` に変更**

`recorder.onstop` の中の:
```javascript
if (blob.size > 0) await sendAudio(blob, recorder.mimeType || 'audio/webm')
```

を:
```javascript
if (blob.size > 0) await sendAudioRef.current?.(blob, recorder.mimeType || 'audio/webm')
```

に変更する。

**Step 2: 動作確認**

10秒録音 → AI 返答 → ユーザーターン の1サイクルが正常に動くこと。

**Step 3: コミット**

```bash
git add frontend/src/hooks/useSession.js
git commit -m "fix: use sendAudioRef to avoid stale closure in recorder.onstop"
```

---

### Task 5: 最終動作確認

**Step 1: バックエンドテスト**

```bash
cd .worktrees/feat/sse-tts-no-websocket/backend
uv run pytest tests -v
```

期待: 全件 PASS（intro テスト2件分は削除済み）

**Step 2: エンドツーエンド確認**

```
1. docker compose up (ワークツリーから)
2. http://localhost:5173 を開く
3. タイトル → ルール → セッションに遷移
4. 「🎤 話してください... 残り 10s」が表示されカウントダウンが動く
5. 10秒後に AI が返答し、音声が再生される
6. 再生完了後にユーザーターンに戻る
7. 2回目以降も同様に繰り返される
```
