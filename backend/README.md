# PalmPalm バックエンド

## 起動手順

### 前提

`backend/` ディレクトリに `.env` を作成：

```
GEMINI_API_KEY=your_key_here
```

---

### ① Docker（Backend + Frontend）

```bash
cd /path/to/PalmPalm
docker compose up --build
```

- Frontend: http://localhost:5173
- Backend API: http://localhost:8000

---

### ② Agitation サーバー（ターミナル1）

振動検知の動揺スコアを管理するローカルサーバー。

```bash
cd backend
uv run uvicorn src.agitation_server:app --host 0.0.0.0 --port 8001
```

---

### ③ シリアルリーダー（ターミナル2）

Pico のシリアル出力を監視し、検知のたびに Agitation サーバーへ通知する。

```bash
# ポートを確認
ls /dev/tty.usbmodem*

# 起動
cd backend
uv run python -m src.serial_reader --port /dev/tty.usbmodem1101
```

> `--port` は実際のポート名に合わせること。

---

### 起動順序まとめ

| 順番 | コマンド | 場所 |
|------|----------|------|
| 1 | `docker compose up --build` | PalmPalm/ |
| 2 | `uv run uvicorn src.agitation_server:app --host 0.0.0.0 --port 8001` | backend/ |
| 3 | `uv run python -m src.serial_reader --port /dev/tty.usbmodemXXXX` | backend/ |

---

## エンドポイント一覧

### メインサーバー（port 8000）

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/health` | GET | ヘルスチェック |
| `/ws/session` | WebSocket | 占いセッション（PCM ストリーミング） |

### WebSocket メッセージ仕様 (`/ws/session`)

**フロントエンド → バックエンド**

| type / フレーム | 内容 |
|---|---|
| binary | PCM 16kHz mono int16 チャンク（マイク入力） |
| `{"type": "input_audio_end"}` | 発話終了の補助通知 |
| `{"type": "session_end"}` | セッション終了 |

**バックエンド → フロントエンド**

| type | 内容 |
|---|---|
| `session_ready` | セッション確立完了 |
| `audio_chunk` | AI 音声（base64 PCM 24kHz）|
| `turn_complete` | AI の発話終了 |

---

### Agitation サーバー（port 8001）

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/health` | GET | ヘルスチェック |
| `/pulse` | POST | 振動検知時に呼ぶ |
| `/agitation` | GET | 動揺スコア取得（現在値） |
| `/agitation/window?from_ts=X&to_ts=Y` | GET | 指定時間窓の動揺スコア取得 |
