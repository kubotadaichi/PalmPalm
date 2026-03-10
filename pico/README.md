# Pico セットアップガイド

## 必要なもの
- Raspberry Pi Pico
- 振動センサーモジュール（デジタル出力）
- USB ケーブル（Pico → Mac）

## Pico 側のセットアップ

1. [MicroPython をフラッシュ](https://micropython.org/download/RPI_PICO/)
2. Thonny IDE または mpremote でファイルを転送:
   ```bash
   pip install mpremote
   mpremote connect auto cp pico/main.py :main.py
   ```
3. 配線:
   - センサー OUT → GP17
   - センサー VCC → 3V3(OUT)
   - センサー GND → GND

## Mac 側のブリッジ起動

```bash
cd pico
pip install -r requirements.txt

# Backend を先に起動しておく
cd ../backend && MOCK_MODE=false uv run uvicorn src.main:app --port 8000 &

# ブリッジを起動（Picoを自動検出）
cd ../pico && python serial_bridge.py
```

## ポートの手動確認

```bash
ls /dev/tty.usbmodem*
# または
python -c "import serial.tools.list_ports; [print(p) for p in serial.tools.list_ports.comports()]"
```
