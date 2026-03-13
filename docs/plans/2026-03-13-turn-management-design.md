# ターン管理リファクタリング設計 (2026-03-13)

## 目的

現状の `useSession` + `useVAD` 分離構造による stale closure バグと
ターン遷移責任の分散を解消する。

## 要件

- セッション開始 → いきなりユーザーターン（イントロなし）
- ユーザーが 10 秒録音 → 自動送信
- AI が SSE で返答 + 音声再生 → 完了したらまたユーザーターン
- 120 秒タイマーで終了

## ターンフロー

```
[開始]
  ↓
turn='user' → 録音開始(10s固定) → POST /api/audio
                                        ↓
                                turn='ai' + SSE受信
                                        ↓
                                音声キュー再生(順番に)
                                        ↓
                                全音声再生完了 or 音声なし
                                        ↓
                                turn='user' (繰り返し)
```

## アーキテクチャ

`useVAD.js` を廃止し、録音・音声再生・SSE 受信・ターン管理を
`useSession.js` に統合する。

### state / ref 構成

| 名前 | 種類 | 役割 |
|---|---|---|
| `turn` | state | `'user'` / `'ai'` |
| `aiText` | state | AI テキスト表示用 |
| `vadError` | state | マイクエラー表示用 |
| `timeLeft` | state | 録音残り秒数表示用 |
| `recorderRef` | ref | MediaRecorder インスタンス |
| `streamRef` | ref | MediaStream インスタンス |
| `audioQueueRef` | ref | 再生待ち URL キュー |
| `isPlayingRef` | ref | 音声再生中フラグ |
| `sseCompleteRef` | ref | turn_end 受信済みフラグ |
| `countdownRef` | ref | カウントダウン interval ID |
| `stopTimerRef` | ref | 録音停止 timeout ID |

### コンポーネント構成

```
App.jsx
  └─ SessionPage.jsx
       └─ useSession() ← 全責務
```

`SessionPage` は `{ turn, aiText, vadError, timeLeft }` を受け取って表示するだけ。

## 変更ファイル一覧

### フロントエンド

| ファイル | 変更内容 |
|---|---|
| `src/hooks/useSession.js` | 全面書き直し（録音・再生・SSE 統合） |
| `src/hooks/useVAD.js` | **削除** |
| `src/pages/SessionPage.jsx` | useVAD 依存を除去、props を最小化 |
| `src/App.jsx` | useSession の props を整理 |

### バックエンド

| ファイル | 変更内容 |
|---|---|
| `src/main.py` | `GET /api/session/start` 削除、INTRO_AUDIO_URL 削除 |
| `src/two_stage_session.py` | `intro()` メソッド削除 |
