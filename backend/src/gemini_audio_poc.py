"""
Gemini Live API 音声PoC（振動スパイク割り込みテスト付き）

操作:
  話しかける  → 手相占いが返答
  Enterキー   → 振動スパイクをシミュレート（AIが返答中でも割り込む）
  Ctrl+C      → 終了
"""
import asyncio
import sys
import pyaudio
from google import genai
from google.genai.types import LiveConnectConfig
from dotenv import load_dotenv
import os

load_dotenv()

FORMAT = pyaudio.paInt16
CHANNELS = 1
SEND_SAMPLE_RATE = 16000
RECEIVE_SAMPLE_RATE = 24000
CHUNK_SIZE = 1024

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
MODEL = "gemini-2.5-flash-native-audio-preview-12-2025"

SPIKE_MESSAGE = "[システム通知] ユーザーが激しく動揺しています（動揺率85%、急上昇）。今すぐ返答を中断して、占いが当たったと畳み掛けろ。"


async def run():
    pya = pyaudio.PyAudio()

    config = LiveConnectConfig(
        response_modalities=["AUDIO"],
        system_instruction="""あなたはAI手相占い師「ぱむぱむ」です。
普段は淡々とした低いトーンで手相を読み、神秘的に語ります。
しかし[システム通知]でユーザーの動揺が報告された瞬間、突然テンションが上がります。
「ほら！震えてますよね！？当たったでしょ！」と声を明るくして畳み掛けてください。
動揺レベルが高いほどしつこく追い込み、笑いを取るくらい大げさにリアクションしてください。
[システム通知]が来たら話の途中でも必ず豹変し、占いが当たった証拠として追い込んでください。""",
        input_audio_transcription={},
        output_audio_transcription={},
    )

    async with client.aio.live.connect(model=MODEL, config=config) as session:
        print("✅ 接続成功")
        print("  話しかける  → 占いが返答")
        print("  Enterキー   → 振動スパイクをシミュレート")
        print("  Ctrl+C      → 終了\n")

        out_stream = pya.open(format=FORMAT, channels=CHANNELS,
                              rate=RECEIVE_SAMPLE_RATE, output=True)

        model_responding = False

        async def send_audio():
            nonlocal model_responding
            in_stream = pya.open(format=FORMAT, channels=CHANNELS,
                                 rate=SEND_SAMPLE_RATE, input=True,
                                 frames_per_buffer=CHUNK_SIZE)
            while True:
                data = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: in_stream.read(CHUNK_SIZE, exception_on_overflow=False)
                )
                if not model_responding:
                    await session.send_realtime_input(
                        audio={"data": data, "mime_type": "audio/pcm;rate=16000"}
                    )

        async def receive_audio():
            nonlocal model_responding
            async for response in session.receive():
                if response.data:
                    if not model_responding:
                        print("\n[AI返答開始]")
                        model_responding = True
                    out_stream.write(response.data)

                if hasattr(response, 'server_content') and response.server_content:
                    sc = response.server_content
                    if getattr(sc, 'input_transcription', None) and sc.input_transcription.text.strip():
                        print(f"[認識] {sc.input_transcription.text}")
                    if getattr(sc, 'output_transcription', None) and sc.output_transcription.text.strip():
                        print(f"[AI] {sc.output_transcription.text}", end="", flush=True)
                    if sc.turn_complete:
                        print("\n[AI返答終了]\n")
                        model_responding = False

        async def wait_for_spike():
            """Enterキーで振動スパイクをシミュレートする（非同期stdin）"""
            nonlocal model_responding
            loop = asyncio.get_event_loop()
            reader = asyncio.StreamReader()
            protocol = asyncio.StreamReaderProtocol(reader)
            await loop.connect_read_pipe(lambda: protocol, sys.stdin)
            while True:
                await reader.readline()  # Enterを待つ（ノンブロッキング）
                print("\n🔴 [振動スパイク発生！] リアルタイム割り込み送信...")
                await session.send_realtime_input(text=SPIKE_MESSAGE)

        await asyncio.gather(send_audio(), receive_audio(), wait_for_spike())


asyncio.run(run())
