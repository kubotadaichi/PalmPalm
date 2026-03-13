# Gemini TTS 統合 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `TwoStageSessionManager` に Gemini TTS を統合し、stage1 音声再生中に stage2 を生成・送信することで継ぎ目ないリアルタイム占い音声体験を実現する。

**Architecture:** stage1 テキスト生成 → stage1 TTS → ai_audio 送信 → (D - N)秒待機 → 最新動揺度で stage2 生成 → stage2 TTS → ai_audio 送信。フロントエンドは ai_audio URL をキューに積んで順番再生する。

**Tech Stack:** `google-genai` (TTS), `wave` (stdlib, PCM→WAV変換), React useState/useRef (audio queue)

---

### Task 1: TTS ディレクトリと PCM→WAV ヘルパー

**Files:**
- Modify: `backend/src/two_stage_session.py`
- Test: `backend/tests/test_two_stage_session.py`

**Step 1: 既存テストを確認して実行**

```bash
cd backend && python -m pytest tests/test_two_stage_session.py -v
```

Expected: 既存テストが PASS することを確認。

**Step 2: WAV 変換ヘルパーのテストを書く**

`backend/tests/test_two_stage_session.py` に追記：

```python
import wave, io
from src.two_stage_session import _pcm_to_wav_bytes, _wav_duration

def test_pcm_to_wav_bytes_creates_valid_wav():
    # 1秒分のサイレント PCM（24kHz, 16bit, mono）
    pcm = bytes(24000 * 2)
    wav_bytes = _pcm_to_wav_bytes(pcm, sample_rate=24000)
    with wave.open(io.BytesIO(wav_bytes)) as wf:
        assert wf.getnchannels() == 1
        assert wf.getsampwidth() == 2
        assert wf.getframerate() == 24000

def test_wav_duration():
    pcm = bytes(24000 * 2)  # 1秒
    wav_bytes = _pcm_to_wav_bytes(pcm, sample_rate=24000)
    assert abs(_wav_duration(wav_bytes) - 1.0) < 0.01
```

**Step 3: テストが失敗することを確認**

```bash
python -m pytest tests/test_two_stage_session.py::test_pcm_to_wav_bytes_creates_valid_wav tests/test_two_stage_session.py::test_wav_duration -v
```

Expected: FAIL (`ImportError: cannot import name '_pcm_to_wav_bytes'`)

**Step 4: ヘルパー関数を実装**

`backend/src/two_stage_session.py` の末尾（`_chunks` の後）に追記：

```python
import io
import uuid
import wave
from pathlib import Path

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
```

※ `import io, uuid, wave, Path` は既存 import の直下に追記する（重複しないように）。

**Step 5: テストが通ることを確認**

```bash
python -m pytest tests/test_two_stage_session.py::test_pcm_to_wav_bytes_creates_valid_wav tests/test_two_stage_session.py::test_wav_duration -v
```

Expected: PASS

**Step 6: TTS ファイル保存ヘルパーのテストを書く**

```python
import tempfile, os
from unittest.mock import patch
from src.two_stage_session import _save_tts_wav

def test_save_tts_wav_returns_url_and_duration(tmp_path):
    with patch("src.two_stage_session.TTS_DIR", tmp_path):
        pcm = bytes(24000 * 2)  # 1秒
        url, duration = _save_tts_wav(pcm)
    assert url.startswith("/audio/tts/")
    assert url.endswith(".wav")
    assert abs(duration - 1.0) < 0.01
    # ファイルが存在する
    filename = url.split("/")[-1]
    assert (tmp_path / filename).exists()

def test_save_tts_wav_cleanup_old_files(tmp_path):
    with patch("src.two_stage_session.TTS_DIR", tmp_path):
        # 21 ファイル作る
        pcm = bytes(24000 * 2)
        for _ in range(21):
            _save_tts_wav(pcm)
        files = list(tmp_path.glob("*.wav"))
    assert len(files) <= 20
```

**Step 7: テストが失敗することを確認**

```bash
python -m pytest tests/test_two_stage_session.py::test_save_tts_wav_returns_url_and_duration tests/test_two_stage_session.py::test_save_tts_wav_cleanup_old_files -v
```

Expected: FAIL

**Step 8: `_save_tts_wav` を実装**

`_wav_duration` の後に追記：

