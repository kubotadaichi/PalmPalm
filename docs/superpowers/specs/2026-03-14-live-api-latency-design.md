# PalmPalm レイテンシ改善設計：Gemini Live API + Tool Use

**日付:** 2026-03-14
**ステータス:** 承認済み

---

## 背景と課題

現状のレスポンスフロー（直列 API 呼び出し）：

```
音声受信 → text gen (~5s) → TTS gen (~5s) → stage1 audio
                                              ↑ ~15秒

stage1 再生終了 → text gen (~5s) → TTS gen (~5s) → stage2 audio
                                                     ↑ さらに ~10秒
```

原因：
- `generate_content`（テキスト）と `generate_content`（TTS）が直列
- `run_in_executor` による同期クライアントのスレッド実行
- 2段階構造のため API 呼び出しが合計4回

---

## 目標

- Stage1 first audio: ~15s → ~2s
- Stage2 gap（stage1終了〜stage2再生）: ~10s → 0s（1ターン統合）
- 会話履歴の維持
- agitation データをコールドリーディング的なタイミングで活用

---

## アーキテクチャ

### 全体像

```
[Pico] → serial → [serial_reader] → POST /pulse
                                          ↓
                                  [AgitationEngine]
                                  deque[timestamp] に蓄積
                                  /agitation/window?from=X&to=Y

[Frontend]                        [Backend: FastAPI]
  Web Audio API         ←──────   Gemini Live API セッション
  PCM チャンク再生                  ↑
  turn タイムスタンプ記録  ──────→  session.send_tool_response()
```

### セッションライフサイクル

```
占いセッション開始（1回）
  └─ client.aio.live.connect(model='gemini-2.5-flash-live', config)
       └─ context window compression 有効（15分制限を回避）
       └─ get_agitation tool を登録
       └─ セッション全体を通じて継続（WebSocket 持続）

[ターンごと]
  1. ユーザー音声 PCM を send_realtime_input() でストリーム送信
  2. AI が応答生成開始 → first audio ~2s で到着
  3. AI が適切なタイミングで get_agitation() を tool call
  4. Backend が AgitationEngine に window query → 結果を send_tool_response()
  5. AI が agitation 情報を織り交ぜて応答を完成
  6. turn_end イベントでユーザーターンへ

セッション切断時：
  └─ resumption token で再接続
  └─ 直近6ターンのテキスト履歴を system_instruction に埋め込んで補完
```

---

## コンポーネント設計

### 1. AgitationEngine の拡張（`agitation_engine.py`）

追加メソッド：

```python
def snapshot_window(self, from_ts: float, to_ts: float) -> dict:
    """指定期間内のパルスから level/peak/trend を算出。"""
    pulses_in_window = [t for t in self._pulses if from_ts <= t <= to_ts]
    level = min(100, int(len(pulses_in_window) / self.max_pulses * 100))
    peak = level  # window内のピーク（将来的に細分化可）
    return {"level": level, "peak": peak, "trend": self._calc_trend(level)}
```

### 2. Agitation Server の拡張（`agitation_server.py`）

追加エンドポイント：

```
GET /agitation/window?from=<unix_sec>&to=<unix_sec>
→ {"level": int, "peak": int, "trend": str}
```

### 3. Live API セッション管理（新規 `live_session.py`）

```python
class LiveSessionManager:
    """Gemini Live API を使った占いセッション管理。"""

    # セッション設定
    MODEL = "gemini-2.5-flash-live"
    TOOLS = [get_agitation_tool_declaration]

    # 状態管理
    _session: BidiGenerateContentSession
    _ai_speak_start: float | None  # AI発話開始タイムスタンプ
    _text_history: list[dict]      # 切断復帰用テキスト履歴（直近6ターン）

    async def start(self): ...     # セッション確立
    async def send_audio(self, pcm_bytes: bytes): ...  # ユーザー音声送信
    async def receive(self) -> AsyncGenerator[dict, None]: ...  # 応答受信
    async def _handle_tool_call(self, call) -> None:
        # get_agitation() が呼ばれたとき
        # window = [ai_speak_start, now] で agitation を取得して返す
        ...
```

