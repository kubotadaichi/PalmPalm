# SSE + TTS + WebSocket 廃止 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** WebSocket を廃止し、AI レスポンスを SSE（Server-Sent Events）で返す形に刷新。Gemini TTS で stage1/stage2 の音声を生成し、ラズパイが動揺度 API を提供する。

**Architecture:** フロント → `POST /api/audio` → バックエンドが SSE でストリーム返却（stage1 text+audio → 待機 → stage2 text+audio → turn_end）。動揺度はバックエンドがラズパイの `GET /agitation` をポーリング。振動エフェクトは廃止。

**Tech Stack:** FastAPI StreamingResponse, SSE, google-genai TTS (`gemini-2.5-flash-preview-tts`), httpx（ラズパイ API 呼び出し）, React fetch + ReadableStream

> **注意:** `docs/plans/2026-03-13-gemini-tts.md` は本プランに置き換えられます。

---

### Task 1: httpx を本番依存に追加

**Files:**
- Modify: `backend/pyproject.toml`

**Step 1: 依存を追加**

`backend/pyproject.toml` の `dependencies` に `httpx` を追加：

```toml
dependencies = [
    "fastapi>=0.135.1",
    "google-genai>=1.66.0",
    "httpx>=0.28.0",
    "pyaudio>=0.2.14",
    "python-dotenv>=1.2.2",
    "uvicorn>=0.41.0",
    "websockets>=16.0",
]
```

**Step 2: コミット**

```bash
cd backend && git add pyproject.toml
git commit -m "chore: add httpx to main dependencies"
```

---

### Task 2: TTS ヘルパー関数を追加

**Files:**
- Modify: `backend/src/two_stage_session.py`
- Test: `backend/tests/test_two_stage_session.py`

**Step 1: 既存テストが通ることを確認**

```bash
cd backend && python -m pytest tests/ -v
```

**Step 2: WAV ヘルパーのテストを書く**

`backend/tests/test_two_stage_session.py` に追記：

```python
import base64, io, wave
from unittest.mock import MagicMock, patch
import pytest
from src.two_stage_session import _pcm_to_wav_bytes, _wav_duration, _save_tts_wav


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
```

**Step 3: テストが失敗することを確認**

```bash
python -m pytest tests/test_two_stage_session.py::test_pcm_to_wav_bytes_creates_valid_wav -v
```

Expected: FAIL

**Step 4: ヘルパー関数を実装**

`backend/src/two_stage_session.py` の末尾の `_chunks` 関数の後に追記。
また、ファイル冒頭の import に `import io`, `import uuid`, `import wave` を追加（既存 import と重複しないこと）。

```python
# --- ファイル冒頭 import に追加 ---
import io
import uuid
import wave
from pathlib import Path

# --- ファイル末尾（_chunks の後）に追記 ---

TTS_DIR = Path("assets/audio/tts")
TTS_SAMPLE_RATE = 24000


def _pcm_to_wav_bytes(pcm: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def _wav_duration(wav_bytes: bytes) -> float:
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        return wf.getnframes() / wf.getframerate()


def _save_tts_wav(pcm: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> tuple[str, float]:
    """PCM を WAV として保存し (url_path, duration_sec) を返す。古いファイルは20件超で削除。"""
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(TTS_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    while len(files) >= 20:
        files.pop(0).unlink(missing_ok=True)
    filename = f"tts_{uuid.uuid4().hex}.wav"
    wav_bytes = _pcm_to_wav_bytes(pcm, sample_rate)
    (TTS_DIR / filename).write_bytes(wav_bytes)
    return f"/audio/tts/{filename}", _wav_duration(wav_bytes)
```

**Step 5: テストが通ることを確認**

```bash
python -m pytest tests/test_two_stage_session.py -v
```

Expected: 全 PASS

**Step 6: コミット**

```bash
git add src/two_stage_session.py tests/test_two_stage_session.py
git commit -m "feat: add PCM-to-WAV helpers and TTS file management"
```

---

### Task 3: `TwoStageSessionManager` を非同期ジェネレータに書き換え

**Files:**
- Modify: `backend/src/two_stage_session.py`（全面書き換え）

