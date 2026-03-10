# raspi/sensor.py
"""
Raspberry Pi上で動かす振動センサースクリプト。
GPIO監視 → MacのBackendにWebSocketで "1" を送信する。

RPi.GPIOが使えない環境（Mac等）ではモックとして動作する。

使用方法:
  # Raspberry Pi上:
  python sensor.py --host 192.168.x.x --port 8000 --pin 17

  # Macでモックとして:
  python sensor.py --host localhost --port 8000
"""
import asyncio
import argparse
import sys

try:
    import websockets
except ImportError:
    print("websockets not installed. Run: pip install websockets")
    sys.exit(1)

try:
    import RPi.GPIO as GPIO
    REAL_GPIO = True
except ImportError:
    REAL_GPIO = False
    print("[INFO] RPi.GPIO not found - running in mock mode")


async def run(host: str, port: int, pin: int):
    uri = f"ws://{host}:{port}/ws/sensor"
    print(f"Connecting to {uri} ...")

    try:
        async with websockets.connect(uri) as ws:
            print("✅ Connected. Monitoring sensor...")

            if REAL_GPIO:
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(pin, GPIO.IN, pull_up_down=GPIO.PUD_DOWN)
                try:
                    while True:
                        if GPIO.input(pin) == GPIO.HIGH:
                            await ws.send("1")
                            await asyncio.sleep(0.05)  # デバウンス
                        else:
                            await asyncio.sleep(0.01)
                finally:
                    GPIO.cleanup()
            else:
                # モック: ランダム間隔でパルスを送信
                import random
                pulse_count = 0
                while True:
                    interval = random.uniform(0.3, 2.5)
                    await asyncio.sleep(interval)
                    await ws.send("1")
                    pulse_count += 1
                    print(f"[Mock] Pulse #{pulse_count} sent (next in ~{interval:.1f}s)")
    except (ConnectionRefusedError, OSError) as e:
        print(f"❌ Connection failed: {e}")
        print(f"  Backend ({uri}) が起動しているか確認してください")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[INFO] Stopped by user")


def main():
    parser = argparse.ArgumentParser(description="PalmPalm vibration sensor client")
    parser.add_argument("--host", default="localhost", help="Backend host (default: localhost)")
    parser.add_argument("--port", type=int, default=8000, help="Backend port (default: 8000)")
    parser.add_argument("--pin", type=int, default=17, help="GPIO pin number (default: 17, BCM)")
    args = parser.parse_args()

    asyncio.run(run(args.host, args.port, args.pin))


if __name__ == "__main__":
    main()
