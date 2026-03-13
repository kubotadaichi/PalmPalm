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

振動センサーの動揺スコアを管理するローカルサーバー。

```bash
cd backend
uv run uvicorn src.agitation_server:app --host 0.0.0.0 --port 8001
```

---

### ③ シリアルリーダー（ターミナル2）

Pico（振動センサー）のシリアル出力を監視し、検知のたびに Agitation サーバーへ通知する。

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

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/health` | GET | ヘルスチェック |
| `/api/audio` | POST | ユーザー音声受信 → SSE でステージ1/2返却 |
| `/audio/*` | GET | TTS 生成済み音声ファイル配信 |

### Agitation サーバー（port 8001）

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/pulse` | POST | 振動検知時に呼ぶ |
| `/agitation` | GET | 動揺スコア取得 |
