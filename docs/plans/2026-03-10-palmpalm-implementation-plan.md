# PalmPalm 実装プラン（事前準備）

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** ハッカソン当日までに「Gemini Live API PoC」「Dockerスキャフォールド」「ラズパイ疎通」「初心者用環境」を完成させる

**Architecture:** Mac Backend（FastAPI）がGemini Live APIセッションを管理し、ラズパイの振動センサーからの0/1パルスを動揺率に変換してLLMに渡す。フロントはDockerで動くReact/Vite。

**Tech Stack:** Python 3.11+, FastAPI, uv, google-genai (Gemini Live), React, Vite, Tailwind CSS, Docker

---

## Task 1: プロジェクト構造のセットアップ

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/src/__init__.py`
- Create: `frontend/` (Viteプロジェクト)

**Step 1: バックエンドをuvで初期化**

```bash
mkdir -p backend && cd backend
uv init --name palmpalm-backend --python 3.11
uv add fastapi uvicorn websockets google-genai python-dotenv
uv add --dev pytest pytest-asyncio httpx
```

**Step 2: フロントエンドをViteで初期化**

```bash
cd .. && npm create vite@latest frontend -- --template react-ts
cd frontend && npm install
npm install -D tailwindcss @tailwindcss/vite
```

**Step 3: .envファイルを作成**

```bash
cat > backend/.env << 'EOF'
GEMINI_API_KEY=your_key_here
MOCK_MODE=true
EOF
```

**Step 4: .gitignoreに追加**

```
backend/.env
backend/.venv/
frontend/node_modules/
frontend/dist/
```

**Step 5: コミット**

```bash
git add .
git commit -m "feat: initialize project structure (backend + frontend)"
```

---

## Task 2: Gemini Live API PoC（最重要）

**Files:**
- Create: `backend/src/gemini_poc.py`
- Create: `backend/tests/test_gemini_poc.py`

**目的:** Gemini Live APIで「音声セッション確立」「テキスト送信」「セッション中割り込み」が動くことを確認する

**Step 1: Gemini Live APIの動作確認スクリプトを書く**

```python
# backend/src/gemini_poc.py
import asyncio
import os
from google import genai
from google.genai.live import AsyncSession
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """あなたはAI手相占い師「ぱむぱむ」です。
ユーザーの手相を占います。
ユーザーの揺れ率は占いの的確度への反応です。
levelが高いほど当たっている。trend: risingなら確信を持って追い込め。
Push通知が来たら必ずリアクションしろ。"""

async def run_poc():
    config = {
        "system_instruction": SYSTEM_PROMPT,
        "response_modalities": ["TEXT"],
        "tools": [{"function_declarations": [
            {
                "name": "get_agitation_level",
                "description": "ユーザーの現在の動揺率を取得する",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {},
                    "required": []
                }
            }
        ]}]
    }

    async with client.aio.live.connect(
        model="gemini-2.0-flash-live-001",
        config=config
    ) as session:
        print("セッション確立成功")

        # テスト1: テキスト送信
        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": "私の手相を占ってください"}]},
            turn_complete=True
        )
        async for response in session.receive():
            if response.text:
                print(f"AI応答: {response.text}")
            if response.server_content and response.server_content.turn_complete:
                break

        # テスト2: 割り込み指示（Pushシミュレーション）
        print("\n--- 動揺急上昇をシミュレーション ---")
        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": "[システム通知] ユーザーが75%動揺しています。追い込め。"}]},
            turn_complete=True
        )
        async for response in session.receive():
            if response.text:
                print(f"AI割り込み応答: {response.text}")
            if response.server_content and response.server_content.turn_complete:
                break

        print("\nPoC完了")

if __name__ == "__main__":
    asyncio.run(run_poc())