```python
def _save_tts_wav(pcm: bytes, sample_rate: int = TTS_SAMPLE_RATE) -> tuple[str, float]:
    """PCM バイトを WAV として保存し (url_path, duration_sec) を返す。"""
    TTS_DIR.mkdir(parents=True, exist_ok=True)
    files = sorted(TTS_DIR.glob("*.wav"), key=lambda p: p.stat().st_mtime)
    while len(files) >= 20:
        files[0].unlink(missing_ok=True)
        files = files[1:]
    filename = f"tts_{uuid.uuid4().hex}.wav"
    wav_bytes = _pcm_to_wav_bytes(pcm, sample_rate)
    (TTS_DIR / filename).write_bytes(wav_bytes)
    return f"/audio/tts/{filename}", _wav_duration(wav_bytes)
```

**Step 9: テストが通ることを確認**

```bash
python -m pytest tests/test_two_stage_session.py -v
```

Expected: 全 PASS

**Step 10: コミット**

```bash
cd backend && git add src/two_stage_session.py tests/test_two_stage_session.py
git commit -m "feat: add PCM-to-WAV helpers and TTS file management"
```

---

### Task 2: `_generate_tts` メソッドを追加

**Files:**
- Modify: `backend/src/two_stage_session.py`
- Test: `backend/tests/test_two_stage_session.py`

**Step 1: `_generate_tts` のテストを書く**

```python
import asyncio, base64
from unittest.mock import MagicMock, patch
from src.two_stage_session import TwoStageSessionManager
from src.agitation_engine import AgitationEngine

def _make_tts_response(pcm: bytes):
    """genai client のモックレスポンスを作る"""
    part = MagicMock()
    part.inline_data.data = base64.b64encode(pcm).decode()
    candidate = MagicMock()
    candidate.content.parts = [part]
    resp = MagicMock()
    resp.candidates = [candidate]
    return resp

@pytest.mark.asyncio
async def test_generate_tts_returns_url_and_duration(tmp_path):
    client = MagicMock()
    pcm = bytes(24000 * 2)  # 1秒
    client.models.generate_content.return_value = _make_tts_response(pcm)

    engine = AgitationEngine()
    mgr = TwoStageSessionManager(engine, client=client)

    with patch("src.two_stage_session.TTS_DIR", tmp_path):
        url, duration = await mgr._generate_tts("こんにちは")

    assert url.startswith("/audio/tts/")
    assert abs(duration - 1.0) < 0.01
```

**Step 2: テストが失敗することを確認**

```bash
python -m pytest tests/test_two_stage_session.py::test_generate_tts_returns_url_and_duration -v
```

Expected: FAIL

**Step 3: `_generate_tts` を実装**

`TwoStageSessionManager` クラス内の `_generate_text` メソッドの後に追記：

```python
TTS_MODEL = "gemini-2.5-flash-preview-tts"
TTS_VOICE = "Kore"
```

（クラス外の定数として `MODEL` の近くに置く）

```python
    async def _generate_tts(self, text: str) -> tuple[str, float]:
        """テキストを TTS で音声化し (url_path, duration_sec) を返す。"""
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
        import base64 as _b64
        pcm = _b64.b64decode(response.candidates[0].content.parts[0].inline_data.data)
        return _save_tts_wav(pcm)
```

**Step 4: テストが通ることを確認**

```bash
python -m pytest tests/test_two_stage_session.py -v
```

Expected: 全 PASS

**Step 5: コミット**

```bash
git add src/two_stage_session.py tests/test_two_stage_session.py
git commit -m "feat: add _generate_tts method using gemini-2.5-flash-preview-tts"
```

---

### Task 3: `receive_audio` を TTS タイミング制御に書き換え

**Files:**
- Modify: `backend/src/two_stage_session.py`

`receive_audio` メソッド（現在 `src/two_stage_session.py:111-165`）を以下で**丸ごと置き換える**。

`STAGE2_LEAD_SECONDS` を定数として `TTS_VOICE` の近くに追加：

```python
STAGE2_LEAD_SECONDS = float(os.getenv("STAGE2_LEAD_SECONDS", "3"))
```

`receive_audio` を置き換え：