現在の `TwoStageSessionManager` クラスを以下で**丸ごと置き換える**（ヘルパー関数はそのまま残す）。

クラス外の定数（`MODEL` など）も以下に統一：

```python
MODEL = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_VOICE = "Kore"
STAGE2_LEAD_SECONDS = float(os.getenv("STAGE2_LEAD_SECONDS", "3"))
AGITATION_API_URL = os.getenv("AGITATION_API_URL", "")  # 例: http://raspberrypi.local:8001

STAGE1_SYSTEM = (
    "あなたはAI手相占い師「ぱむぱむ」です。"
    "まずは会話の流れに沿って、低いトーンで神秘的に2文程度で語ってください。"
)

STAGE2_SYSTEM = (
    "あなたはAI手相占い師「ぱむぱむ」です。"
    "動揺データ(level, trend)を踏まえ、占いが当たっている証拠として"
    "テンションを少し上げて1〜2文で追い込みコメントを返してください。"
)
```

クラス本体：

```python
import base64 as _b64
from typing import AsyncGenerator
import httpx


class TwoStageSessionManager:
    def __init__(self, agitation_api_url: str = AGITATION_API_URL, client=None):
        self.agitation_api_url = agitation_api_url
        self.client = client or genai.Client(
            api_key=os.getenv("GEMINI_API_KEY"),
            http_options={"timeout": 15},
        )
        self._history: list[dict] = []
        self._lock = asyncio.Lock()

    async def intro(self) -> AsyncGenerator[dict, None]:
        """イントロを生成して SSE イベントを yield する。"""
        prompt = "手相占いを始めます。相手の手を見て、神秘的なイントロを2文で述べてください。"
        contents = [{"role": "user", "parts": [{"text": prompt}]}]
        try:
            text = await self._generate_text(contents, STAGE1_SYSTEM)
        except Exception as e:
            print(f"[TwoStage] intro text error: {e}")
            text = ""
        if not text:
            text = "あなたの手のひらには、深い運命の線が刻まれています。今日は特別なものが見えます。"

        try:
            audio_url, _ = await self._generate_tts(text)
        except Exception as e:
            print(f"[TwoStage] intro TTS error: {e}")
            audio_url = None

        self._history.extend([
            {"role": "user", "parts": [{"text": prompt}]},
            {"role": "model", "parts": [{"text": text}]},
        ])
        yield {"type": "intro", "text": text, "audio_url": audio_url}
        yield {"type": "turn_end"}

    async def receive_audio(
        self, audio_bytes: bytes, mime_type: str = "audio/webm"
    ) -> AsyncGenerator[dict, None]:
        """ユーザー音声を受け取り stage1 → stage2 を SSE イベントで yield する。"""
        async with self._lock:
            audio_part = {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": _b64.b64encode(audio_bytes).decode(),
                }
            }

            # Stage 1
            stage1_prompt = (
                "占いの続きを一言ください。"
                "まだ相手を煽りすぎず、神秘的なトーンを維持してください。"
            )
            contents1 = self._history + [
                {"role": "user", "parts": [audio_part, {"text": stage1_prompt}]}
            ]
            try:
                stage1_text = await self._generate_text(contents1, STAGE1_SYSTEM)
            except Exception as e:
                print(f"[TwoStage] stage1 text error: {e}")
                stage1_text = ""
            if not stage1_text:
                stage1_text = "手のひらに、まだ語られていない流れが見えます。"

            try:
                stage1_url, stage1_duration = await self._generate_tts(stage1_text)
            except Exception as e:
                print(f"[TwoStage] stage1 TTS error: {e}")
                stage1_url, stage1_duration = None, 0.0

            yield {"type": "stage1", "text": stage1_text, "audio_url": stage1_url}

            # stage1 再生中に stage2 生成開始するまで待機
            wait_sec = max(0.0, stage1_duration - STAGE2_LEAD_SECONDS)
            if wait_sec > 0:
                await asyncio.sleep(wait_sec)

            # Stage 2（最新動揺度を取得）
            snapshot = await self._fetch_agitation()
            stage2_prompt = (
                f"動揺データ: level={snapshot['level']}, trend={snapshot['trend']}。"
                f"直前の発言: {stage1_text} "
                "この情報を踏まえ、当たっている実感を強める補足をしてください。"
            )
            contents2 = self._history + [
                {"role": "user", "parts": [{"text": stage2_prompt}]}
            ]
            try:
                stage2_text = await self._generate_text(contents2, STAGE2_SYSTEM)
            except Exception as e:
                print(f"[TwoStage] stage2 text error: {e}")
                stage2_text = ""
            if not stage2_text:
                stage2_text = f"揺れは{snapshot['level']}%です。反応がもう答えになっています。"

            try:
                stage2_url, _ = await self._generate_tts(stage2_text)
            except Exception as e:
                print(f"[TwoStage] stage2 TTS error: {e}")
                stage2_url = None

            self._history.extend([
                {"role": "user", "parts": [audio_part]},
                {"role": "model", "parts": [{"text": f"{stage1_text} {stage2_text}"}]},
            ])
            self._history = self._history[-12:]

            yield {"type": "stage2", "text": stage2_text, "audio_url": stage2_url}
            yield {"type": "turn_end"}

    async def _fetch_agitation(self) -> dict:
        """ラズパイの agitation API を叩く。未設定時はダミーを返す。"""
        if not self.agitation_api_url:
            return {"level": 0, "trend": "stable"}
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{self.agitation_api_url}/agitation")
                return resp.json()
        except Exception as e:
            print(f"[TwoStage] agitation fetch error: {e}")
            return {"level": 0, "trend": "stable"}

    async def _generate_text(self, contents: list, system_instruction: str) -> str:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: self._generate_text_sync(contents, system_instruction),
            ),
            timeout=20.0,
        )

    def _generate_text_sync(self, contents: list, system_instruction: str) -> str:
        response = self.client.models.generate_content(
            model=MODEL,
            contents=contents,
            config=types.GenerateContentConfig(system_instruction=system_instruction),
        )
        return (getattr(response, "text", "") or "").strip()

    async def _generate_tts(self, text: str) -> tuple[str, float]:
        loop = asyncio.get_running_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: self._generate_tts_sync(text)),
            timeout=20.0,
        )

    def _generate_tts_sync(self, text: str) -> tuple[str, float]:
        response = self.client.models.generate_content(
            model=TTS_MODEL,
            contents=text,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=TTS_VOICE
                        )
                    )
                ),
            ),
        )
        pcm = _b64.b64decode(response.candidates[0].content.parts[0].inline_data.data)
        return _save_tts_wav(pcm)
```

