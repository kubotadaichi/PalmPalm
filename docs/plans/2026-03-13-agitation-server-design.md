# Agitation Server Design

**Date:** 2026-03-13

## Overview

Raspberry Pi Pico（MicroPython）で振動センサーを読み取り、動揺率をメインバックエンドに提供するサーバを実装する。Docker外でホスト上に2プロセスで構成する。

## Background

- `AgitationEngine` はスライディングウィンドウ方式で振動パルスを動揺率（0-100）に変換するロジックとして既に実装済み
- `TwoStageSessionManager` は `GET /agitation` を外部サーバに投げる想定で実装済み（`agitation_api_url`）
- Pico は MicroPython 上で振動センサー（GPIO16）を読み取り、`"Vibration detected!"` または `"..."` をシリアル出力する

## Architecture

```
Pico（MicroPython, GPIO16）
  → "Vibration detected!" / "..." @ 0.1秒間隔
  → USB シリアル
  → serial_reader.py（ホスト上）
      └── POST /pulse → agitation_server.py（ホスト, port 8001）
                              ↑ GET /agitation
              メインバックエンド（AGITATION_API_URL=http://localhost:8001）
```

## Components

### `backend/src/agitation_server.py`

FastAPI アプリ。`AgitationEngine` をシングルトンとして保持。

| エンドポイント | メソッド | 説明 |
|---|---|---|
| `/agitation` | GET | `engine.snapshot()` を返す `{"level": int, "trend": str}` |
| `/pulse` | POST | `engine.record_pulse()` を呼ぶ `{"ok": true}` |
| `/health` | GET | `{"status": "ok"}` |

### `backend/src/serial_reader.py`

`pyserial` でシリアルポートを監視し、`"Vibration detected!"` を含む行を検知したら `POST /pulse` を叩く。

- ポートは `--port` 引数 or `SERIAL_PORT` 環境変数で指定
- ボーレート: 9600（デフォルト）、`--baud` で変更可
- 接続先: `http://localhost:8001`（`AGITATION_SERVER_URL` 環境変数で変更可）

## Startup

```bash
# ターミナル1: agitation サーバ起動
uvicorn backend.src.agitation_server:app --port 8001

# ターミナル2: シリアル読み取り起動
python -m backend.src.serial_reader --port /dev/tty.usbmodem1234
```

## Dependencies

- `fastapi`, `uvicorn` — 既にバックエンドで使用
- `pyserial` — serial_reader 用に追加が必要

## Out of Scope

- Docker への組み込み（意図的に除外）
- Pico 側のコード変更（既存スクリプトをそのまま使用）
