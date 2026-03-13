# Agitation Server Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Pico からのシリアル振動データを受け取り、動揺率を `GET /agitation` で提供する FastAPI サーバと serial_reader を実装する。

**Architecture:** `agitation_server.py` が `AgitationEngine` をシングルトンとして保持し FastAPI で `/agitation`・`/pulse` を公開する。`serial_reader.py` がシリアルポートを監視して `"Vibration detected!"` 行を検知するたびに `POST /pulse` を叩く。両プロセスをホスト上で Docker 外に起動する。

**Tech Stack:** FastAPI, uvicorn, pyserial, httpx（テスト用）, pytest, pytest-asyncio

---

### Task 1: pyserial を依存関係に追加

**Files:**
- Modify: `backend/pyproject.toml`

**Step 1: pyserial を追加**

```toml
dependencies = [
    ...
    "pyserial>=3.5",
]
```

**Step 2: 依存関係を同期**

```bash
cd backend
uv sync
```

Expected: `pyserial` がインストールされる

**Step 3: コミット**

```bash
git add backend/pyproject.toml backend/uv.lock
git commit -m "chore: add pyserial dependency"
```

---

### Task 2: agitation_server.py を実装

**Files:**
- Create: `backend/src/agitation_server.py`
- Test: `backend/tests/test_agitation_server.py`

**Step 1: 失敗するテストを書く**

`backend/tests/test_agitation_server.py` を作成:

```python
# backend/tests/test_agitation_server.py
import pytest
from httpx import AsyncClient, ASGITransport
from src.agitation_server import app, engine


@pytest.fixture(autouse=True)
def reset_engine():
    """各テスト前にエンジンをリセット"""
    engine._pulses.clear()
    engine._previous_level = 0


@pytest.mark.asyncio
async def test_health():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_agitation_initial():
    """初期状態は level=0, trend=stable"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get("/agitation")
    assert resp.status_code == 200
    data = resp.json()
    assert data["level"] == 0
    assert data["trend"] == "stable"


@pytest.mark.asyncio
async def test_pulse_increases_level():
    """POST /pulse を10回叩くと level が上がる"""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for _ in range(10):
            await ac.post("/pulse")
        resp = await ac.get("/agitation")
    data = resp.json()
    assert data["level"] > 0


@pytest.mark.asyncio
async def test_pulse_returns_ok():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.post("/pulse")
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
```

**Step 2: テストが失敗することを確認**

```bash
cd backend
uv run pytest tests/test_agitation_server.py -v
```

Expected: `ImportError: cannot import name 'app' from 'src.agitation_server'`

**Step 3: 実装を書く**

`backend/src/agitation_server.py` を作成:

```python
# backend/src/agitation_server.py
from fastapi import FastAPI
from .agitation_engine import AgitationEngine

engine = AgitationEngine(window_seconds=10, max_pulses=20)

app = FastAPI()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/agitation")
def get_agitation():
    return engine.snapshot()


@app.post("/pulse")
def post_pulse():
    engine.record_pulse()
    return {"ok": True}
```

**Step 4: テストが通ることを確認**

```bash
cd backend
uv run pytest tests/test_agitation_server.py -v
```

Expected: 4 passed

**Step 5: コミット**

```bash
git add backend/src/agitation_server.py backend/tests/test_agitation_server.py
git commit -m "feat: add agitation FastAPI server"
```

---

### Task 3: serial_reader.py を実装

**Files:**
- Create: `backend/src/serial_reader.py`
- Test: `backend/tests/test_serial_reader.py`

**Step 1: 失敗するテストを書く**

`backend/tests/test_serial_reader.py` を作成:

```python
# backend/tests/test_serial_reader.py
from unittest.mock import patch, MagicMock
import pytest
from src.serial_reader import should_record_pulse, VIBRATION_KEYWORD


def test_vibration_line_triggers_pulse():
    """'Vibration detected!' を含む行は True"""
    assert should_record_pulse("Vibration detected!") is True


def test_dots_line_does_not_trigger():
    """'...' は False"""
    assert should_record_pulse("...") is False


def test_empty_line_does_not_trigger():
    assert should_record_pulse("") is False


def test_keyword_is_correct():
    assert VIBRATION_KEYWORD == "Vibration detected!"
```

**Step 2: テストが失敗することを確認**

```bash
cd backend
uv run pytest tests/test_serial_reader.py -v
```

Expected: `ImportError: cannot import name 'should_record_pulse'`

**Step 3: 実装を書く**

`backend/src/serial_reader.py` を作成:

```python
# backend/src/serial_reader.py
"""
シリアルポートから Pico の振動センサー出力を読み取り、
"Vibration detected!" を検知するたびに POST /pulse を叩く。

使い方:
    python -m backend.src.serial_reader --port /dev/tty.usbmodem1234
    python -m backend.src.serial_reader --port COM3 --baud 115200
"""
import argparse
import os
import time

import httpx
import serial

VIBRATION_KEYWORD = "Vibration detected!"


def should_record_pulse(line: str) -> bool:
    return VIBRATION_KEYWORD in line


def run(port: str, baud: int, server_url: str) -> None:
    print(f"[serial_reader] Connecting to {port} @ {baud}bps")
    with serial.Serial(port, baud, timeout=1) as ser:
        print(f"[serial_reader] Connected. Watching for vibrations...")
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore").strip()
            if should_record_pulse(line):
                try:
                    httpx.post(f"{server_url}/pulse", timeout=2.0)
                except Exception as e:
                    print(f"[serial_reader] POST /pulse failed: {e}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Pico vibration serial reader")
    parser.add_argument("--port", default=os.getenv("SERIAL_PORT", ""), required=False)
    parser.add_argument("--baud", type=int, default=int(os.getenv("SERIAL_BAUD", "9600")))
    parser.add_argument(
        "--server",
        default=os.getenv("AGITATION_SERVER_URL", "http://localhost:8001"),
    )
    args = parser.parse_args()

    if not args.port:
        parser.error("--port または SERIAL_PORT 環境変数でシリアルポートを指定してください")

    run(args.port, args.baud, args.server)


if __name__ == "__main__":
    main()
```

**Step 4: テストが通ることを確認**

```bash
cd backend
uv run pytest tests/test_serial_reader.py -v
```

Expected: 4 passed

**Step 5: コミット**

```bash
git add backend/src/serial_reader.py backend/tests/test_serial_reader.py
git commit -m "feat: add serial reader for Pico vibration sensor"
```

---

### Task 4: 全テストが通ることを確認してコミット

**Step 1: 全テストを実行**

```bash
cd backend
uv run pytest -v
```

Expected: 全テスト passed（既存テスト含む）

**Step 2: 起動方法を手動確認（任意）**

```bash
# ターミナル1
cd backend
uv run uvicorn src.agitation_server:app --port 8001

# ターミナル2
cd backend
uv run python -m src.serial_reader --port /dev/tty.usbmodemXXXX
```

`curl http://localhost:8001/agitation` で `{"level": 0, "trend": "stable"}` が返ることを確認。

**Step 3: 最終コミット（必要に応じて）**

```bash
git add -u
git commit -m "chore: verify all tests pass for agitation server"
```
