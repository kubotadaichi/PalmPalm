import { useEffect, useRef, useState } from 'react'
import { KirbyMock } from '../components/KirbyMock'
import { useVAD } from '../hooks/useVAD'

const SESSION_SECONDS = 120

export function SessionPage({ agitationLevel, aiText, aiAudioUrl, httpBase, onEnd }) {
  const [timeLeft, setTimeLeft] = useState(SESSION_SECONDS)
  const isTalking = aiText.length > 0
  const audioRef = useRef(null)
  const { isSpeaking, vadError } = useVAD({ httpBase })

  useEffect(() => {
    if (timeLeft <= 0) {
      onEnd()
      return
    }
    const t = setTimeout(() => setTimeLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [timeLeft, onEnd])

  useEffect(() => {
    if (!aiAudioUrl) return
    if (audioRef.current) {
      audioRef.current.pause()
    }
    const audio = new Audio(aiAudioUrl)
    audioRef.current = audio
    audio.play().catch(() => {
      // autoplay policy に引っかかった場合は無視
    })
  }, [aiAudioUrl])

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-800 text-white relative">
      <div className="absolute top-4 right-4 text-gray-400 text-sm bg-gray-900 px-3 py-1 rounded">
        残り {timeLeft}s
      </div>
      <div className="absolute top-4 left-4 text-xs text-gray-500">
        動揺率: {agitationLevel}%
      </div>
      {vadError && (
        <div className="absolute bottom-16 left-1/2 -translate-x-1/2 text-xs text-yellow-400 bg-black/60 px-3 py-1 rounded max-w-xs text-center">
          VAD: {vadError}
        </div>
      )}
      {isSpeaking && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-red-400 bg-black/60 px-3 py-1 rounded">
          🎤 録音中...
        </div>
      )}
      <KirbyMock isTalking={isTalking} />
      <div className="mt-8 max-w-md text-center min-h-[4rem] px-4">
        <p className="text-lg leading-relaxed">{aiText}</p>
      </div>
    </div>
  )
}
