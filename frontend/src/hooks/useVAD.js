import { useEffect, useState } from 'react'

/**
 * Float32Array (16kHz モノラル PCM) を WAV Blob に変換する
 */
function float32ToWav(samples, sampleRate = 16000) {
  const buffer = new ArrayBuffer(44 + samples.length * 2)
  const view = new DataView(buffer)

  const writeString = (offset, str) => {
    for (let i = 0; i < str.length; i++) {
      view.setUint8(offset + i, str.charCodeAt(i))
    }
  }

  writeString(0, 'RIFF')
  view.setUint32(4, 36 + samples.length * 2, true)
  writeString(8, 'WAVE')
  writeString(12, 'fmt ')
  view.setUint32(16, 16, true)
  view.setUint16(20, 1, true)
  view.setUint16(22, 1, true)
  view.setUint32(24, sampleRate, true)
  view.setUint32(28, sampleRate * 2, true)
  view.setUint16(32, 2, true)
  view.setUint16(34, 16, true)
  writeString(36, 'data')
  view.setUint32(40, samples.length * 2, true)

  let offset = 44
  for (let i = 0; i < samples.length; i++) {
    const s = Math.max(-1, Math.min(1, samples[i]))
    view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7fff, true)
    offset += 2
  }

  return new Blob([buffer], { type: 'audio/wav' })
}

/**
 * マイク音声をVADで検知し、発話終了時にバックエンドへPOSTするフック
 * @param {string} httpBase - バックエンドのHTTPベースURL (例: "http://localhost:8000")
 */
export function useVAD({ httpBase }) {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [vadError, setVadError] = useState(null)

  useEffect(() => {
    let vad = null

    import('@ricky0123/vad-web')
      .then(({ MicVAD }) =>
        MicVAD.new({
          workersOptions: { url: '/vad.worklet.bundle.min.js' },
          modelURL: '/silero_vad_v5.onnx',
          onSpeechStart: () => setIsSpeaking(true),
          onSpeechEnd: async (audio) => {
            setIsSpeaking(false)
            const wav = float32ToWav(audio)
            try {
              await fetch(`${httpBase}/api/audio`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/octet-stream' },
                body: wav,
              })
            } catch {
              // ネットワークエラーは無視
            }
          },
        })
      )
      .then((v) => {
        vad = v
        vad.start()
      })
      .catch((e) => {
        console.error('[VAD] init error:', e)
        setVadError(e?.message ?? String(e))
      })

    return () => {
      vad?.destroy()
    }
  }, [httpBase])

  return { isSpeaking, vadError }
}
