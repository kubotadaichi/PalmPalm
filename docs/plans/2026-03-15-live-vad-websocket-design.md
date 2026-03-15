# PalmPalm Live VAD WebSocket Design

## Goal

Gemini Live API の自動 VAD を主導にして、ブラウザからの常時音声ストリーミング、自然なターン切替、割り込み、tool use による動揺度取得を安定させる。あわせて、2ターン目以降に音声が返らない不具合を調査できる観測点を加える。

## Why Change

現状は以下の二重管理になっている。

- Gemini Live API 側の自動 VAD
- フロントエンド側の 10 秒タイマーと silence 判定

この構成では以下の問題が起きやすい。

- ターン切替の責務が二重化する
- 無音入力時にフロントが先に状態遷移して固まりやすい
- `input_audio_end` の重複送信が起きやすい
- 2ターン目以降に WebSocket や Live API セッションの状態が崩れた時に観測しづらい

## Design Choice

### Recommended

Live VAD 主導に寄せる。

- PCM は WebSocket で常時送信
- クライアントは silence 判定しない
- ターンの終了は Gemini Live API の `turn_complete` を基準にする
- `input_audio_end` は原則送らない
- UI の 10 秒カウントダウンは撤去する

### Rejected

- クライアント側 VAD を調整し続ける
  - Live VAD と競合し続ける
- HTTP/SSE に戻す
  - 目的である常時接続と割り込みに逆行する

## Target Behavior

### Session Lifecycle

- セッション開始時に `WebSocket /ws/session` を 1 本確立する
- バックエンドは 1 接続ごとに `LiveSessionManager` を 1 本維持する
- ページ離脱または終了時に `session_end` を送り、WebSocket を閉じる

### Audio Input

- ブラウザは `AudioWorklet` で 16kHz mono int16 PCM を生成する
- PCM chunk は常時 WebSocket binary frame で送る
- 無音でも turn を強制終了しない
- 長時間無音に対してもクライアント側で `ai` ターンへ遷移しない

### AI Turn

- Gemini Live API が自動 VAD で入力区切りを判断する
- `audio_chunk` を受けた時点で UI は `ai` ターンへ入る
- `turn_complete` を受けたら UI は `user` ターンへ戻る
- 割り込みは常時送信を続けることで Live API に委ねる

### Tool Use

- `get_agitation` は引き続きバックエンド実装で処理する
- 当面はローリング集計を返す
- 後で「AI発話開始から tool call 時点まで」の集計へ差し替える

## Debugging Instrumentation

2ターン目以降の不具合を切り分けるため、最小限のログを入れる。

### Backend `live_session.py`

- `send_audio_chunk()` 呼び出し回数
- `receive()` 内の
  - `audio_chunk` 送出回数
  - `tool_call` 回数
  - `turn_complete` 検知
- `disconnect()` 時刻

### Backend `main.py`

- WebSocket accept / close
- close の理由
- binary frame 受信回数
- 例外発生時の stack trace

### Frontend `useSession.js`

- socket open / close / error
- `audio_chunk` 受信回数
- `turn_complete` 受信回数
- `turn` の遷移

## Frontend Changes

### `frontend/src/hooks/useSession.js`

- `MAX_RECORD_SECONDS` と `timeLeft` を削除
- silence 判定を削除
- `input_audio_end` 送信を通常フローから削除
- `turn_complete` だけで `user` ターンへ戻す
- デバッグログを追加

### `frontend/src/pages/SessionPage.jsx`

- 録音カウントダウン表示を削除
- 必要ならセッション全体制限表示も削除候補
- ただし見た目の整理は二次的で、まずターン制御から切り離す

## Backend Changes

### `backend/src/main.py`

- WebSocket text frame は `session_end` のみ残す
- `input_audio_end` への依存を外す
- 調査ログを追加

### `backend/src/live_session.py`

- `flush_input_audio()` は残してよいが通常フローでは使わない
- `send_audio_chunk()` を主経路にする
- 調査ログを追加

## Verification

### Automated

- `uv run pytest tests/ -v`
- `npm run build`

### Manual

Chrome で以下を確認する。

1. `ws://127.0.0.1:8000/ws/session` が接続維持される
2. 1ターン目の応答が再生される
3. 2ターン目以降も再生される
4. 無音時に UI が固まらず、`user` ターンのまま待つ
5. AI 発話中にユーザーが話し始めると割り込める

## Risks

- 常時送信による不要な無音 chunk が多いと、Live API 側の挙動が読みにくい
- turn 切替を完全に Live VAD 任せにすると、UI 応答性に調整が必要になる場合がある
- ログを増やしすぎると追いづらくなるので最小限に留める
