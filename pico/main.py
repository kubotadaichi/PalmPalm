# pico/main.py
"""
Raspberry Pi Pico 用 MicroPython スクリプト。
振動センサーのGPIOを監視し、検知したら USBシリアルに "1\n" を送信する。

【セットアップ方法】
1. Pico に MicroPython をフラッシュ（https://micropython.org/download/RPI_PICO/）
2. Thonny IDE または mpremote でこのファイルを Pico の main.py として書き込む
3. Pico を Mac に USB接続すると自動起動する

【配線】
振動センサーの OUT ピン → GPIO_PIN (デフォルト: GP17)
振動センサーの VCC  → 3V3(OUT)
振動センサーの GND  → GND
"""
from machine import Pin
import utime

# 振動センサーを接続するGPIOピン番号（変更可）
GPIO_PIN = 17

# デバウンス時間（ミリ秒）- 連続検知を防ぐ
DEBOUNCE_MS = 50


def main():
    sensor = Pin(GPIO_PIN, Pin.IN, Pin.PULL_DOWN)
    last_trigger_ms = 0
    print("PalmPalm Pico sensor started. GPIO pin:", GPIO_PIN)

    while True:
        if sensor.value() == 1:
            now = utime.ticks_ms()
            if utime.ticks_diff(now, last_trigger_ms) > DEBOUNCE_MS:
                # USBシリアルに "1" を送信（PCが受け取る）
                print("1")
                last_trigger_ms = now
        utime.sleep_ms(10)


if __name__ == "__main__":
    main()
