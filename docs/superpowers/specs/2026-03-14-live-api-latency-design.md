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

- Stage1 first audio: ~15s → ~2s（ネットワーク状況により前後する）
- Stage2 gap（stage1終了〜stage2再生）: ~10s → 0s（1ターン統合）
- 会話履歴の維持（Live API セッション内で自動保持）
- agitation データをコールドリーディング的なタイミングで活用

---

## アーキテクチャ

### 全体像

```
[Pico] → serial → [serial_reader] → POST /pulse
                                          ↓
                                  [AgitationEngine]（Raspberry Pi）
                                  deque[timestamp] に蓄積
                                  GET /agitation/window?from=X&to=Y ←──┐
                                                                         │HTTP
[Frontend]                        [Backend: FastAPI]                     │
  AudioWorklet で PCM キャプチャ   Gemini Live API セッション             │
  fetch POST /api/audio ────────→  send_realtime_input(PCM 16kHz)       │
  SSE で audio_chunk 受信 ←──────  receive() ループ                      │
  Web Audio API で PCM 再生         └─ tool call 受信時 ──────────────────┘
                                       send_tool_response(agitation)
```

### セッションライフサイクル

```
占いセッション開始（1回）
  └─ POST /api/session/start → {"session_id": "<uuid>"}
  └─ client.aio.live.connect(model='gemini-2.5-flash-live', config)
       └─ context window compression 有効（15分制限を回避）
       └─ get_agitation tool を登録
       └─ セッション全体を通じて WebSocket 持続（履歴は API 側が自動保持）

[ターンごと]
  1. Frontend: AudioWorklet で PCM(16kHz mono int16) をキャプチャ
  2. Frontend: POST /api/audio?session_id=<uuid> に PCM blob を送信
  3. Backend: send_realtime_input() で Gemini へ転送
  4. Gemini: 応答生成開始 → first audio チャンク ~2s で到着
             ★ 最初の audio チャンク到着時 _ai_speak_start = time.time() をセット
  5. Gemini: 任意のタイミングで get_agitation() を tool call
  6. Backend: GET /agitation/window?from=_ai_speak_start&to=now をラズパイへ HTTP 呼び出し
             → send_tool_response(level, peak, trend)
  7. Gemini: agitation 情報を織り交ぜて応答を完成
  8. Backend: SSE で audio_chunk（base64 PCM 24kHz）を Frontend へ逐次送信
  9. Frontend: Web Audio API で PCM チャンクをスケジュール再生
  10. turn_complete イベントでユーザーターンへ

セッション切断時：
  └─ resumption token で再接続（2時間以内有効）
  └─ 直近6ターンのテキスト履歴を system_instruction に埋め込んで補完
```

---

## コンポーネント設計

### 1. AgitationEngine の拡張（`agitation_engine.py`）

既存の `trend` プロパティのロジックを `_calc_trend(level: int) -> str` として切り出し、
`snapshot_window` と共用する。

```python
def _calc_trend(self, level: int) -> str:
    diff = level - self._previous_level
    if diff > 10:
        return "rising"
    elif diff < -10:
        return "falling"
    return "stable"

def snapshot_window(self, from_ts: float, to_ts: float) -> dict:
    """指定期間内のパルスから level/peak/trend を算出。_previous_level は更新しない。"""
    pulses_in_window = [t for t in self._pulses if from_ts <= t <= to_ts]
    level = min(100, int(len(pulses_in_window) / self.max_pulses * 100))
    return {"level": level, "peak": level, "trend": self._calc_trend(level)}
```

既存の `trend` プロパティは `self._calc_trend(self.level)` を使うよう変更。

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

    MODEL = "gemini-2.5-flash-live"

    def __init__(self, agitation_api_url: str):
        self.agitation_api_url = agitation_api_url
        self._session = None
        self._ai_speak_start: float | None = None  # 最初の audio chunk 到着時にセット
        self._text_history: list[dict] = []         # 切断復帰用（直近6ターン分のテキスト）

    async def connect(self) -> None:
        """Live API セッションを確立する。"""
        ...

    async def send_audio(self, pcm_bytes: bytes) -> None:
        """PCM 16kHz mono int16 を send_realtime_input() で送信。"""
        ...

    async def receive(self) -> AsyncGenerator[dict, None]:
        """
        受信イベントを yield する。
        - {"type": "audio_chunk", "data": "<base64 PCM 24kHz>"}
        - {"type": "turn_complete"}
        最初の audio_chunk 受信時に _ai_speak_start をセット。
        tool_call を受け取ったら _handle_tool_call() を呼んで処理。
        """
        ...

    async def _handle_tool_call(self, call) -> None:
        """
        get_agitation() tool call 処理。
        window = [_ai_speak_start, time.time()] でラズパイへ HTTP クエリ。
        _ai_speak_start が None の場合は現在時刻から 3s 前をフォールバックに使用。
        """
        from_ts = self._ai_speak_start or (time.time() - 3.0)
        to_ts = time.time()
        snap = await self._fetch_agitation_window(from_ts, to_ts)
        await self._session.send_tool_response(
            function_responses=[FunctionResponse(
                id=call.id, name="get_agitation", response=snap
            )]
        )

    async def _fetch_agitation_window(self, from_ts: float, to_ts: float) -> dict:
        """ラズパイの /agitation/window を HTTP 呼び出し。"""
        ...