#### get_agitation tool 定義

```python
get_agitation_tool = {
    "name": "get_agitation",
    "description": (
        "ユーザーの手の振動センサーから身体的動揺度を読み取る。"
        "占いの重要なタイミング（感情の核心に触れる直前）で呼び出すこと。"
        "呼び出すタイミング自体が演出の一部であり、"
        "AI が最もドラマチックな瞬間を選ぶこと。"
    ),
    "parameters": {"type": "object", "properties": {}},
    "behavior": "NON_BLOCKING",
    "scheduling": "WHEN_IDLE",
}
```

#### tool call 時のウィンドウ

| タイミング | 取得ウィンドウ | 意味 |
|---|---|---|
| AI が tool call した時点 | `[ai_speak_start, now]` | AIが話し始めてからの反応 |

### 4. バックエンドエンドポイント（`main.py`）

```
POST /api/session/start  → Live セッション確立、session_id を返す
POST /api/audio          → PCM bytes 送信 → SSE で音声チャンク + イベントを返す
DELETE /api/session      → セッション終了
```

音声チャンクは SSE で `audio_chunk` イベントとして送信（base64 PCM）。

### 5. フロントエンド（`useSession.js`）

変更点：
- `new Audio(url)` による WAV 再生 → **Web Audio API** による PCM ストリーム再生
- AI 発話開始タイムスタンプを `session_id` と共にバックエンドに通知
- 音声チャンクを受け取り次第キューに追加して再生

```javascript
// PCM チャンク受信 → AudioBuffer に変換 → AudioContext でスケジュール再生
const audioCtx = new AudioContext({ sampleRate: 24000 })
```

---

## system_instruction（占い師プロンプト）

Live API のセッション開始時に1回設定。

```
あなたはAI手相占い師「ぱむぱむ」です。

【基本姿勢】
手の感情線・運命線・頭脳線・生命線を具体的に言及しながら語る。
断言は避け「〜ではないですか」「〜が見えます」という仮説として語る。
神秘的かつ低いトーンで、2〜3文で語る。

【get_agitation ツールの使い方（最重要）】
- 毎ターン必ず1回呼び出すこと
- 呼び出すタイミングは「感情の核心に近づいた」と感じた瞬間
- 呼び出す前に一般的な読みを展開し、結果を見てから核心を突く
- すぐに「センサーが〜」とは言わない。「体が正直に答えています」程度に留める

【出力】
2〜3文、必ず問いかけで締める。
```

---

## 実装後タスク：プロンプトチューニング

- agitation レベル別の応答トーン調整
- tool call タイミングの誘導強化
- コールドリーディング精度向上

---

## 変更ファイルサマリー

| ファイル | 変更種別 | 規模 |
|---|---|---|
| `backend/src/agitation_engine.py` | 追加 | +20行 |
| `backend/src/agitation_server.py` | 追加 | +10行 |
| `backend/src/live_session.py` | 新規 | ~250行 |
| `backend/src/two_stage_session.py` | 廃止（保持） | - |
| `backend/src/main.py` | 変更 | ~60行変更 |
| `frontend/src/hooks/useSession.js` | 変更 | ~100行変更 |

合計：約 450〜500 行

---

## 技術的リスクと対策

| リスク | 対策 |
|---|---|
| Live API セッション15分制限 | context window compression を有効化 |
| セッション切断 | resumption token + テキスト履歴で復帰 |
| tool call タイミングが不自然 | `WHEN_IDLE` + system_instruction で誘導 |
| Web Audio API ブラウザ互換性 | Chrome/Safari の AudioContext で動作確認済み |
| PCM フォーマット変換 | 入力: 16kHz mono / 出力: 24kHz mono で統一 |
