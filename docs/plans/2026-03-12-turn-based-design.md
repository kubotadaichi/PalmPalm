# ターン制会話システム 設計ドキュメント (2026-03-12)

## 概要

人間とAIが交互に発話するターン制システムを実装する。
AIの発話完了シグナル（`ai_turn_end`）をトリガーにターンを遷移させる、フロントエンド主導のステートマシン方式を採用する。

---

## ターンフロー

```
セッション開始
    ↓
[AIターン] イントロ・手相読み上げ
    ↓ ai_turn_end 受信
[ユーザーターン] 自動録音開始 + "話してください" 表示 + カウントダウン
    ↓ タイマー終了 → 録音自動停止 → /api/audio 送信
[AIターン] ユーザー音声 + agitation_snapshot を使った応答
    ↓ ai_turn_end 受信
[ユーザーターン] ...以降繰り返し
```

---

## アーキテクチャ

### ターン状態（フロントエンド管理）

```
type TurnState = 'ai' | 'user'
```

- `'ai'` : AIが発話中。録音は行わない。
- `'user'` : ユーザーターン。自動録音中。カウントダウン表示。

### ターン遷移トリガー

| 遷移 | トリガー |
|---|---|
| `ai` → `user` | バックエンドから `ai_turn_end` WSメッセージ受信 |
| `user` → `ai` | ユーザーターンのタイマー終了（録音自動停止 → `/api/audio` 送信後） |

### スパイク割り込みについて

スパイク割り込みは廃止する。動揺データ（`agitation_level`）はバックグラウンドで収集され続け、AIがユーザー音声に応答する際に `engine.snapshot()` で取得してコンテキストとして利用する。

---

## バックエンド設計

### WSメッセージ追加

```json
{ "type": "ai_turn_end" }
```

AIの1発話が完了するたびに送信する。フロントはこれを受け取ってユーザーターンへ遷移する。

### `mock_gemini_session.py`

- `_script_loop`（継続ループ）を廃止する
- `start_session` でイントロ（台本1エントリ）を送信後、`ai_turn_end` を送信する
- `receive_audio()` でユーザー音声に応答後、`ai_turn_end` を送信する
- `send_push()` および `_vibration_loop` は残す（動揺データ収集のため）。ただし `send_push` は外部から呼ばれなくなる

### `two_stage_session.py`

- `receive_audio()` でユーザー音声 + 現在の `engine.snapshot()` を Gemini に渡して応答生成する
- 応答送信後、`ai_turn_end` を送信する

### `main.py`

- `is_spike()` チェックと `send_push()` の呼び出しを削除する
- その他の変更なし

---

## フロントエンド設計

### `useBackendWS.js`

- `turn: 'ai' | 'user'` 状態を追加する
- `ai_turn_end` 受信時：`turn` を `'user'` に変更し、`aiText` をリセットする
- `turn` を `'user'` から `'ai'` に変更するセッター（`setTurnToAi`）をエクスポートする

### `useVAD.js`

- `turn` を受け取り、`turn === 'user'` になった瞬間（`useEffect`）に `startRecording()` を自動呼び出しする
- タイマー終了後、`recorder.stop()` → `sendRecordedAudio()` → `onRecordingComplete` コールバックを呼び出す
- `onRecordingComplete` は `SessionPage` から渡し、`setTurnToAi()` をトリガーする

### `SessionPage.jsx`

- 録音ボタンを削除する
- `turn === 'ai'` 時：AI発話テキスト + `KirbyMock`（isTalking）を表示する
- `turn === 'user'` 時：「話してください 🎤」表示 + カウントダウン（残り秒数）を表示する
- `aiText` は各AIターン開始時にリセットされるため、前ターンのテキストは残らない

---

## データフロー（詳細）

```
[AIターン]
backend: イントロ送信
    → ai_audio (url)
    → ai_text (chunks)
    → ai_turn_end
frontend: aiText 更新 / 音声再生
    → ai_turn_end 受信 → turn = 'user', aiText リセット

[ユーザーターン]
frontend: useVAD が自動録音開始
    → カウントダウン表示 (10秒)
    → タイマー終了 → recorder.stop()
    → POST /api/audio
    → onRecordingComplete() → turn = 'ai'

[AIターン（2回目以降）]
backend: receive_audio() + engine.snapshot() → Gemini応答
    → ai_text (chunks)
    → ai_turn_end
frontend: aiText 更新
    → ai_turn_end 受信 → turn = 'user', aiText リセット
```

---

## 変更ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `backend/src/mock_gemini_session.py` | 変更 | `_script_loop` 廃止、イントロ一回送信 + `ai_turn_end`、`receive_audio` 後 `ai_turn_end` |
| `backend/src/two_stage_session.py` | 変更 | `receive_audio` 後 `ai_turn_end` 送信、`engine.snapshot()` を応答コンテキストに追加 |
| `backend/src/main.py` | 変更 | `is_spike()` / `send_push()` 呼び出し削除 |
| `frontend/src/hooks/useBackendWS.js` | 変更 | `turn` 状態追加、`ai_turn_end` ハンドリング、`aiText` リセット |
| `frontend/src/hooks/useVAD.js` | 変更 | `turn` 受け取り、`user` ターン開始時に自動録音、`onRecordingComplete` コールバック |
| `frontend/src/pages/SessionPage.jsx` | 変更 | 録音ボタン削除、ターン別UI表示 |