```

**Step 2: PoCを実行して動作確認**

```bash
cd backend
uv run python src/gemini_poc.py
```

期待される出力:
```
セッション確立成功
AI応答: （手相占いのセリフ）
--- 動揺急上昇をシミュレーション ---
AI割り込み応答: （追い込むセリフ）
PoC完了
```

エラーが出た場合の確認ポイント:
- `GEMINI_API_KEY`が正しいか
- Live APIが有効になっているか（Google AI Studio → API Keys → Live API）
- モデル名が正しいか（`gemini-2.0-flash-live-001`）

**Step 3: Tool Use（get_agitation_level）の動作確認**

```python
# backend/src/gemini_poc_tooluse.py
# PoCスクリプトに追加: Tool Callへの応答処理

async def handle_tool_call(session: AsyncSession, tool_call):
    """Geminiからget_agitation_levelが呼ばれたときの応答"""
    if tool_call.function_calls:
        for fc in tool_call.function_calls:
            if fc.name == "get_agitation_level":
                # モック値を返す
                await session.send_tool_response(
                    function_responses=[{
                        "name": "get_agitation_level",
                        "id": fc.id,
                        "response": {"result": {"level": 60, "trend": "rising"}}
                    }]
                )
```

**Step 4: Tool Useが機能するか確認**

```bash
uv run python src/gemini_poc_tooluse.py
```

**Step 5: コミット**

```bash
git add backend/src/gemini_poc.py backend/src/gemini_poc_tooluse.py
git commit -m "feat: add Gemini Live API PoC scripts"
```

---

## Task 3: 動揺率エンジン（バックエンドコア）

**Files:**
- Create: `backend/src/agitation_engine.py`
- Create: `backend/tests/test_agitation_engine.py`

**Step 1: テストを書く**

```python
# backend/tests/test_agitation_engine.py
import time
import pytest
from src.agitation_engine import AgitationEngine

def test_initial_level_is_zero():
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    assert engine.level == 0
    assert engine.trend == "stable"

def test_pulse_increases_level():
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    for _ in range(10):
        engine.record_pulse()
    assert engine.level == 50

def test_trend_rising():
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 20
    for _ in range(15):
        engine.record_pulse()
    assert engine.trend == "rising"

def test_trend_falling():
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 80
    for _ in range(5):
        engine.record_pulse()
    assert engine.trend == "falling"

def test_is_spike_when_jump_over_30():
    engine = AgitationEngine(window_seconds=10, max_pulses=20)
    engine._previous_level = 10
    for _ in range(18):  # level = 90, diff = 80
        engine.record_pulse()
    assert engine.is_spike() is True
```

**Step 2: テストが失敗することを確認**

```bash
cd backend
uv run pytest tests/test_agitation_engine.py -v
```

期待: `ModuleNotFoundError` or `ImportError`

**Step 3: 実装を書く**

```python
# backend/src/agitation_engine.py
import time
from collections import deque

class AgitationEngine:
    """
    振動センサーの0/1パルスを受け取り、動揺率(0-100)とトレンドを算出する。
    スライディングウィンドウ（直近N秒）で集計。
    """
    SPIKE_THRESHOLD = 30  # 前回比+30以上で急上昇と判定

    def __init__(self, window_seconds: int = 10, max_pulses: int = 20):
        self.window_seconds = window_seconds
        self.max_pulses = max_pulses
        self._pulses: deque[float] = deque()
        self._previous_level: float = 0

    def record_pulse(self):
        """センサーから1を受け取ったときに呼ぶ"""
        now = time.time()
        self._pulses.append(now)
        self._cleanup()

    def _cleanup(self):
        """ウィンドウ外のパルスを削除"""
        cutoff = time.time() - self.window_seconds
        while self._pulses and self._pulses[0] < cutoff:
            self._pulses.popleft()

    @property
    def level(self) -> int:
        self._cleanup()
        return min(100, int(len(self._pulses) / self.max_pulses * 100))

    @property
    def trend(self) -> str:
        current = self.level
        diff = current - self._previous_level
        if diff > 10:
            return "rising"
        elif diff < -10:
            return "falling"
        return "stable"

    def is_spike(self) -> bool:
        return (self.level - self._previous_level) >= self.SPIKE_THRESHOLD

    def snapshot(self) -> dict:
        """Geminiに渡す動揺率スナップショット"""
        current = self.level
        result = {"level": current, "trend": self.trend}
        self._previous_level = current
        return result