**Step 2: テストが通ることを確認**

```bash
python -m pytest tests/ -v
```

Expected: PASS（既存テストが壊れていないこと。`receive_audio` のインターフェースが変わるのでテストが壊れる場合は削除して OK）

**Step 3: コミット**

```bash
git add src/two_stage_session.py
git commit -m "feat: refactor TwoStageSessionManager to async generator with TTS"
```

---

### Task 4: `main.py` を WebSocket 廃止・SSE エンドポイントに書き換え

**Files:**
- Modify: `backend/src/main.py`（全面書き換え）

```python
# backend/src/main.py
"""
PalmPalm バックエンド（FastAPI）

エンドポイント:
  GET  /health              - ヘルスチェック
  GET  /api/session/start   - SSE: イントロ生成（ai_intro → turn_end）
  POST /api/audio           - SSE: ユーザー音声 → stage1 → stage2 → turn_end

環境変数:
  GEMINI_API_KEY      - Gemini API キー
  GEMINI_MODEL        - テキスト生成モデル (default: gemini-2.5-flash)
  AGITATION_API_URL   - ラズパイの agitation API ベース URL (例: http://raspberrypi.local:8001)
  STAGE2_LEAD_SECONDS - stage1 終了 N 秒前に stage2 生成開始 (default: 3)
"""
import json
import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from .two_stage_session import TwoStageSessionManager

load_dotenv()

gemini = TwoStageSessionManager()

app = FastAPI()
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)
app.mount("/audio", StaticFiles(directory="assets/audio"), name="audio")


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


@app.get("/health")
async def health():
    return {"status": "ok"}


@app.get("/api/session/start")
async def session_start():
    """イントロを SSE で返す。EventSource で接続可能。"""
    async def generate():
        async for event in gemini.intro():
            yield _sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.post("/api/audio")
async def receive_audio(request: Request):
    """ユーザー音声を受け取り stage1→stage2 を SSE で返す。"""
    audio_bytes = await request.body()
    raw_ct = request.headers.get("content-type", "audio/webm")
    mime_type = raw_ct.split(";")[0].strip() or "audio/webm"

    async def generate():
        async for event in gemini.receive_audio(audio_bytes, mime_type):
            yield _sse(event)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
```

