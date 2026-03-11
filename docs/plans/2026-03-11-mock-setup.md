# Mock Setup Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Gemini LiveとRaspberry Piのモックを作り、`docker compose up` 一発でフロントエンド開発できる環境を整える。

**Architecture:** `MockGeminiSessionManager` を新規作成し `GeminiSessionManager` と同じインターフェースで差し替え可能にする。`MOCK_MODE=true` で切り替え。docker-composeにbackendサービスを追加して全スタックをコンテナで動かす。

**Tech Stack:** Python 3.11, FastAPI, uvicorn, uv, Docker Compose

---

### Task 1: MockGeminiSessionManager のテストを書く

**Files:**
- Create: `backend/tests/test_mock_gemini_session.py`

**Step 1: テストファイルを作成**

```python
# backend/tests/test_mock_gemini_session.py
import asyncio
import pytest
from unittest.mock import AsyncMock
from src.agitation_engine import AgitationEngine
from src.mock_gemini_session import MockGeminiSessionManager


@pytest.mark.asyncio
async def test_start_session_calls_broadcast():
    """start_session後、ai_textがbroadcastされる"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    received = []
    async def fake_broadcast(data):
        received.append(data)

    mock.set_broadcast_callback(fake_broadcast)
    await mock.start_session()

    # 少し待ってメッセージが届くか確認
    await asyncio.sleep(0.1)
    mock.stop()

    assert any(m["type"] == "ai_text" for m in received)


@pytest.mark.asyncio
async def test_send_push_broadcasts_spike_text():
    """send_push後、豹変セリフがbroadcastされる"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    received = []
    async def fake_broadcast(data):
        received.append(data)

    mock.set_broadcast_callback(fake_broadcast)
    await mock.start_session()
    await mock.send_push(level=80, trend="rising")

    await asyncio.sleep(0.1)
    mock.stop()

    texts = [m["text"] for m in received if m["type"] == "ai_text"]
    assert any(texts), "豹変セリフが届いていない"


@pytest.mark.asyncio
async def test_set_broadcast_callback():
    """set_broadcast_callbackで登録したコールバックが使われる"""
    engine = AgitationEngine()
    mock = MockGeminiSessionManager(engine)

    cb = AsyncMock()
    mock.set_broadcast_callback(cb)
    await mock.start_session()
    await asyncio.sleep(0.1)
    mock.stop()

    assert cb.called
```

**Step 2: テストが失敗することを確認**

```bash
cd backend && uv run pytest tests/test_mock_gemini_session.py -v
```
期待: `ImportError: cannot import name 'MockGeminiSessionManager'`

---

### Task 2: MockGeminiSessionManager を実装する

**Files:**
- Create: `backend/src/mock_gemini_session.py`

**Step 1: ファイルを作成**