```

**Step 4: テストを実行して確認**

```bash
uv run pytest tests/test_agitation_engine.py -v
```

期待: 全テストPASS

**Step 5: コミット**

```bash
git add backend/src/agitation_engine.py backend/tests/test_agitation_engine.py
git commit -m "feat: add AgitationEngine with sliding window vibration rate"
```

---

## Task 4: FastAPI バックエンド本体

**Files:**
- Create: `backend/src/main.py`
- Create: `backend/src/gemini_session.py`

**Step 1: Geminiセッション管理クラスを書く**

```python
# backend/src/gemini_session.py
import asyncio
import os
from google import genai
from .agitation_engine import AgitationEngine

SYSTEM_PROMPT = """あなたはAI手相占い師「ぱむぱむ」です。
ユーザーの手相を見て占います。神秘的かつ毒舌なキャラクターです。
ユーザーの揺れ率は占いの的確度への反応です。
levelが高いほど当たっている証拠。trend: risingなら確信を持って追い込め。
[システム通知]が来たら必ずリアクションしろ。"""

class GeminiSessionManager:
    def __init__(self, agitation_engine: AgitationEngine):
        self.engine = agitation_engine
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self._session = None
        self._broadcast_callback = None

    def set_broadcast_callback(self, callback):
        """フロントエンドへのWebSocket配信コールバックを登録"""
        self._broadcast_callback = callback

    async def start_session(self):
        config = {
            "system_instruction": SYSTEM_PROMPT,
            "response_modalities": ["TEXT"],
            "tools": [{"function_declarations": [{
                "name": "get_agitation_level",
                "description": "ユーザーの現在の動揺率を取得する",
                "parameters": {"type": "OBJECT", "properties": {}, "required": []}
            }]}]
        }
        self._context = self.client.aio.live.connect(
            model="gemini-2.0-flash-live-001",
            config=config
        )
        self._session = await self._context.__aenter__()
        asyncio.create_task(self._receive_loop())

    async def send_push(self, level: int, trend: str):
        """急上昇時の割り込みPush"""
        if self._session:
            msg = f"[システム通知] ユーザーが{level}%動揺しています（{trend}）。追い込め。"
            await self._session.send_client_content(
                turns={"role": "user", "parts": [{"text": msg}]},
                turn_complete=True
            )

    async def _receive_loop(self):
        """Geminiからの応答を受け取りフロントに配信"""
        async for response in self._session.receive():
            if response.tool_call:
                await self._handle_tool_call(response.tool_call)
            if response.text and self._broadcast_callback:
                await self._broadcast_callback({"type": "ai_text", "text": response.text})

    async def _handle_tool_call(self, tool_call):
        for fc in tool_call.function_calls:
            if fc.name == "get_agitation_level":
                snapshot = self.engine.snapshot()
                await self._session.send_tool_response(
                    function_responses=[{
                        "name": "get_agitation_level",
                        "id": fc.id,
                        "response": {"result": snapshot}
                    }]
                )
```

**Step 2: FastAPI mainを書く**

```python
# backend/src/main.py
import asyncio
import json
import os
import random
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from dotenv import load_dotenv
from .agitation_engine import AgitationEngine
from .gemini_session import GeminiSessionManager

load_dotenv()

engine = AgitationEngine(window_seconds=10, max_pulses=20)
gemini = GeminiSessionManager(engine)
frontend_clients: list[WebSocket] = []

async def broadcast_to_frontend(data: dict):
    for ws in frontend_clients[:]:
        try:
            await ws.send_json(data)
        except Exception:
            frontend_clients.remove(ws)

