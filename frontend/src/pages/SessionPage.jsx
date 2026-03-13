import { useEffect, useState } from 'react'
import { KirbyMock } from '../components/KirbyMock'

const SESSION_SECONDS = 120

export function SessionPage({ turn, aiText, vadError, timeLeft, onEnd }) {
  const [sessionTimeLeft, setSessionTimeLeft] = useState(SESSION_SECONDS)

  useEffect(() => {
    if (sessionTimeLeft <= 0) {
      onEnd()
      return
    }
    const t = setTimeout(() => setSessionTimeLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [sessionTimeLeft, onEnd])

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-800 text-white relative">
      <div className="absolute top-4 right-4 text-gray-400 text-sm bg-gray-900 px-3 py-1 rounded">
        残り {sessionTimeLeft}s
      </div>
      {vadError && (
        <div className="absolute bottom-16 left-1/2 -translate-x-1/2 text-xs text-yellow-400 bg-black/60 px-3 py-1 rounded max-w-xs text-center">
          マイク: {vadError}
        </div>
      )}
      {turn === 'user' && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 text-sm text-red-400 bg-black/60 px-3 py-1 rounded">
          🎤 話してください... 残り {timeLeft}s
        </div>
      )}
      <KirbyMock isTalking={turn === 'ai' && aiText.length > 0} />
      <div className="mt-8 max-w-md text-center min-h-[4rem] px-4">
        <p className="text-lg leading-relaxed">{aiText}</p>
      </div>
    </div>
  )
}