```python
    async def receive_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav"):
        """ユーザー音声を受け取りGeminiに渡して2段階応答を生成・broadcast"""
        if not self._broadcast_callback:
            return

        async with self._lock:
            audio_part = {
                "inline_data": {
                    "mime_type": mime_type,
                    "data": base64.b64encode(audio_bytes).decode(),
                }
            }

            # --- Stage 1 ---
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
                print(f"[TwoStage] receive_audio stage1 error: {e}")
                stage1_text = ""
            if not stage1_text:
                stage1_text = "手のひらに、まだ語られていない流れが見えます。"

            # Stage 1 TTS
            try:
                stage1_url, stage1_duration = await self._generate_tts(stage1_text)
            except Exception as e:
                print(f"[TwoStage] TTS stage1 error: {e}")
                stage1_url, stage1_duration = None, 0.0

            # Stage 1 テキスト + 音声を送信
            await self._broadcast_text(stage1_text)
            if stage1_url:
                await self._broadcast_callback({"type": "ai_audio", "url": stage1_url})

            # Stage 1 再生終了の STAGE2_LEAD_SECONDS 秒前に Stage 2 生成開始
            wait_sec = max(0.0, stage1_duration - STAGE2_LEAD_SECONDS)
            if wait_sec > 0:
                await asyncio.sleep(wait_sec)

            # --- Stage 2（最新動揺度を取得）---
            snapshot = self.engine.snapshot()
            stage2_prompt = (
                f"動揺データ: level={snapshot['level']}, trend={snapshot['trend']}。"
                f"直前の発言: {stage1_text}"
                "この情報を踏まえ、当たっている実感を強める補足をしてください。"
            )
            contents2 = self._history + [
                {"role": "user", "parts": [{"text": stage2_prompt}]}
            ]
            try:
                stage2_text = await self._generate_text(contents2, STAGE2_SYSTEM)
            except Exception as e:
                print(f"[TwoStage] receive_audio stage2 error: {e}")
                stage2_text = ""
            if not stage2_text:
                stage2_text = f"揺れは{snapshot['level']}%です。反応がもう答えになっています。"

            # Stage 2 TTS
            try:
                stage2_url, _ = await self._generate_tts(stage2_text)
            except Exception as e:
                print(f"[TwoStage] TTS stage2 error: {e}")
                stage2_url = None

            # Stage 2 テキスト + 音声を送信
            await self._broadcast_text(stage2_text)
            if stage2_url:
                await self._broadcast_callback({"type": "ai_audio", "url": stage2_url})

            # 履歴更新
            self._history.extend([
                {"role": "user", "parts": [audio_part]},
                {"role": "model", "parts": [{"text": f"{stage1_text} {stage2_text}"}]},
            ])
            self._history = self._history[-12:]
            await self._broadcast_callback({"type": "ai_turn_end"})
```

**Step 2: 既存テストが通ることを確認**

```bash
python -m pytest tests/test_two_stage_session.py -v
```

Expected: PASS（`receive_audio` のテストがあれば通ること）

**Step 3: コミット**

```bash
git add src/two_stage_session.py
git commit -m "feat: receive_audio with TTS and stage2 timing control"
```

---

### Task 4: `send_intro` を TTS 対応に変更

**Files:**
- Modify: `backend/src/two_stage_session.py:50-71`

`send_intro` を以下で置き換え：

```python
    async def send_intro(self):
        """フロントエンド接続時にGeminiでイントロを生成して送信する。"""
        print(f"[TwoStage] send_intro called, callback={self._broadcast_callback is not None}")
        if not self._broadcast_callback:
            return
        intro_prompt = (
            "手相占いを始めます。相手の手を見て、神秘的なイントロを2文で述べてください。"
        )
        contents = [{"role": "user", "parts": [{"text": intro_prompt}]}]
        try:
            intro_text = await self._generate_text(contents, STAGE1_SYSTEM)
        except Exception as e:
            print(f"[TwoStage] send_intro error: {e}")
            intro_text = ""
        if not intro_text:
            intro_text = "あなたの手のひらには、深い運命の線が刻まれています。今日は特別なものが見えます。"

        try:
            intro_url, _ = await self._generate_tts(intro_text)
        except Exception as e:
            print(f"[TwoStage] TTS intro error: {e}")
            intro_url = None

        await self._broadcast_text(intro_text)
        if intro_url:
            await self._broadcast_callback({"type": "ai_audio", "url": intro_url})
        await self._broadcast_callback({"type": "ai_turn_end"})
        self._history.extend([
            {"role": "user", "parts": [{"text": intro_prompt}]},
            {"role": "model", "parts": [{"text": intro_text}]},
        ])
```

**Step 2: テストが通ることを確認**

```bash
python -m pytest tests/test_two_stage_session.py -v
```

**Step 3: コミット**

```bash
git add src/two_stage_session.py
git commit -m "feat: send_intro with TTS audio"
```

---

### Task 5: フロントエンド audio キュー実装

**Files:**
- Modify: `frontend/src/hooks/useBackendWS.js`
- Modify: `frontend/src/App.jsx`
- Modify: `frontend/src/pages/SessionPage.jsx`