@asynccontextmanager
async def lifespan(app: FastAPI):
    gemini.set_broadcast_callback(broadcast_to_frontend)
    if os.getenv("MOCK_MODE", "false").lower() != "true":
        await gemini.start_session()
    if os.getenv("MOCK_MODE", "false").lower() == "true":
        asyncio.create_task(mock_vibration_loop())
    yield

app = FastAPI(lifespan=lifespan)

async def mock_vibration_loop():
    """モード: ランダムに振動イベントを発生させる"""
    while True:
        await asyncio.sleep(random.uniform(0.5, 2.0))
        engine.record_pulse()
        snapshot = engine.snapshot()
        await broadcast_to_frontend({
            "type": "agitation_update",
            "level": snapshot["level"],
            "trend": snapshot["trend"]
        })

@app.websocket("/ws/sensor")
async def sensor_ws(websocket: WebSocket):
    """ラズパイからの振動データ受信"""
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            if data == "1":
                engine.record_pulse()
                snapshot = engine.snapshot()
                await broadcast_to_frontend({
                    "type": "agitation_update",
                    "level": snapshot["level"],
                    "trend": snapshot["trend"]
                })
                # 急上昇チェック
                if engine.is_spike():
                    await gemini.send_push(snapshot["level"], snapshot["trend"])
    except WebSocketDisconnect:
        pass

@app.websocket("/ws/frontend")
async def frontend_ws(websocket: WebSocket):
    """フロントエンドへのリアルタイム配信"""
    await websocket.accept()
    frontend_clients.append(websocket)
    try:
        while True:
            await websocket.receive_text()  # keep alive
    except WebSocketDisconnect:
        frontend_clients.remove(websocket)

@app.get("/health")
async def health():
    return {"status": "ok", "mock_mode": os.getenv("MOCK_MODE", "false")}
```

**Step 3: バックエンドをモードで起動確認**

```bash
cd backend
MOCK_MODE=true uv run uvicorn src.main:app --reload --port 8000
```

別ターミナルで確認:
```bash
curl http://localhost:8000/health
# 期待: {"status": "ok", "mock_mode": "true"}
```

**Step 4: コミット**

```bash
git add backend/src/main.py backend/src/gemini_session.py
git commit -m "feat: add FastAPI backend with WebSocket + mock mode"
```

---

## Task 5: ラズパイ用センサースクリプト

**Files:**
- Create: `raspi/sensor.py`

**Step 1: センサースクリプトを書く**

```python
# raspi/sensor.py
"""
Raspberry Pi上で動かすセンサースクリプト。
振動センサーのGPIOピンを監視し、振動を検知したらMacのBackendにWebSocketで送る。

使用方法:
  python sensor.py --host 192.168.x.x --port 8000 --pin 17
"""
import asyncio
import argparse
import websockets

# RPiが使えない環境（テスト用）はモックGPIOを使う
try:
    import RPi.GPIO as GPIO
    REAL_GPIO = True
except ImportError:
    REAL_GPIO = False
    print("RPi.GPIO not found - running in mock mode")

async def run(host: str, port: int, pin: int):
    uri = f"ws://{host}:{port}/ws/sensor"
    print(f"Connecting to {uri}")

    async with websockets.connect(uri) as ws:
        print("Connected. Monitoring sensor...")

        if REAL_GPIO:
            GPIO.setmode(GPIO.BCM)
            GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)

        while True:
            if REAL_GPIO:
                if GPIO.input(pin) == GPIO.HIGH:
                    await ws.send("1")
                    await asyncio.sleep(0.05)  # デバウンス
                else:
                    await asyncio.sleep(0.01)
            else:
                # モック: 2秒ごとにランダム送信
                import random
                await asyncio.sleep(random.uniform(0.5, 3.0))
                await ws.send("1")
                print("Mock pulse sent")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="localhost")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--pin", type=int, default=17)
    args = parser.parse_args()
    asyncio.run(run(args.host, args.port, args.pin))