```python
# backend/src/mock_gemini_session.py
"""
Gemini Live APIのモック実装。
MOCK_MODE=true のときに GeminiSessionManager の代わりに使う。
GeminiSessionManager と同じインターフェース(start_session / send_push / set_broadcast_callback)を持つ。
"""
import asyncio
import random
from .agitation_engine import AgitationEngine

# 通常の手相占い台本（神秘的・低トーン）
_READING_SCRIPT = [
    "あなたの手相には、深い感情線が刻まれています。",
    "生命線は力強く、長い旅路を示しています。",
    "知能線が少し湾曲している。創造性の証です。",
    "小指の付け根に薄い縦線が…コミュニケーション運が高い。",
    "運命線がはっきりと中央を走っている。強い意志を感じます。",
    "太陽線が複数本ある。多才で、人を惹きつける力があります。",
]

# 動揺急上昇時の豹変セリフ
_SPIKE_RESPONSES = [
    "ほら！震えてますよね！？当たったでしょ！！",
    "手が揺れてる！この反応、隠せないですよ！",
    "やっぱり！今の線のこと、心当たりがあるでしょ！？",
    "動揺してますよね？当たりすぎて怖いですか？",
]


class MockGeminiSessionManager:
    def __init__(self, agitation_engine: AgitationEngine):
        self.engine = agitation_engine
        self._broadcast_callback = None
        self._task: asyncio.Task | None = None
        self._running = False

    def set_broadcast_callback(self, callback):
        self._broadcast_callback = callback

    async def start_session(self):
        """台本ループと振動モックをバックグラウンドで起動"""
        self._running = True
        self._task = asyncio.create_task(self._script_loop())
        asyncio.create_task(self._vibration_loop())

    def stop(self):
        """テスト用にループを止める"""
        self._running = False
        if self._task:
            self._task.cancel()

    async def send_push(self, level: int, trend: str):
        """動揺急上昇時の豹変セリフを送信"""
        if not self._broadcast_callback:
            return
        text = random.choice(_SPIKE_RESPONSES)
        for chunk in _chunks(text, size=10):
            await self._broadcast_callback({"type": "ai_text", "text": chunk})
            await asyncio.sleep(0.05)

    async def _script_loop(self):
        """3〜6秒ごとに台本テキストをチャンクで送信。終わったら先頭に戻る"""
        idx = 0
        while self._running:
            await asyncio.sleep(random.uniform(3.0, 6.0))
            if not self._running:
                break
            line = _READING_SCRIPT[idx % len(_READING_SCRIPT)]
            idx += 1
            if self._broadcast_callback:
                for chunk in _chunks(line, size=8):
                    await self._broadcast_callback({"type": "ai_text", "text": chunk})
                    await asyncio.sleep(0.05)

    async def _vibration_loop(self):
        """ランダムに振動イベントを発生させてフロントに配信"""
        while self._running:
            await asyncio.sleep(random.uniform(0.5, 2.0))
            if not self._running:
                break
            self.engine.record_pulse()
            snapshot = self.engine.snapshot()
            if self._broadcast_callback:
                await self._broadcast_callback({
                    "type": "agitation_update",
                    "level": snapshot["level"],
                    "trend": snapshot["trend"],
                })


def _chunks(text: str, size: int) -> list[str]:
    """テキストをsizeバイト単位のチャンクに分割（ストリーミング風）"""
    return [text[i:i + size] for i in range(0, len(text), size)]
```

**Step 2: テストを実行して確認**

```bash
cd backend && uv run pytest tests/test_mock_gemini_session.py -v
```
期待: 3テストすべて PASS

**Step 3: コミット**

```bash
git add backend/src/mock_gemini_session.py backend/tests/test_mock_gemini_session.py
git commit -m "feat: add MockGeminiSessionManager for frontend development"
```

---

### Task 3: main.py を MOCK_MODE で切り替える

**Files:**
- Modify: `backend/src/main.py`

**Step 1: main.py を書き換える**

`backend/src/main.py` の先頭付近を修正する。変更点は2つ:
1. `MockGeminiSessionManager` をインポートする
2. `gemini` の初期化を `MOCK_MODE` で切り替える
3. `lifespan` 内の `mock_vibration_loop` の起動を削除（MockGeminiSessionManager内に移動済み）

変更前:
```python
from .agitation_engine import AgitationEngine
from .gemini_session import GeminiSessionManager

load_dotenv()

engine = AgitationEngine(window_seconds=10, max_pulses=20)
gemini = GeminiSessionManager(engine)
```

変更後:
```python
from .agitation_engine import AgitationEngine
from .gemini_session import GeminiSessionManager
from .mock_gemini_session import MockGeminiSessionManager

load_dotenv()

engine = AgitationEngine(window_seconds=10, max_pulses=20)
_mock_mode = os.getenv("MOCK_MODE", "false").lower() == "true"
gemini = MockGeminiSessionManager(engine) if _mock_mode else GeminiSessionManager(engine)
```

また `lifespan` 内の以下を削除する:
```python
    else:
        asyncio.create_task(mock_vibration_loop())
        print("[Backend] Mock mode enabled - random vibration events active")
```

