# backend/src/gemini_poc.py
"""
Gemini Live API PoC スクリプト。
実行方法: cd backend && uv run python src/gemini_poc.py

事前準備: backend/.env に GEMINI_API_KEY=xxx を設定
"""
import asyncio
import os
from google import genai
from dotenv import load_dotenv

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))

SYSTEM_PROMPT = """あなたはAI手相占い師「ぱむぱむ」です。
神秘的かつ毒舌なキャラクターで、ユーザーの手相を占います。
ユーザーの揺れ率は占いの的確度への反応です。
levelが高いほど当たっている。trend: risingなら確信を持って追い込め。
[システム通知]が来たら必ずリアクションしろ。"""


async def run_poc():
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

    print("Gemini Live APIに接続中...")
    async with client.aio.live.connect(
        model="gemini-2.0-flash-live-001",
        config=config
    ) as session:
        print("✅ セッション確立成功\n")

        # --- テスト1: テキスト送信 → 応答受信 ---
        print("=== テスト1: 手相占いリクエスト ===")
        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": "私の手相を占ってください。生命線が短いです。"}]},
            turn_complete=True
        )
        async for response in session.receive():
            if hasattr(response, 'tool_call') and response.tool_call:
                # Tool Useが呼ばれた場合はモック値で応答
                for fc in response.tool_call.function_calls:
                    print(f"  [Tool Call] {fc.name}() が呼ばれました")
                    await session.send_tool_response(
                        function_responses=[{
                            "name": fc.name,
                            "id": fc.id,
                            "response": {"result": {"level": 30, "trend": "stable"}}
                        }]
                    )
            if hasattr(response, 'text') and response.text:
                print(f"AI: {response.text}", end="", flush=True)
            if (hasattr(response, 'server_content') and
                    response.server_content and
                    response.server_content.turn_complete):
                break
        print("\n")

        # --- テスト2: 動揺急上昇のPush割り込み ---
        print("=== テスト2: 動揺急上昇 Push割り込み ===")
        await session.send_client_content(
            turns={"role": "user", "parts": [{"text": "[システム通知] ユーザーが75%動揺しています（rising）。追い込め。"}]},
            turn_complete=True
        )
        async for response in session.receive():
            if hasattr(response, 'tool_call') and response.tool_call:
                for fc in response.tool_call.function_calls:
                    print(f"  [Tool Call] {fc.name}() が呼ばれました")
                    await session.send_tool_response(
                        function_responses=[{
                            "name": fc.name,
                            "id": fc.id,
                            "response": {"result": {"level": 75, "trend": "rising"}}
                        }]
                    )
            if hasattr(response, 'text') and response.text:
                print(f"AI: {response.text}", end="", flush=True)
            if (hasattr(response, 'server_content') and
                    response.server_content and
                    response.server_content.turn_complete):
                break
        print("\n")

        print("✅ PoC完了")


if __name__ == "__main__":
    asyncio.run(run_poc())
