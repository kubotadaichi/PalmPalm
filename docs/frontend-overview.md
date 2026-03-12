# フロントエンド概要ドキュメント

> 対象: フロントエンド共同開発者向け
> 最終更新: 2026-03-12

---

## 目次

1. [技術スタック](#技術スタック)
2. [ディレクトリ構成](#ディレクトリ構成)
3. [アプリの画面フロー](#アプリの画面フロー)
4. [主要ファイルの役割](#主要ファイルの役割)
5. [状態管理の仕組み](#状態管理の仕組み)
6. [バックエンドとの通信](#バックエンドとの通信)
7. [音声録音・再生の仕組み](#音声録音再生の仕組み)
8. [ターン制の仕組み](#ターン制の仕組み)
9. [環境変数](#環境変数)
10. [開発サーバーの起動](#開発サーバーの起動)

---

## 技術スタック

| カテゴリ | 技術 | バージョン |
|---------|------|-----------|
| UIフレームワーク | React | ^19.2.0 |
| ビルドツール | Vite | ^7.3.1 |
| スタイリング | Tailwind CSS | ^4.2.1 |
| 音声検出 | @ricky0123/vad-web | ^0.0.30 |
| 通信 | WebSocket / Fetch API | (ブラウザネイティブ) |

---

## ディレクトリ構成

```
frontend/
├── src/
│   ├── main.jsx              # エントリポイント
│   ├── App.jsx               # ルーティング + 全体の状態管理
│   ├── pages/
│   │   ├── TitlePage.jsx     # タイトル画面
│   │   ├── RulesPage.jsx     # ルール説明 + 10秒カウントダウン
│   │   ├── SessionPage.jsx   # メインの会話画面
│   │   └── EndPage.jsx       # セッション終了画面
│   ├── components/
│   │   ├── KirbyMock.jsx     # ぱむぱむキャラクターのアニメーション
│   │   └── VibrationEffect.jsx  # 興奮度に応じた背景エフェクト
│   └── hooks/
│       ├── useBackendWS.js   # WebSocket通信ロジック
│       └── useVAD.js         # マイク録音ロジック
├── public/
│   └── vad.worklet.bundle.min.js  # VAD用WASMワークレット
├── vite.config.js
└── package.json
```

---

## アプリの画面フロー

```
TitlePage (title)
    ↓ スタートボタンを押す
RulesPage (rules)
    ↓ 10秒後に自動で遷移
SessionPage (session)
    ↓ 120秒経過 or セッション終了
EndPage (end)
    ↓ 戻るボタン
TitlePage (title)
```

**ページ管理**: `App.jsx` の `useState('title')` で現在のページを文字列で管理している。React Routerは使っていない。

---

## 主要ファイルの役割

### `App.jsx`
- 全体のページ状態（`title` / `rules` / `session` / `end`）を管理
- `useBackendWS()` フックを呼び出してWebSocket接続を確立
- WebSocket URLからHTTPベースURLを算出（音声再生に使用）
- アプリ全体を `<VibrationEffect>` でラップして興奮度エフェクトを適用
- 左上にバックエンド接続状態バッジを表示
- 各ページに必要なpropsを渡す

### `SessionPage.jsx`
- セッション中のメイン画面
- 120秒のカウントダウンタイマーを管理
- AIの音声URLが来たら `new Audio(url)` で再生し、再生終了を待ってからユーザーターンに移る
- `useVAD` フックを使ってユーザーターン時に自動録音開始
- ぱむぱむキャラクター、AIのテキスト、残り時間を表示

### `KirbyMock.jsx`
- ぱむぱむキャラクターのCSS実装（ピンクの丸）
- `isTalking` propで口のアニメーションを切り替え（しゃべる/黙る）
- `imageUrl` propを渡すと画像に差し替え可能

### `VibrationEffect.jsx`
- 興奮度（0〜100）に応じて背景色をアニメーション
- 興奮度 > 50 でTailwindの `animate-pulse` + 赤みがかった背景色を適用
- コード内に「初心者担当エリア」コメントあり → カスタマイズ歓迎

### `useBackendWS.js`
- `ws://xxx/ws/frontend` に接続してバックエンドからのメッセージを受信
- 受信したデータを状態に変換してコンポーネントに返す
- ターンの切り替え関数（`setTurnToAi`, `startUserTurn`）も提供

### `useVAD.js`
- `navigator.mediaDevices.getUserMedia` でマイクにアクセス
- `MediaRecorder` で録音（最大10秒）
- 録音完了後に `onRecordingComplete` コールバックを呼び出す
- `@ricky0123/vad-web` はインポートされているが、現状は主に `MediaRecorder` を使用

---

## 状態管理の仕組み

Redux / Context は使っていない。すべて `useState` + カスタムフック。

```
App.jsx
  ├── page (useState)
  └── useBackendWS() ─ agitationLevel, aiText, aiAudioUrl, turn, aiTurnEnded, connected
                        setTurnToAi(), startUserTurn()
        ↓ props
SessionPage.jsx
  ├── sessionTime (useState) ← 120秒タイマー
  ├── isAudioPlaying (useState)
  └── useVAD(turn, httpBase, setTurnToAi)
        ├── isSpeaking
        ├── timeLeft
        └── vadError
```

---

## バックエンドとの通信

### WebSocket受信 (`/ws/frontend`)

バックエンドから以下のJSON形式でメッセージが来る:

| type | 内容 | フィールド |
|------|------|-----------|
| `agitation_update` | 興奮度更新 | `level` (0-100), `trend` ('rising'/'stable'/'falling') |
| `ai_text` | AIテキスト（ストリーミング） | `text` (追記される) |
| `ai_audio` | AI音声のURL | `url` (例: `/audio/line1.m4a`) |
| `ai_turn_end` | AIターン終了の合図 | なし |

### HTTP POST送信 (`/api/audio`)

ユーザーが話し終えたら音声データをPOSTする:

```
POST ${httpBase}/api/audio
Content-Type: audio/webm
Body: 録音したBlob
```

レスポンス: `{ "status": "accepted" }`
バックエンドが受け取ってSTT→AI生成を非同期で処理する（返答は上記WebSocketで来る）。

### URLの算出方法

```javascript
// App.jsx内での処理
const wsUrl = 'ws://localhost:8000/ws/frontend'
const httpBase = wsUrl.replace(/^ws/, 'http').replace(/\/ws\/.*$/, '')
// → 'http://localhost:8000'

// 音声再生時
const audioUrl = httpBase + '/audio/line1.m4a'
// → 'http://localhost:8000/audio/line1.m4a'
```

---

## 音声録音・再生の仕組み

### 録音フロー（ユーザーターン）

```
turn === 'user'
    ↓
useVAD内でstartRecording()
    ↓
getUserMedia() → MediaRecorder作成 → recording開始
    ↓ (最大10秒)
recorder.stop() → onstop発火
    ↓
Blob生成 → POST /api/audio
    ↓
onRecordingComplete() → setTurnToAi()
```

### 再生フロー（AIターン）

```
WebSocketで { type: 'ai_audio', url: '/audio/line1.m4a' } 受信
    ↓
aiAudioUrl が更新される
    ↓
SessionPage内でuseEffectが発火
    ↓
new Audio(httpBase + url).play()
    ↓
audio.onended → isAudioPlaying = false
    ↓
aiTurnEnded && !isAudioPlaying → startUserTurn()
```

> **重要**: 音声再生が完全に終わってから `startUserTurn()` を呼ぶ。再生完了を待たずにユーザーターンにならないよう `isAudioPlaying` フラグで制御している。

---

## ターン制の仕組み

```
turn: 'ai' | 'user'
```

| ターン | UI状態 | マイク | 表示 |
|-------|-------|-------|------|
| `ai` | AIが話す | 無効 | AIテキスト表示、ぱむぱむが喋るアニメ |
| `user` | ユーザーが話す | 有効（自動録音開始） | 「🎤 話してください」表示 |

**ターン遷移のトリガー**:
- AI → User: `ai_turn_end` + 音声再生完了 → `startUserTurn()`
- User → AI: 録音完了 → `setTurnToAi()`

---

## 環境変数

`frontend/.env` または Docker環境変数で設定:

| 変数名 | デフォルト | 説明 |
|--------|-----------|------|
| `VITE_BACKEND_WS_URL` | `ws://localhost:8000/ws/frontend` | バックエンドWebSocketのURL |

バックエンド側の変数（参考）:

| 変数名 | 説明 |
|--------|------|
| `MOCK_MODE` | `true` でバックエンドをモックモードで起動 |
| `GEMINI_API_KEY` | Google Gemini APIキー |
| `GEMINI_MODEL` | 使用するGeminiモデルID |

---

## 開発サーバーの起動

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

バックエンドと合わせて起動する場合はプロジェクトルートの `docker-compose.yml` を使う:

```bash
docker compose up
```

---

## よくある注意点

- **音声関連はHTTPS必須**: ブラウザのセキュリティポリシーにより、本番環境では `getUserMedia` はHTTPS経由でのみ動く。`localhost` は例外。
- **VAD WASMファイル**: `public/vad.worklet.bundle.min.js` は `@ricky0123/vad-web` の内部で使われるワークレット。削除しないこと。
- **VibrationEffect**: `agitationLevel` が 50 を超えると背景が赤くなるアニメーションが入る。カスタマイズは `VibrationEffect.jsx` で行う（コメントあり）。
- **KirbyMock**: 現状はCSS実装の仮キャラクター。`imageUrl` propに画像URLを渡せば画像に差し替えられる。