```

**Step 2: Mac上でモック動作確認（バックエンド起動中に）**

```bash
# 別ターミナルで（バックエンド起動済みの状態で）
cd raspi
python sensor.py --host localhost --port 8000
# 期待: "Mock pulse sent" が表示されバックエンドログに反応が出る
```

**Step 3: コミット**

```bash
git add raspi/sensor.py
git commit -m "feat: add Raspberry Pi sensor script with GPIO + mock fallback"
```

---

## Task 6: Dockerスキャフォールド（フロントエンド）

**Files:**
- Create: `frontend/Dockerfile`
- Create: `docker-compose.yml`
- Modify: `frontend/vite.config.ts`

**Step 1: Dockerfileを書く**

```dockerfile
# frontend/Dockerfile
FROM node:20-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 5173

CMD ["npm", "run", "dev", "--", "--host", "0.0.0.0"]
```

**Step 2: docker-compose.ymlを書く**

```yaml
# docker-compose.yml (リポジトリルート)
services:
  frontend:
    build:
      context: ./frontend
    ports:
      - "5173:5173"
    volumes:
      - ./frontend/src:/app/src        # ホットリロード: srcを直接マウント
      - ./frontend/public:/app/public
      - ./frontend/index.html:/app/index.html
    environment:
      - VITE_BACKEND_WS_URL=ws://host.docker.internal:8000/ws/frontend
    extra_hosts:
      - "host.docker.internal:host-gateway"
```

**Step 3: vite.config.tsにHMR設定を追加**

```typescript
// frontend/vite.config.ts
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    watch: {
      usePolling: true,  // Docker内でのホットリロードに必須
    },
  },
})
```

**Step 4: 動作確認**

```bash
docker compose up --build
```

ブラウザで `http://localhost:5173` を開く。
Viteのデフォルト画面が表示されればOK。

`frontend/src/App.tsx` を編集して保存 → ブラウザが自動リロードされることを確認（ホットリロード確認）

**Step 5: コミット**

```bash
git add frontend/Dockerfile docker-compose.yml frontend/vite.config.ts
git commit -m "feat: add Docker setup with hot reload for frontend"
```

---

## Task 7: フロントエンド骨格（初心者引き渡し用）

**Files:**
- Create: `frontend/src/hooks/useBackendWS.ts`
- Create: `frontend/src/components/KirbyMock.tsx`
- Create: `frontend/src/components/VibrationEffect.tsx`
- Create: `frontend/src/pages/TitlePage.tsx`
- Create: `frontend/src/pages/RulesPage.tsx`
- Create: `frontend/src/pages/SessionPage.tsx`
- Create: `frontend/src/pages/EndPage.tsx`
- Modify: `frontend/src/App.tsx`

**Step 1: WebSocketフックを書く（あなたが死守する部分）**

```typescript
// frontend/src/hooks/useBackendWS.ts
import { useEffect, useRef, useState } from 'react'

export interface BackendMessage {
  type: 'agitation_update' | 'ai_text'
  level?: number
  trend?: 'rising' | 'falling' | 'stable'
  text?: string
}

export function useBackendWS() {
  const [agitationLevel, setAgitationLevel] = useState(0)
  const [agitationTrend, setAgitationTrend] = useState<string>('stable')
  const [aiText, setAiText] = useState('')
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const url = import.meta.env.VITE_BACKEND_WS_URL ?? 'ws://localhost:8000/ws/frontend'
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)

    ws.onmessage = (event) => {
      try {
        const msg: BackendMessage = JSON.parse(event.data)
        if (msg.type === 'agitation_update') {
          setAgitationLevel(msg.level ?? 0)
          setAgitationTrend(msg.trend ?? 'stable')
        } else if (msg.type === 'ai_text') {
          setAiText((prev) => prev + msg.text)
        }
      } catch {
        // ignore parse errors
      }
    }

    return () => ws.close()
  }, [])

  return { agitationLevel, agitationTrend, aiText, connected }
}
```

**Step 2: KirbyMockコンポーネントを書く**