そして `lifespan` を次のように変更する:
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    gemini.set_broadcast_callback(broadcast_to_frontend)
    if _mock_mode:
        await gemini.start_session()
        print("[Backend] Mock mode - MockGeminiSessionManager started")
    else:
        try:
            await gemini.start_session()
            print("[Backend] Gemini Live session started")
        except Exception as e:
            print(f"[Backend] Failed to start Gemini session: {e}")
    yield
```

`mock_vibration_loop` 関数定義ごと削除してよい（MockGeminiSessionManager._vibration_loop に移動済み）。

**Step 2: バックエンドをローカルで起動して動作確認**

```bash
cd backend && MOCK_MODE=true uv run uvicorn src.main:app --reload --port 8000
```

別ターミナルで:
```bash
curl http://localhost:8000/health
```
期待: `{"status":"ok","mock_mode":true,"frontend_clients":0}`

**Step 3: コミット**

```bash
git add backend/src/main.py
git commit -m "refactor: switch gemini session by MOCK_MODE flag"
```

---

### Task 4: backend の Dockerfile を作成する

**Files:**
- Create: `backend/Dockerfile`

**Step 1: Dockerfile を作成**

```dockerfile
FROM python:3.11-slim

# uv をインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 依存関係を先にコピーしてキャッシュを効かせる
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ソースはvolumesでマウントするのでCOPYしない
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
```

**Step 2: ビルドできるか確認**

```bash
cd backend && docker build -t palmpalm-backend .
```
期待: Successfully built ...

**Step 3: コミット**

```bash
git add backend/Dockerfile
git commit -m "feat: add backend Dockerfile with uv"
```

---

### Task 5: docker-compose.yml に backend を追加する

**Files:**
- Modify: `docker-compose.yml`

**Step 1: docker-compose.yml を書き換える**

既存の `frontend` サービスの前に `backend` サービスを追加する:

```yaml
services:
  backend:
    build:
      context: ./backend
      dockerfile: Dockerfile
    ports:
      - "8000:8000"
    volumes:
      - ./backend/src:/app/src
    environment:
      - MOCK_MODE=true
      - GEMINI_API_KEY=${GEMINI_API_KEY:-dummy}
    extra_hosts:
      - "host.docker.internal:host-gateway"

  frontend:
    build:
      context: ./frontend
      dockerfile: Dockerfile
    ports:
      - "5173:5173"
    volumes:
      - ./frontend/src:/app/src
      - ./frontend/public:/app/public
      - ./frontend/index.html:/app/index.html
      - ./frontend/vite.config.js:/app/vite.config.js
    environment:
      - VITE_BACKEND_WS_URL=ws://host.docker.internal:8000/ws/frontend
    extra_hosts:
      - "host.docker.internal:host-gateway"
    depends_on:
      - backend
```

**Step 2: 全スタック起動確認**

```bash
docker compose up --build
```

別ターミナルで:
```bash
curl http://localhost:8000/health
# → {"status":"ok","mock_mode":true,"frontend_clients":0}
```

ブラウザで `http://localhost:5173` を開き、SessionPageで動揺率が動いてAIテキストが流れることを確認。

**Step 3: コミット**

```bash
git add docker-compose.yml
git commit -m "feat: add backend service to docker-compose with MOCK_MODE"
```

---

### Task 6: .env.example を作成してコラボレーター向けに説明を整備する

**Files:**
- Create: `backend/.env.example`

**Step 1: .env.example を作成**

```bash
# backend/.env.example
# Gemini Live API キー（本番時のみ必要。MOCK_MODE=true なら不要）
GEMINI_API_KEY=your_api_key_here

# true にするとラズパイ・Gemini なしでフロント開発できる
MOCK_MODE=false
```

**Step 2: .gitignore に .env が含まれているか確認**

```bash
grep -n "\.env" .gitignore
```

含まれていなければ追加:
```
.env
```

**Step 3: コミット**

```bash
git add backend/.env.example .gitignore
git commit -m "docs: add .env.example for collaborator onboarding"
```