**Step 2: サーバーを起動して手動確認**

```bash
cd backend && uvicorn src.main:app --reload
```

別ターミナルで：
```bash
curl -N http://localhost:8000/api/session/start
```

Expected: SSE イベントが流れてくること（`data: {"type": "intro", ...}` など）

**Step 3: コミット**

```bash
git add src/main.py
git commit -m "feat: replace WebSocket with SSE endpoints, remove agitation engine"
```

---

### Task 5: ラズパイ用 agitation サーバーを作成

**Files:**
- Create: `raspberry_pi/server.py`
- Create: `raspberry_pi/agitation_engine.py`（backend からコピー）

**Step 1: `agitation_engine.py` をコピー**

```bash
cp backend/src/agitation_engine.py raspberry_pi/agitation_engine.py
```

**Step 2: `raspberry_pi/server.py` を作成**

```python
"""
ラズパイ用 agitation サーバー

振動センサー検知時: POST /pulse
動揺度取得:         GET  /agitation

起動: uvicorn server:app --host 0.0.0.0 --port 8001
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from agitation_engine import AgitationEngine

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

engine = AgitationEngine(window_seconds=10, max_pulses=20)


@app.post("/pulse")
async def record_pulse():
    """振動センサー検知時に呼ぶ。GPIO スクリプトから叩く。"""
    engine.record_pulse()
    return {"ok": True}


@app.get("/agitation")
async def get_agitation():
    return engine.snapshot()
```

**Step 3: コミット**

```bash
git add raspberry_pi/
git commit -m "feat: add Raspberry Pi agitation HTTP server"
```

---

### Task 6: `useVAD.js` を POST から blob コールバックに変更

**Files:**
- Modify: `frontend/src/hooks/useVAD.js`

`useVAD` から HTTP POST ロジックを除去し、録音完了時に `onAudioReady(blob, mimeType)` を呼ぶだけにする。

変更箇所：

1. **props 変更**: `httpBase` を削除、`onRecordingComplete` を `onAudioReady` に変更

```js
// 変更前:
export function useVAD({ httpBase, maxSeconds = DEFAULT_MAX_SECONDS, turn, onRecordingComplete }) {
// 変更後:
export function useVAD({ maxSeconds = DEFAULT_MAX_SECONDS, turn, onAudioReady }) {
```

2. **`isSending` state を削除**（POST がなくなるため）

```js
// 削除: const [isSending, setIsSending] = useState(false)
```

3. **`sendRecordedAudio` 関数を削除**（`useVAD.js:37-55` を丸ごと削除）

4. **`recorder.onstop` を変更**（`useVAD.js:95-107`）:

```js
recorder.onstop = async () => {
  clearTimers()
  setIsSpeaking(false)
  setTimeLeft(maxSeconds)
  const blob = new Blob(chunksRef.current, {
    type: recorder.mimeType || 'audio/webm',
  })
  chunksRef.current = []
  if (blob.size > 0) {
    onAudioReady?.(blob, recorder.mimeType || 'audio/webm')
  }
}
```

5. **return から `isSending` を削除**:

```js
return { isSpeaking, vadError, timeLeft, isSupported, startRecording, stopRecording }
```

**Step 2: コミット**

```bash
git add frontend/src/hooks/useVAD.js
git commit -m "refactor: useVAD returns audio blob via onAudioReady callback"
```

---

### Task 7: `useSession.js` を新規作成（`useBackendWS` 置き換え）

