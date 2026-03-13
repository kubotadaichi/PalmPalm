"""
シリアルポートから Pico の振動センサー出力を読み取り、
"Vibration detected!" を検知するたびに POST /pulse を叩く。

使い方:
    python -m backend.src.serial_reader --port /dev/tty.usbmodem1234
    python -m backend.src.serial_reader --port COM3 --baud 115200
"""

import argparse
import os

import httpx
import serial

VIBRATION_KEYWORD = "Vibration detected!"


def should_record_pulse(line: str) -> bool:
    return VIBRATION_KEYWORD in line


def run(port: str, baud: int, server_url: str) -> None:
    print(f"[serial_reader] Connecting to {port} @ {baud}bps")
    with serial.Serial(port, baud, timeout=1) as ser:
        print("[serial_reader] Connected. Watching for vibrations...")
        while True:
            raw = ser.readline()
            if not raw:
                continue
            line = raw.decode("utf-8", errors="ignore").strip()
            if should_record_pulse(line):
                try:
                    httpx.post(f"{server_url}/pulse", timeout=2.0)
                except Exception as exc:
                    print(f"[serial_reader] POST /pulse failed: {exc}")


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
