# マイク入力 → Gemini 連携 設計ドキュメント (2026-03-12)

## 概要

フロントエンドのマイクから音声入力を受け取り、Gemini 標準APIに渡して応答を得る。
既存の `TwoStageSessionManager` インターフェースを拡張し、モック/本番で同一インターフェースを維持する。

---

## データフロー

```
SessionPage
  └─ useVAD（@ricky0123/vad-web）
       ├─ 発話開始 → isSpeaking = true → マイクインジケーター表示
       └─ 発話終了（onSpeechEnd: Float32Array）
            └─ float32ToWav() で WAV Blob 変換
                 └─ POST /api/audio（application/octet-stream）
                      └─ TwoStageSessionManager.receive_audio(bytes, "audio/wav")
                           └─ Gemini API（音声 inline_data → テキスト応答）
                                └─ broadcast ai_text → frontend
```

---

## バックエンド変更

### `backend/src/main.py`

新エンドポイント追加（CORSは既存ミドルウェアで対応済み）:

```python
from fastapi import Request

@app.post("/api/audio")
async def receive_audio_endpoint(request: Request):
    audio_bytes = await request.body()
    asyncio.create_task(gemini.receive_audio(audio_bytes, "audio/wav"))
    return {"status": "accepted"}
```

### `backend/src/two_stage_session.py`

`receive_audio()` メソッド追加。
ユーザーの発話音声を Gemini に渡し、2段階応答（Stage1: 神秘的応答、Stage2: 動揺データ踏まえた追い込み）を生成して broadcast。

```python
async def receive_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav"):
    import base64
    audio_part = {
        "inline_data": {
            "mime_type": mime_type,
            "data": base64.b64encode(audio_bytes).decode()
        }
    }
    # 既存の send_push と同様に2段階応答 → broadcast ai_text
```

### `backend/src/mock_gemini_session.py`

同インターフェース追加（音声内容は無視して台本から返す）:

```python
async def receive_audio(self, audio_bytes: bytes, mime_type: str = "audio/wav"):
    entry = _READING_SCRIPT[self._script_idx % len(_READING_SCRIPT)]
    self._script_idx += 1
    await self._broadcast_callback({"type": "ai_audio", "url": entry["audio"]})
    for chunk in _chunks(entry["text"], size=8):
        await self._broadcast_callback({"type": "ai_text", "text": chunk})
        await asyncio.sleep(0.05)
```

---

## フロントエンド変更

### 依存追加

```bash
npm install @ricky0123/vad-web
```

### 新規: `frontend/src/hooks/useVAD.js`

```javascript
import { useMicVAD } from '@ricky0123/vad-web'

export function useVAD({ httpBase }) {
  const [isSpeaking, setIsSpeaking] = useState(false)

  useMicVAD({
    onSpeechStart: () => setIsSpeaking(true),
    onSpeechEnd: async (audio) => {
      setIsSpeaking(false)
      const wav = float32ToWav(audio)
      await fetch(`${httpBase}/api/audio`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/octet-stream' },
        body: wav,
      })
    },
  })

  return { isSpeaking }
}
```

`float32ToWav()` は同ファイル内のユーティリティ（16kHz モノラル WAV）。

### `frontend/src/pages/SessionPage.jsx`

`useVAD` を呼び出し、`isSpeaking` 中はマイクアイコン（🎤）を表示。

---

## HTTP URL 導出

`useVAD.js` は `useBackendWS.js` と同じロジックで httpBase を受け取る:

```javascript
const wsUrl = import.meta.env.VITE_BACKEND_WS_URL ?? 'ws://localhost:8000/ws/frontend'
const httpBase = wsUrl.replace(/^ws/, 'http').replace(/\/ws\/.*$/, '')
// → http://localhost:8000
```

`App.jsx` で `httpBase` を計算して `SessionPage` → `useVAD` に渡す。

---

## モック動作

`MOCK_MODE=true` のとき `MockGeminiSessionManager.receive_audio()` が呼ばれ、音声を無視して次の台本セリフを返す。フロント側は本番と同じフローで動作確認できる。

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `backend/src/main.py` | 変更 | `POST /api/audio` エンドポイント追加 |
| `backend/src/two_stage_session.py` | 変更 | `receive_audio()` メソッド追加 |
| `backend/src/mock_gemini_session.py` | 変更 | `receive_audio()` モック実装追加 |
| `frontend/package.json` | 変更 | `@ricky0123/vad-web` 追加 |
| `frontend/src/hooks/useVAD.js` | 新規 | VAD + 音声POST フック |
| `frontend/src/App.jsx` | 変更 | `httpBase` 計算、`SessionPage` に渡す |
| `frontend/src/pages/SessionPage.jsx` | 変更 | `useVAD` 呼び出し、`isSpeaking` 表示 |