**Step 1: `useBackendWS.js` を変更**

`aiAudioUrl` state を `aiAudioQueue`（配列）に変更する。

現在の `useBackendWS.js` の `useState` と `onmessage` と return を以下に変更：

```js
// 変更前: const [aiAudioUrl, setAiAudioUrl] = useState(null)
// 変更後:
const [aiAudioQueue, setAiAudioQueue] = useState([])
```

`ws.onmessage` 内の `ai_audio` ハンドラを変更：

```js
// 変更前:
} else if (msg.type === 'ai_audio') {
  setAiAudioUrl(httpBase + msg.url)
// 変更後:
} else if (msg.type === 'ai_audio') {
  setAiAudioQueue(prev => [...prev, httpBase + msg.url])
```

`startUserTurn` でキューをクリア：

```js
// 変更前:
const startUserTurn = useCallback(() => {
  setTurn('user')
  setAiTurnEnded(false)
}, [])
// 変更後:
const startUserTurn = useCallback(() => {
  setTurn('user')
  setAiTurnEnded(false)
  setAiAudioQueue([])
}, [])
```

return 文を変更：

```js
// 変更前: ... aiAudioUrl, ...
// 変更後: ... aiAudioQueue, ...
return { agitationLevel, agitationTrend, aiText, aiAudioQueue, connected, turn, aiTurnEnded, setTurnToAi, startUserTurn }
```

**Step 2: `App.jsx` を変更**

`App.jsx:13` の destructuring と SessionPage の prop を更新：

```jsx
// 変更前:
const { agitationLevel, aiText, aiAudioUrl, connected, turn, aiTurnEnded, setTurnToAi, startUserTurn } = useBackendWS()
// 変更後:
const { agitationLevel, aiText, aiAudioQueue, connected, turn, aiTurnEnded, setTurnToAi, startUserTurn } = useBackendWS()
```

```jsx
// SessionPage の prop を変更:
// 変更前: aiAudioUrl={aiAudioUrl}
// 変更後: aiAudioQueue={aiAudioQueue}
```

**Step 3: `SessionPage.jsx` を変更**

prop 名を変更し、キュー再生ロジックを実装する。

```jsx
// 変更前の関数シグネチャ:
export function SessionPage({ agitationLevel, aiText, aiAudioUrl, httpBase, turn, aiTurnEnded, startUserTurn, setTurnToAi, onEnd }) {
// 変更後:
export function SessionPage({ agitationLevel, aiText, aiAudioQueue, httpBase, turn, aiTurnEnded, startUserTurn, setTurnToAi, onEnd }) {
```

`audioRef` の下に `audioPlayedRef` を追加：

```jsx
const audioRef = useRef(null)
const audioPlayedRef = useRef(0)  // 追加
```

既存の audio `useEffect`（現在 `SessionPage.jsx:24-35`）を以下で**丸ごと置き換える**：

```jsx
// audio キュー再生: 新しい URL が来るか、再生終了時に次を確認
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
}, [aiAudioQueue, isAudioPlaying])

// ユーザーターン開始時にインデックスをリセット
useEffect(() => {
  if (turn === 'user') {
    audioPlayedRef.current = 0
  }
}, [turn])
```

**Step 4: ブラウザで動作確認**

`fig up` してフロントにアクセス。セッションページで：
1. AI のイントロが音声で流れること
2. 話しかけた後 stage1 の音声が流れ、続いて stage2 の音声が流れること
3. 両方の音声が終わったらマイクアイコンが出てユーザーターンになること

**Step 5: コミット**

```bash
git add frontend/src/hooks/useBackendWS.js frontend/src/App.jsx frontend/src/pages/SessionPage.jsx
git commit -m "feat: audio queue playback for stage1/stage2 TTS"
```

---

### Task 6: docker-compose の tts ディレクトリをマウント確認

**Files:**
- Confirm: `docker-compose.yml`

`assets/audio` は既に `./backend/assets:/app/assets` でマウント済み。`assets/audio/tts/` はバックエンドが起動時に `TTS_DIR.mkdir(parents=True, exist_ok=True)` で自動作成されるため **追加対応不要**。

ホスト側に `backend/assets/audio/tts/` が作られていることを確認するだけ：

```bash
ls backend/assets/audio/tts/ 2>/dev/null || echo "not yet (will be created on first TTS call)"
```

**Step 2: 最終コミット**

```bash
git add .
git commit -m "feat: complete Gemini TTS integration with stage timing"
```
