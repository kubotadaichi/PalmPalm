import { useEffect, useRef, useState } from 'react'
import { KirbyMock } from '../components/KirbyMock'
import { useVAD } from '../hooks/useVAD'

const SESSION_SECONDS = 120

export function SessionPage({ aiText, aiAudioQueue, audioPlayedRef, turn, aiTurnEnded, startUserTurn, setTurnToAi, sendAudio, onEnd }) {
  const [timeLeft, setTimeLeft] = useState(SESSION_SECONDS)
  const [isAudioPlaying, setIsAudioPlaying] = useState(false)
  const isTalking = aiText.length > 0
  const audioRef = useRef(null)

  const { vadError, isSpeaking, timeLeft: recordingTimeLeft } = useVAD({
    maxSeconds: 10,
    turn,
    onAudioReady: sendAudio,
  })

  // タイマー
  useEffect(() => {
    if (timeLeft <= 0) { onEnd(); return }
    const t = setTimeout(() => setTimeLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [timeLeft, onEnd])

  // audio キュー再生
  useEffect(() => {
    if (isAudioPlaying) return
    const url = aiAudioQueue[audioPlayedRef.current]
    if (!url) return
    audioPlayedRef.current += 1
    const audio = new Audio(url)
    audioRef.current = audio
    setIsAudioPlaying(true)
    audio.onended = () => setIsAudioPlaying(false)
    audio.onerror = () => setIsAudioPlaying(false)
    audio.play().catch(() => setIsAudioPlaying(false))
  }, [aiAudioQueue, isAudioPlaying, audioPlayedRef])

  // AI ターン終了 + 音声再生完了（または音声なし）→ ユーザーターンへ
  useEffect(() => {
    if (!aiTurnEnded) return
    const allPlayed = aiAudioQueue.length === 0 ||
      (audioPlayedRef.current >= aiAudioQueue.length && !isAudioPlaying)
    if (allPlayed) startUserTurn()
  }, [aiTurnEnded, isAudioPlaying, aiAudioQueue, audioPlayedRef, startUserTurn])

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-800 text-white relative">
      <div className="absolute top-4 right-4 text-gray-400 text-sm bg-gray-900 px-3 py-1 rounded">
        残り {timeLeft}s
      </div>
      {vadError && (
        <div className="absolute bottom-16 left-1/2 -translate-x-1/2 text-xs text-yellow-400 bg-black/60 px-3 py-1 rounded max-w-xs text-center">
          マイク: {vadError}
        </div>
      )}
      {turn === 'user' && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-red-400 bg-black/60 px-3 py-1 rounded">
          🎤 話してください... 残り {recordingTimeLeft}s
        </div>
      )}
      <KirbyMock isTalking={isTalking} />
      <div className="mt-8 max-w-md text-center min-h-[4rem] px-4">
        <p className="text-lg leading-relaxed">{aiText}</p>
      </div>
    </div>
  )
}
