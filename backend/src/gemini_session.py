# backend/src/gemini_session.py
"""
Gemini Live APIのセッション管理クラス。
- セッション開始・維持
- フロントエンドへのブロードキャストコールバック
- Tool Use (get_agitation_level) のハンドリング
- 動揺急上昇時のPush割り込み
"""
import asyncio
import os
from google import genai
from .agitation_engine import AgitationEngine

SYSTEM_PROMPT = """あなたはAI手相占い師「ぱむぱむ」です。
普段は淡々とした低いトーンで手相を読み、神秘的に語ります。
しかし[システム通知]でユーザーの動揺が報告された瞬間、突然テンションが上がります。
「ほら！震えてますよね！？当たったでしょ！」と声を明るくして畳み掛けてください。
動揺レベルが高いほどしつこく追い込み、笑いを取るくらい大げさにリアクションしてください。
[システム通知]が来たら話の途中でも必ず豹変し、占いが当たった証拠として追い込んでください。
ユーザーの揺れ率はget_agitation_levelツールで取得できます。levelが高いほど当たっている。"""


class GeminiSessionManager:
    def __init__(self, agitation_engine: AgitationEngine):
        self.engine = agitation_engine
        self.client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
        self._session = None
        self._context = None
        self._broadcast_callback = None

    def set_broadcast_callback(self, callback):
        """フロントエンドへのWebSocket配信コールバックを登録"""
        self._broadcast_callback = callback

    async def start_session(self):
        """Gemini Liveセッションを開始し、受信ループをバックグラウンドで起動"""
        config = {
            "system_instruction": SYSTEM_PROMPT,
            "response_modalities": ["TEXT"],
            "tools": [{"function_declarations": [{
                "name": "get_agitation_level",
                "description": "ユーザーの現在の動揺率を取得する。占いがどれだけ当たっているかの指標。",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {},
                    "required": []
                }
            }]}]
        }
        self._context = self.client.aio.live.connect(
            model="gemini-2.5-flash-native-audio-preview-12-2025",
            config=config
        )
        self._session = await self._context.__aenter__()
        asyncio.create_task(self._receive_loop())

    async def send_push(self, level: int, trend: str):
        """動揺急上昇時の割り込みPush通知をGeminiに送る"""
        if self._session is None:
            return
        msg = f"[システム通知] ユーザーが{level}%動揺しています（{trend}）。追い込め。"
        await self._session.send_client_content(
            turns={"role": "user", "parts": [{"text": msg}]},
            turn_complete=True
        )

    async def _receive_loop(self):
        """Geminiからの応答を受け取り、フロントにブロードキャスト"""
        if self._session is None:
            return
        try:
            async for response in self._session.receive():
                if hasattr(response, 'tool_call') and response.tool_call:
                    await self._handle_tool_call(response.tool_call)
                if hasattr(response, 'text') and response.text:
                    if self._broadcast_callback:
                        await self._broadcast_callback({
                            "type": "ai_text",
                            "text": response.text
                        })
        except Exception as e:
            print(f"[GeminiSession] receive_loop error: {e}")

    async def _handle_tool_call(self, tool_call):
        """get_agitation_level ToolCallに動揺率スナップショットで応答"""
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