```typescript
// frontend/src/components/KirbyMock.tsx
// 本番ではpropのimageUrlを渡すと画像に差し替えられる

interface Props {
  isTalking: boolean
  imageUrl?: string  // 本番画像があれば渡す
}

export function KirbyMock({ isTalking, imageUrl }: Props) {
  if (imageUrl) {
    return (
      <img
        src={imageUrl}
        alt="ぱむぱむ"
        className={`w-48 h-48 object-contain ${isTalking ? 'animate-bounce' : ''}`}
      />
    )
  }

  // モック: CSS丸 + 口アニメ
  return (
    <div className="relative w-48 h-48">
      <div className="w-full h-full rounded-full bg-pink-300 flex items-center justify-center">
        <div className="relative">
          {/* 目 */}
          <div className="flex gap-4 mb-2">
            <div className="w-3 h-3 rounded-full bg-black" />
            <div className="w-3 h-3 rounded-full bg-black" />
          </div>
          {/* 口: 喋ってるときは大きく開く */}
          <div
            className={`mx-auto bg-red-500 rounded-full transition-all duration-100 ${
              isTalking ? 'w-8 h-6' : 'w-6 h-2'
            }`}
          />
        </div>
      </div>
    </div>
  )
}
```

**Step 3: VibrationEffectコンポーネントを書く（初心者が編集する部分）**

```typescript
// frontend/src/components/VibrationEffect.tsx
//
// ============================================================
// 🎨 ここを自由に編集してください！
//
// agitationLevel: 0〜100 の数値です
//   0   = 平静（普通の状態）
//   50  = 少し動揺
//   100 = 最大動揺（占いがバチバチに当たっている！）
//
// やってみること例:
//   - 画面全体を揺らす（CSS shake アニメーション）
//   - 背景色を変える（赤く染まるなど）
//   - テキストをぼかす
// ============================================================

interface Props {
  agitationLevel: number  // 0〜100
  children: React.ReactNode
}

export function VibrationEffect({ agitationLevel, children }: Props) {
  // TODO: agitationLevelに応じてエフェクトを変える
  // 例: レベルが50以上で画面が揺れる
  const isAgitated = agitationLevel > 50

  return (
    <div
      className={isAgitated ? 'animate-pulse' : ''}
      style={{
        // ヒント: agitationLevelを使って動的にスタイルを変えられます
        // 例: backgroundColor: `rgba(255, 0, 0, ${agitationLevel / 200})`
      }}
    >
      {children}
    </div>
  )
}
```

**Step 4: 各ページを書く**

```typescript
// frontend/src/pages/TitlePage.tsx
interface Props { onStart: () => void }
export function TitlePage({ onStart }: Props) {
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-900 text-white">
      <h1 className="text-4xl font-bold mb-2">ぱむぱむ</h1>
      <p className="text-gray-400 mb-12">〜 AIよ手相よい 〜</p>
      <div className="w-32 h-32 rounded-full bg-gray-700 mb-12" />
      <button
        onClick={onStart}
        className="px-8 py-3 bg-white text-gray-900 rounded font-bold hover:bg-gray-200"
      >
        スタート
      </button>
    </div>
  )
}
```

```typescript
// frontend/src/pages/RulesPage.tsx
import { useEffect, useState } from 'react'
interface Props { onReady: () => void }
export function RulesPage({ onReady }: Props) {
  const [countdown, setCountdown] = useState(30)
  useEffect(() => {
    if (countdown <= 0) { onReady(); return }
    const t = setTimeout(() => setCountdown(c => c - 1), 1000)
    return () => clearTimeout(t)
  }, [countdown, onReady])
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-900 text-white">
      <h2 className="text-2xl mb-8">ルール説明</h2>
      <div className="flex gap-8 mb-8">
        {['手を乗せる', '深呼吸', '落ち着いたら\n自分でスタート'].map((step, i) => (
          <div key={i} className="flex flex-col items-center">
            <div className="w-16 h-16 bg-gray-700 rounded mb-2" />
            <p className="text-sm text-center whitespace-pre">{step}</p>
          </div>
        ))}
      </div>
      <p className="text-gray-400">開始まで {countdown} 秒</p>
    </div>
  )
}
```

