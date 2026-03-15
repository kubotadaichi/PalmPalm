# PalmPalm Live API WebSocket Design

## Goal

Gemini Live API セッションを常時維持しつつ、ブラウザのマイクPCMをリアルタイムにストリーミングして、無音で AI ターン開始・割り込み発話・tool use による動揺度取得を自然に行える構成へ移行する。

## Scope

- ブラウザとバックエンド間を `POST /api/audio + SSE` から `WebSocket` へ移行する
- バックエンドと Gemini Live API の接続はセッション単位で持続させる
- `get_agitation` tool は当面「直近 N 秒のローリング集計」を返す
- 将来、「AI が話し始めてから tool call 時点まで」の統計へ差し替えやすい形を保つ

## Non-Goals

- 動揺度の意味づけやプロンプト最適化
- UI の残り秒数表示の整理
- テキスト字幕の復活
- センサー側 API の大きな仕様変更

## Approach

### Recommended Architecture

1. ブラウザは `AudioWorklet` で 16kHz mono int16 PCM を小さいチャンクで継続送信する
2. バックエンドは `WebSocket /ws/session` でクライアント接続を受け、1 接続につき 1 つの `LiveSessionManager` を持つ
3. `LiveSessionManager` は Gemini Live API へ音声チャンクを順次送信し、返ってきた音声チャンクを即座にフロントへ返す
4. Gemini の自動 VAD を基本とし、将来の安定化のため `input_audio_end` メッセージを残す
5. `get_agitation` はバックエンドで処理し、AI が任意のタイミングで呼び出せるようにする

### Alternatives Considered

- `POST /api/audio + SSE` を細切れ送信へ拡張
  - 既存コードは一部使えるが、割り込みとターン制御が不自然で捨て実装になりやすい
- ブラウザから Gemini Live API へ直接接続
  - API キー管理と tool use 実装が煩雑になり、このプロジェクトには不向き

## Protocol

### Client → Server

- Binary frame
  - PCM 16kHz mono int16 の音声チャンク
- Text frame: `{"type":"input_audio_end"}`
  - 明示 flush 用
- Text frame: `{"type":"session_end"}`
  - セッション終了

### Server → Client

- Text frame: `{"type":"session_ready"}`
  - Live API セッション確立完了
- Text frame: `{"type":"audio_chunk","data":"<base64 PCM 24kHz>"}`
  - Gemini からの音声
- Text frame: `{"type":"turn_complete"}`
  - AI 発話終了
- Text frame: `{"type":"error","message":"..."}`
  - 切断や API 異常

## Backend Design

### `backend/src/main.py`

- `POST /api/session/start`
- `POST /api/audio`
- `DELETE /api/session`

上記のセッション API は不要になる。代わりに `WebSocket /ws/session` を追加する。

責務:
- 接続時に `LiveSessionManager.connect()`
- クライアントからの binary frame を `send_audio_chunk()` に渡す
- Gemini 側イベントをクライアントへそのまま転送する
- 切断時に `disconnect()` を保証する

### `backend/src/live_session.py`

責務:
- 常駐 Live API セッションの確立と切断
- 音声チャンクの逐次送信
- `input_audio_end` 時の flush
- Gemini 受信イベントから音声データを抽出
- `get_agitation` tool call への応答

変更点:
- まとめ送信前提の `send_audio()` を `send_audio_chunk()` と `flush_input_audio()` に分ける
- `receive()` は async generator として維持し、WebSocket 層から中継しやすくする
- 音声抽出は `response.data` と `response.server_content.model_turn.parts[].inline_data` の両方を扱う

### `backend/src/agitation_engine.py`

当面は `snapshot_window()` を流用するか、より単純に `snapshot()` を使う。
初期リリースでは「実装容易性」を優先し、tool call 時点から見た直近 N 秒の集計で十分とする。

## Frontend Design

### `frontend/src/hooks/useSession.js`

責務:
- `WebSocket` 接続をセッション中 1 本維持
- `AudioWorklet` の PCM バッファを binary frame で逐次送信
- サーバーから来た `audio_chunk` を `Web Audio API` で再生
- `session_ready` を受けるまで送信しない
- `turn_complete` でユーザーターンへ戻す

変更点:
- `fetch + SSE` を廃止
- `sessionId` 管理は不要
- `turn` は `user` / `ai` のままで十分
- 録音タイマーは UI 表示とは切り離し、必要なら内部制御だけ残す

### `frontend/public/pcm-processor.js`

既存の実装を継続利用する。責務は PCM 変換のみで変更しない。

## Tool Use

- モデルは `get_agitation` を任意のタイミングで呼べる
- バックエンドは HTTP 経由またはローカル計算で値を返す
- 初期版の返却値:
  - `level`
  - `peak`
  - `trend`
- 後続で「AI 発話開始から tool call 時点まで」の統計に変更しても、tool 名とレスポンス形は維持する

## Error Handling

- WebSocket 接続失敗時は `vadError` に反映
- Live API 異常時は `error` イベントをフロントへ送る
- セッション切断時は録音・再生・AudioContext を確実に解放する
- `session_ready` 前に送られた音声は破棄するか送信開始を待つ

## Testing Strategy

### Backend

- `test_live_session.py`
  - `send_audio_chunk()` が chunk をそのまま送る
  - `flush_input_audio()` が `audio_stream_end=True` を送る
  - `receive()` が `model_turn.parts.inline_data` から音声を返す
  - tool call 応答が継続する
- `test_main.py`
  - `WebSocket /ws/session` 接続成功
  - binary frame 受信で `send_audio_chunk()` が呼ばれる
  - `session_ready` / `audio_chunk` / `turn_complete` が転送される
  - 切断時に `disconnect()` が呼ばれる

### Frontend

- `npm run build`
- Chrome 手動確認
  - マイク許可
  - 接続成功
  - 無音後に AI 音声が始まる
  - AI 発話中の割り込み

## Risks

- ブラウザと Gemini の VAD の境界が競合する可能性
- binary frame と text frame の混在処理で実装ミスが起きやすい
- 接続断時の AudioContext 解放漏れ

## Rollout Notes

- 先に WebSocket 経路を通し、動揺度は簡易ローリング集計で固定する
- その後、動揺度の統計区間を「AI 発話開始から」に変更する設計を別途行う