```

#### get_agitation tool 定義

```python
get_agitation_tool = FunctionDeclaration(
    name="get_agitation",
    description=(
        "ユーザーの手の振動センサーから身体的動揺度を読み取る。"
        "占いの重要なタイミング（感情の核心に触れる直前）で呼び出すこと。"
        "呼び出すタイミング自体が演出の一部であり、"
        "AI が最もドラマチックな瞬間を選ぶこと。"
        "毎ターン1回は必ず呼び出すこと。"
    ),
    parameters={"type": "object", "properties": {}},
)
```

**scheduling について：** `WHEN_IDLE` は応答生成の自然な間で呼ばれる。
system_instruction で「必ず1回呼ぶ」と指示することで、
生成開始直後ではなく中盤以降に呼ばれるよう誘導する。
`WHEN_IDLE` を使わず blocking にする場合は生成が一時停止するが、
コールドリーディング的な「間」として逆に演出になりうる。実装時に両方試すこと。

#### tool call 時のウィンドウ

| タイミング | 取得ウィンドウ | 意味 |
|---|---|---|
| AI が tool call した時点 | `[_ai_speak_start, now]` | AIが話し始めてからのユーザー反応 |

### 4. バックエンドエンドポイント（`main.py`）

```
POST /api/session/start
  → {"session_id": "<uuid>"}
  → LiveSessionManager を生成・接続し、uuid をキーに dict 管理
  → session が存在しない場合のみ新規作成（同時セッションは1つのみ）

POST /api/audio?session_id=<uuid>
  → body: PCM blob (audio/octet-stream, 16kHz mono int16)
  → 該当セッションに send_audio() → receive() を SSE でストリーム
  → session_id が不正な場合は 404

DELETE /api/session?session_id=<uuid>
  → セッション終了・破棄
```

**削除されるもの：**
- `app.mount("/audio", StaticFiles(...))` を削除（WAV ファイル配信が不要になる）
- `backend/assets/audio/tts/` ディレクトリへの書き込みが不要になる
- `TwoStageSessionManager` のインスタンス化を削除

音声チャンクは SSE で逐次送信：
```
data: {"type": "audio_chunk", "data": "<base64 PCM 24kHz mono>"}
data: {"type": "turn_complete"}
```

### 5. フロントエンド（`useSession.js`）

**ユーザー音声キャプチャ（現状変更）：**
- 現状: `MediaRecorder` → webm blob
- 変更後: **AudioWorklet**（または ScriptProcessorNode）で raw PCM 16kHz mono int16 をキャプチャ
  - `AudioContext({ sampleRate: 16000 })` で作成
  - AudioWorklet が 16bit int に変換して blob として送信

**AI 音声再生（現状変更）：**
- 現状: `new Audio(url)` で WAV ファイルを再生
- 変更後: **Web Audio API** で PCM チャンクをスケジュール再生
  ```javascript
  const audioCtx = new AudioContext({ sampleRate: 24000 })
  // audio_chunk イベントごとに AudioBuffer を作成してキューに追加
  ```

**セッション管理：**
- 起動時に `POST /api/session/start` → `session_id` を保持
- 以降の `POST /api/audio?session_id=<uuid>` に付与

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
- 呼び出すタイミングは「感情の核心に近づいた」と感じた瞬間（ターンの中盤〜後半）
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
| `backend/src/agitation_engine.py` | 変更（`_calc_trend` 切り出し + `snapshot_window` 追加） | +25行 |
| `backend/src/agitation_server.py` | 追加 | +10行 |
| `backend/src/live_session.py` | 新規 | ~250行 |
| `backend/src/two_stage_session.py` | 廃止（ファイルは保持） | - |
| `backend/src/main.py` | 変更（StaticFiles削除・新エンドポイント追加） | ~60行変更 |
| `frontend/src/hooks/useSession.js` | 変更（AudioWorklet + Web Audio API） | ~120行変更 |

合計：約 465〜520 行

---

## 技術的リスクと対策

| リスク | 対策 |
|---|---|
| Live API セッション15分制限 | context window compression を有効化（`BidiGenerateContentSetup` で設定） |
| セッション切断 | resumption token（2時間有効）+ テキスト履歴で復帰 |
| tool call タイミング制御（`WHEN_IDLE` vs blocking） | 両方試して演出として自然な方を採用 |
| Web Audio API ブラウザ互換性 | Chrome/Safari の AudioContext で動作確認 |
| PCM フォーマット | 入力: 16kHz mono int16 / 出力: 24kHz mono int16 で統一 |
| agitation server（ラズパイ）への HTTP 遅延 | timeout=2s で打ち切り、失敗時は `{"level":0,"trend":"stable"}` を返す |
| context window compression の利用可否 | 実装時に `gemini-2.5-flash-live` での対応を確認 |