```typescript
// frontend/src/pages/SessionPage.tsx
import { KirbyMock } from '../components/KirbyMock'
interface Props {
  agitationLevel: number
  aiText: string
  onEnd: () => void
}
export function SessionPage({ agitationLevel, aiText, onEnd }: Props) {
  const [timeLeft, setTimeLeft] = useState(120)
  useEffect(() => {
    if (timeLeft <= 0) { onEnd(); return }
    const t = setTimeout(() => setTimeLeft(s => s - 1), 1000)
    return () => clearTimeout(t)
  }, [timeLeft, onEnd])
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-800 text-white">
      <div className="absolute top-4 right-4 text-gray-400">残り {timeLeft}s</div>
      <KirbyMock isTalking={aiText.length > 0} />
      <p className="mt-8 max-w-md text-center">{aiText}</p>
    </div>
  )
}
```

```typescript
// frontend/src/pages/EndPage.tsx
interface Props { onBack: () => void }
export function EndPage({ onBack }: Props) {
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-900 text-white">
      <div className="w-48 h-48 rounded-full bg-gray-700 flex flex-col items-center justify-center">
        <p className="mb-4">終了しました</p>
        <button onClick={onBack} className="px-4 py-2 bg-white text-gray-900 rounded">
          戻る
        </button>
      </div>
    </div>
  )
}
```

**Step 5: App.tsxで画面遷移を繋ぐ**

```typescript
// frontend/src/App.tsx
import { useState } from 'react'
import { useBackendWS } from './hooks/useBackendWS'
import { VibrationEffect } from './components/VibrationEffect'
import { TitlePage } from './pages/TitlePage'
import { RulesPage } from './pages/RulesPage'
import { SessionPage } from './pages/SessionPage'
import { EndPage } from './pages/EndPage'

type Page = 'title' | 'rules' | 'session' | 'end'

export default function App() {
  const [page, setPage] = useState<Page>('title')
  const { agitationLevel, agitationTrend, aiText, connected } = useBackendWS()

  return (
    <VibrationEffect agitationLevel={agitationLevel}>
      {!connected && (
        <div className="fixed top-2 left-2 text-xs text-yellow-400 z-50">
          ⚠ Backend未接続
        </div>
      )}
      {page === 'title' && <TitlePage onStart={() => setPage('rules')} />}
      {page === 'rules' && <RulesPage onReady={() => setPage('session')} />}
      {page === 'session' && (
        <SessionPage
          agitationLevel={agitationLevel}
          aiText={aiText}
          onEnd={() => setPage('end')}
        />
      )}
      {page === 'end' && <EndPage onBack={() => setPage('title')} />}
    </VibrationEffect>
  )
}
```

**Step 6: 動作確認**

```bash
# バックエンド起動（MOCK_MODE=true）
cd backend && MOCK_MODE=true uv run uvicorn src.main:app --reload --port 8000

# フロントエンド起動
docker compose up
```

`http://localhost:5173` で4画面の遷移が動くことを確認。
バックエンド接続時に ⚠ 表示が消えることを確認。

**Step 7: コミット**

```bash
git add frontend/src/
git commit -m "feat: add React frontend scaffold with all pages and WebSocket hook"
```

---

## 完了チェックリスト

- [ ] `uv run python backend/src/gemini_poc.py` でGemini Live APIが応答する
- [ ] `uv run pytest backend/tests/` が全PASS
- [ ] `MOCK_MODE=true uv run uvicorn src.main:app` でバックエンドが起動する
- [ ] `docker compose up` でフロントが `http://localhost:5173` に表示される
- [ ] フロントのコード変更がホットリロードされる
- [ ] `raspi/sensor.py` をMac上でモック実行するとフロントのAgitationLevelが変動する
- [ ] `VibrationEffect.tsx` に「ここを編集しろ」コメントが仕込まれている