**Files:**
- Create: `frontend/src/hooks/useSession.js`

```js
import { useCallback, useEffect, useRef, useState } from 'react'

const HTTP_BASE = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

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
        try {
          yield JSON.parse(line.slice(6))
        } catch {
          // ignore malformed
        }
      }
    }
  }
}

export function useSession() {
  const [aiText, setAiText] = useState('')
  const [aiAudioQueue, setAiAudioQueue] = useState([])
  const [turn, setTurn] = useState('ai')
  const [aiTurnEnded, setAiTurnEnded] = useState(false)
  const audioPlayedRef = useRef(0)

  const handleEvent = useCallback((event) => {
    if (event.type === 'intro' || event.type === 'stage1' || event.type === 'stage2') {
      setAiText((prev) => prev + event.text)
      if (event.audio_url) {
        setAiAudioQueue((prev) => [...prev, HTTP_BASE + event.audio_url])
      }
    } else if (event.type === 'turn_end') {
      setAiTurnEnded(true)
    }
  }, [])

  // イントロ: EventSource (GET /api/session/start)
  useEffect(() => {
    const es = new EventSource(`${HTTP_BASE}/api/session/start`)
    es.onmessage = (e) => {
      try { handleEvent(JSON.parse(e.data)) } catch {}
    }
    es.onerror = () => es.close()
    return () => es.close()
  }, [handleEvent])

  const sendAudio = useCallback(async (blob, mimeType) => {
    setTurn('ai')
    setAiText('')
    setAiAudioQueue([])
    setAiTurnEnded(false)
    audioPlayedRef.current = 0

    try {
      const response = await fetch(`${HTTP_BASE}/api/audio`, {
        method: 'POST',
        headers: { 'Content-Type': mimeType },
        body: blob,
      })
      for await (const event of readSseStream(response)) {
        handleEvent(event)
      }
    } catch (e) {
      console.error('[useSession] sendAudio error:', e)
    }
  }, [handleEvent])

  const startUserTurn = useCallback(() => {
    setTurn('user')
    setAiTurnEnded(false)
    setAiAudioQueue([])
    audioPlayedRef.current = 0
  }, [])

  const setTurnToAi = useCallback(() => setTurn('ai'), [])

  return { aiText, aiAudioQueue, turn, aiTurnEnded, audioPlayedRef, startUserTurn, setTurnToAi, sendAudio }
}
```

**Step 2: コミット**

```bash
git add frontend/src/hooks/useSession.js
git commit -m "feat: add useSession hook with SSE and audio queue"
```

---

### Task 8: `App.jsx` + `SessionPage.jsx` を更新、`VibrationEffect` 廃止

**Files:**
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/pages/SessionPage.jsx`

**Step 1: `App.jsx` を書き換え**

```jsx
import { useState } from 'react'
import { useSession } from './hooks/useSession'
import { TitlePage } from './pages/TitlePage'
import { RulesPage } from './pages/RulesPage'
import { SessionPage } from './pages/SessionPage'
import { EndPage } from './pages/EndPage'

export default function App() {
  const [page, setPage] = useState('title')
  const { aiText, aiAudioQueue, turn, aiTurnEnded, audioPlayedRef, startUserTurn, setTurnToAi, sendAudio } = useSession()

  return (
    <div>
      {page === 'title' && <TitlePage onStart={() => setPage('rules')} />}
      {page === 'rules' && <RulesPage onReady={() => setPage('session')} />}
      {page === 'session' && (
        <SessionPage
          aiText={aiText}
          aiAudioQueue={aiAudioQueue}
          audioPlayedRef={audioPlayedRef}
          turn={turn}
          aiTurnEnded={aiTurnEnded}
          startUserTurn={startUserTurn}
          setTurnToAi={setTurnToAi}
          sendAudio={sendAudio}
          onEnd={() => setPage('end')}
        />
      )}
      {page === 'end' && <EndPage onBack={() => setPage('title')} />}
    </div>
  )
}
```

**Step 2: `SessionPage.jsx` を書き換え**

```jsx
import { useEffect, useRef, useState } from 'react'
import { KirbyMock } from '../components/KirbyMock'
import { useVAD } from '../hooks/useVAD'

