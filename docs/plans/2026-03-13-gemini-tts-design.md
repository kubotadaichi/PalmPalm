# Gemini TTS 統合設計

## 概要

`TwoStageSessionManager` に Gemini TTS（`gemini-2.5-flash-preview-tts`）を統合し、stage1・stage2 それぞれの応答テキストを音声に変換してフロントエンドで再生する。

## アーキテクチャ

### バックエンド処理フロー

```
① stage1 テキスト生成（Gemini）
② stage1 TTS 生成 → assets/audio/tts/<uuid>.wav（duration = D 秒）
③ ai_text チャンク送信（テキスト表示用）
④ ai_audio(stage1 URL) 送信 → フロントが再生開始
⑤ バックエンドが (D - STAGE2_LEAD_SECONDS) 秒待機
⑥ 最新の動揺度（agitation_engine.snapshot()）を取得
⑦ stage2 テキスト生成（動揺度込み）
⑧ stage2 TTS 生成 → assets/audio/tts/<uuid>.wav
⑨ ai_text チャンク送信（stage2）
⑩ ai_audio(stage2 URL) 送信 → stage1 終了直前に到着
⑪ ai_turn_end 送信
```

### タイミング設計

- `STAGE2_LEAD_SECONDS = 3`（デフォルト）：stage1 終了の何秒前に stage2 生成を開始するか
- stage2 生成時間（テキスト + TTS）が 3 秒以内に収まるという想定
- 調整が必要な場合は環境変数 `STAGE2_LEAD_SECONDS` で上書き可能

### TTS 設定

- モデル：`gemini-2.5-flash-preview-tts`
- 声：`Kore`（日本語対応）
- 出力形式：PCM（24kHz, 16bit, mono）→ WAV ファイルに変換して保存

### 音声ファイル管理

- 保存先：`assets/audio/tts/<uuid>.wav`
- 配信：既存の `/audio/` StaticFiles でそのまま配信（`/audio/tts/<uuid>.wav`）
- クリーンアップ：ファイル数が 20 を超えたら古いものを削除

## フロントエンド変更

### 現状の問題

`SessionPage.jsx` は `aiAudioUrl` が更新されるたびに即再生しており、stage2 が来ると stage1 を上書きしてしまう。

### 変更内容

`useBackendWS.js` の `ai_audio` ハンドラで URL を配列（キュー）に積む。`SessionPage.jsx` でキューを順番に再生し、1つ終わったら次を再生する。

## 変更ファイル

| ファイル | 変更内容 |
|---------|---------|
| `backend/src/two_stage_session.py` | TTS生成・タイミング制御ロジック追加 |
| `frontend/src/hooks/useBackendWS.js` | `aiAudioUrl` → `aiAudioQueue`（配列）に変更 |
| `frontend/src/pages/SessionPage.jsx` | audio キュー順番再生に変更 |

## 環境変数

| 変数 | デフォルト | 説明 |
|------|-----------|------|
| `STAGE2_LEAD_SECONDS` | `3` | stage1 終了の何秒前に stage2 生成を開始するか |
