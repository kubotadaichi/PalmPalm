/**
 * AudioWorklet プロセッサ：マイク入力を 16kHz mono int16 PCM に変換して送信する。
 * AudioContext sampleRate=16000 で使うこと。
 */
class PcmProcessor extends AudioWorkletProcessor {
  process(inputs) {
    const input = inputs[0]
    if (!input || !input[0]) return true

    const float32 = input[0]
    const int16 = new Int16Array(float32.length)
    for (let i = 0; i < float32.length; i++) {
      int16[i] = Math.max(-32768, Math.min(32767, float32[i] * 32768))
    }

    this.port.postMessage(int16.buffer, [int16.buffer])
    return true
  }
}

registerProcessor('pcm-processor', PcmProcessor)
