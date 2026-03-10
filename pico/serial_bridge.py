# pico/serial_bridge.py
"""
Mac上で動くシリアル→WebSocketブリッジ。
Pico から USB シリアルで受け取った "1" を Backend WebSocket に転送する。

【使い方】
# 依存インストール
pip install pyserial websockets

# 実行（ポートは自動検出、またはオプションで指定）
python serial_bridge.py
python serial_bridge.py --port /dev/tty.usbmodem101 --ws ws://localhost:8000/ws/sensor

【Picoのシリアルポート確認方法】
ls /dev/tty.usbmodem* または ls /dev/tty.SLAB*
"""
import asyncio
import argparse
import glob
import sys

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("pyserial not installed. Run: pip install pyserial")
    sys.exit(1)

try:
    import websockets
except ImportError:
    print("websockets not installed. Run: pip install websockets")
    sys.exit(1)


def find_pico_port() -> str | None:
    """接続されているPicoのシリアルポートを自動検出する"""
    # Pico の USB VID:PID は 0x2E8A:0x0005 (MicroPython)
    for port in serial.tools.list_ports.comports():
        if port.vid == 0x2E8A:
            print(f"[Auto-detect] Found Pico at: {port.device}")
            return port.device

    # フォールバック: /dev/tty.usbmodem* を探す
    candidates = glob.glob("/dev/tty.usbmodem*")
    if candidates:
        print(f"[Auto-detect] Found USB serial: {candidates[0]}")
        return candidates[0]

    return None


async def bridge(serial_port: str, ws_url: str, baud: int):
    """シリアルポートを読んでWebSocketに転送するメインループ"""
    print(f"Opening serial port: {serial_port} ({baud} baud)")
    try:
        ser = serial.Serial(serial_port, baud, timeout=0.1)
    except serial.SerialException as e:
        print(f"Failed to open serial port: {e}")
        sys.exit(1)

    print(f"Connecting to backend: {ws_url}")
    try:
        async with websockets.connect(ws_url) as ws:
            print("Connected to backend WebSocket")
            print("Listening for vibration pulses from Pico... (Ctrl+C to stop)")
            pulse_count = 0

            while True:
                # シリアルからデータ読み取り（ノンブロッキング）
                line = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: ser.readline().decode("utf-8", errors="ignore").strip()
                )

                if line == "1":
                    await ws.send("1")
                    pulse_count += 1
                    print(f"[Bridge] Pulse #{pulse_count} forwarded to backend")
                elif line:
                    # デバッグ情報など "1" 以外の行は表示のみ
                    print(f"[Pico] {line}")

    except (ConnectionRefusedError, OSError) as e:
        print(f"WebSocket connection failed: {e}")
        print(f"  Backend ({ws_url}) が起動しているか確認してください")
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n[Bridge] Stopped by user")
    finally:
        ser.close()


def main():
    parser = argparse.ArgumentParser(description="PalmPalm Pico serial bridge")
    parser.add_argument("--port", help="Serial port (auto-detect if omitted)")
    parser.add_argument(
        "--ws",
        default="ws://localhost:8000/ws/sensor",
        help="Backend WebSocket URL (default: ws://localhost:8000/ws/sensor)"
    )
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Baud rate (default: 115200)"
    )
    args = parser.parse_args()

    port = args.port or find_pico_port()
    if not port:
        print("Pico が見つかりません。")
        print("  1. Pico を USB 接続してください")
        print("  2. --port /dev/tty.usbmodemXXXX で手動指定できます")
        sys.exit(1)

    asyncio.run(bridge(port, args.ws, args.baud))


if __name__ == "__main__":
    main()
