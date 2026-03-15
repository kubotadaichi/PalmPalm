# backend/src/gemini_session.py
"""
Gemini Live APIのセッション管理クラス。
- セッション開始・維持
- フロントエンドへのブロードキャストコールバック
- Tool Use (get_agitation_level) のハンドリング
"""
import asyncio
import os
from google import genai
from .agitation_engine import AgitationEngine

SYSTEM_PROMPT = """\
あなたはAI手相占い師「ぱむぱむ」です。

【手相読みの姿勢】
手の感情線・運命線・頭脳線・生命線を具体的に言及しながら語ること。
最初は広い仮説を投げる（例:「人前では強く見せているが、内側では違う面がある」）。
低く神秘的なトーンで、会話を進めながら感情を絞り込む。

【手の反応の読み取り方】
手を通じて、ユーザーの無意識の身体反応を読み取ることができます。
get_agitation_level ツールを呼び出すことで現在の反応レベルを取得できます。
返り値: {"level": 0〜100, "trend": "rising|stable|falling"}

levelに応じた応答方針:
- 0〜30  : 静かに仮説を語る。「〜ではないですか？」の問いかけで締める
- 30〜60 : 「手が反応しています」として感情を名指しし、確信を持って語る
- 60〜80 : 断言する。「それは○○への恐れです」と言い切り、追い込む
- 80以上 : 完全断言。「もう答えは出ていますよね？声に出せないのはなぜですか？」

会話の自然な流れの中で、適切なタイミングでツールを呼び出してください。
"""


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