const SESSION_SECONDS = 120

export function SessionPage({ aiText, aiAudioQueue, audioPlayedRef, turn, aiTurnEnded, startUserTurn, setTurnToAi, sendAudio, onEnd }) {
  const [timeLeft, setTimeLeft] = useState(SESSION_SECONDS)
  const [isAudioPlaying, setIsAudioPlaying] = useState(false)
  const isTalking = aiText.length > 0
  const audioRef = useRef(null)

  const { vadError, isSpeaking, timeLeft: recordingTimeLeft } = useVAD({
    maxSeconds: 10,
    turn,
    onAudioReady: sendAudio,
  })

  // タイマー
  useEffect(() => {
    if (timeLeft <= 0) { onEnd(); return }
    const t = setTimeout(() => setTimeLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [timeLeft, onEnd])

  // audio キュー再生
  useEffect(() => {
    if (isAudioPlaying) return
    const url = aiAudioQueue[audioPlayedRef.current]
    if (!url) return
    audioPlayedRef.current += 1
    const audio = new Audio(url)
    audioRef.current = audio
    setIsAudioPlaying(true)
    audio.onended = () => setIsAudioPlaying(false)
    audio.onerror = () => setIsAudioPlaying(false)
    audio.play().catch(() => setIsAudioPlaying(false))
  }, [aiAudioQueue, isAudioPlaying, audioPlayedRef])

  // AI ターン終了 + 音声再生完了 → ユーザーターンへ
  useEffect(() => {
    if (aiTurnEnded && !isAudioPlaying && aiAudioQueue.length > 0 && audioPlayedRef.current >= aiAudioQueue.length) {
      startUserTurn()
    }
  }, [aiTurnEnded, isAudioPlaying, aiAudioQueue, audioPlayedRef, startUserTurn])

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-800 text-white relative">
      <div className="absolute top-4 right-4 text-gray-400 text-sm bg-gray-900 px-3 py-1 rounded">
        残り {timeLeft}s
      </div>
      {vadError && (
        <div className="absolute bottom-16 left-1/2 -translate-x-1/2 text-xs text-yellow-400 bg-black/60 px-3 py-1 rounded max-w-xs text-center">
          マイク: {vadError}
        </div>
      )}
      {turn === 'user' && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-red-400 bg-black/60 px-3 py-1 rounded">
          🎤 話してください... 残り {recordingTimeLeft}s
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

**Step 3: コミット**

```bash
git add frontend/src/App.jsx frontend/src/pages/SessionPage.jsx
git commit -m "refactor: remove VibrationEffect, use useSession with SSE audio queue"
```

---

### Task 9: `docker-compose.yml` と `.env.example` を更新

**Files:**
- Modify: `docker-compose.yml`
- Modify: `backend/.env.example`（あれば）

**Step 1: `docker-compose.yml` の frontend 環境変数を変更**

```yaml
# 変更前:
environment:
  - VITE_BACKEND_WS_URL=ws://localhost:8000/ws/frontend

# 変更後:
environment:
  - VITE_BACKEND_URL=http://localhost:8000
```

**Step 2: backend の environment に `AGITATION_API_URL` を追加**

```yaml
environment:
  - MOCK_MODE=false
  - AGITATION_API_URL=http://raspberrypi.local:8001  # ラズパイの IP に合わせる
```

**Step 3: `backend/.env.example` を更新**（存在する場合）

```
GEMINI_API_KEY=your_key_here
AGITATION_API_URL=http://raspberrypi.local:8001
STAGE2_LEAD_SECONDS=3
```

**Step 4: `fig up` して動作確認**

```bash
fig up
```

ブラウザで `http://localhost:5173` を開き：
1. セッションページでイントロ音声が流れること
2. 話しかけると stage1 → stage2 の音声が流れること
3. ターミナルに `[TwoStage]` ログが出ること

**Step 5: 最終コミット**

```bash
git add docker-compose.yml backend/.env.example
git commit -m "chore: update env vars for SSE architecture, remove WebSocket config"
```
