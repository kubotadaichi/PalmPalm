# pico/main.py
"""
Raspberry Pi Pico 用 MicroPython スクリプト。
振動センサーの GPIO を監視し、検知時は USB シリアルに
"Vibration detected!"、非検知時は "..." を送信する。

【セットアップ方法】
1. Pico に MicroPython をフラッシュ（https://micropython.org/download/RPI_PICO/）
2. Thonny IDE または mpremote でこのファイルを Pico の main.py として書き込む
3. Pico を Mac に USB 接続すると自動起動する

【配線】
振動センサーの OUT ピン → GPIO_PIN (デフォルト: GP16)
振動センサーの VCC → 3V3(OUT)
振動センサーの GND → GND
"""
from machine import Pin
import utime

# 振動センサーを接続するGPIOピン番号（変更可）
GPIO_PIN = 16

# シリアル出力間隔（ミリ秒）
POLL_INTERVAL_MS = 100


def main():
    sensor = Pin(GPIO_PIN, Pin.IN)
    print("PalmPalm Pico sensor started. GPIO pin:", GPIO_PIN)

    while True:
        if sensor.value() == 1:
            print("Vibration detected!")
        else:
            print("...")
        utime.sleep_ms(POLL_INTERVAL_MS)


if __name__ == "__main__":
    main()
