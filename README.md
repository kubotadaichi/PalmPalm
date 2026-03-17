# ぱむぱむ — AI 手相占い

ハッカソン作品。手に振動センサーを当てながら AI 手相占い師「ぱむぱむ」と会話すると、リアルタイムで検知された身体的動揺度に応じて占いの追い込みが変化する。

## デモ

1. タイトル画面で「占いを始める」
2. 何を占って欲しいか（仕事・恋愛など）を伝える
3. ぱむぱむが手相を読み始め、図星を突いてくる

## システム構成

```
[ブラウザ]
    │ WebSocket (PCM 音声 / JSON イベント)
    ▼
[バックエンド: FastAPI]
    │ Gemini Live API (音声 in/out + tool call)
    ▼
[Gemini 2.5 Flash Native Audio]
    │ get_agitation tool call
    ▼
[ラズパイ agitation サーバー]  ← 振動センサーのパルスを集計
```

- **フロントエンド**: React + Web Audio API (PCM 24kHz 再生)
- **バックエンド**: FastAPI + WebSocket + google-genai Live API
- **ラズパイ**: 振動センサー → `POST /pulse` → `GET /agitation/window` で動揺度を返す
- **Pico**: 振動センサーのシリアル出力をラズパイへ中継（オプション）

## 起動方法

### 前提

- Docker / Docker Compose
- Gemini API キー

### 1. 環境変数を設定

```bash
cp backend/.env.example backend/.env
# GEMINI_API_KEY=your_key_here を記入
```

### 2. Docker で起動

```bash
docker compose up --build
```

ブラウザで http://localhost:5173 を開く。

### ラズパイ（振動センサー）を使う場合

```bash
# ラズパイ上で
cd raspberry_pi
pip install -r requirements.txt
uvicorn server:app --host 0.0.0.0 --port 8001
```

`docker-compose.yml` の `AGITATION_API_URL` をラズパイの IP に変更する。

### Pico（振動センサー → シリアル）を使う場合

```bash
# Pico に MicroPython をフラッシュ後
mpremote connect auto cp pico/main.py :main.py

# Mac でシリアルブリッジを起動
cd pico
pip install -r requirements.txt
python serial_bridge.py
```

## 動揺レベルの定義

| level | 状態 | ぱむぱむの反応 |
|-------|------|---------------|
| 0〜10 | 無反応 | 静かに語りかける |
| 10〜30 (rising) | 微反応・上昇 | 核心に迫り始める |
| 10〜30 (stable) | 微反応・横ばい | 「隠してますね」 |
| 30〜60 (rising) | 反応あり | 感情を名指し |
| 60〜80 (rising) | 強い反応 | 断言・畳み掛け |
| 60〜80 (falling) | 強い反応・落ち着き | 逃げを指摘して追い込む |
| 80以上 | 最大反応 | 完全断言・一切逃がさない |

## ディレクトリ構成

```
.
├── backend/          # FastAPI バックエンド
│   └── src/
│       ├── live_session.py    # Gemini Live API セッション管理
│       ├── agitation_engine.py
│       └── main.py            # WebSocket エンドポイント
├── frontend/         # React フロントエンド
│   └── src/
│       ├── hooks/useSession.js  # WebSocket + 音声再生
│       └── pages/
├── raspberry_pi/     # ラズパイ用 agitation サーバー
├── pico/             # Pico 用 MicroPython + シリアルブリッジ
└── docker-compose.yml
```
