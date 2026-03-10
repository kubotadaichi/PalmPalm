import { useEffect, useState } from 'react'
import { KirbyMock } from '../components/KirbyMock'

interface Props {
  agitationLevel: number
  aiText: string
  onEnd: () => void
}

const SESSION_SECONDS = 120

export function SessionPage({ agitationLevel, aiText, onEnd }: Props) {
  const [timeLeft, setTimeLeft] = useState(SESSION_SECONDS)
  const isTalking = aiText.length > 0

  useEffect(() => {
    if (timeLeft <= 0) {
      onEnd()
      return
    }
    const t = setTimeout(() => setTimeLeft((s) => s - 1), 1000)
    return () => clearTimeout(t)
  }, [timeLeft, onEnd])

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-800 text-white relative">
      <div className="absolute top-4 right-4 text-gray-400 text-sm bg-gray-900 px-3 py-1 rounded">
        残り {timeLeft}s
      </div>
      <div className="absolute top-4 left-4 text-xs text-gray-500">
        動揺率: {agitationLevel}%
      </div>
      <KirbyMock isTalking={isTalking} />
      <div className="mt-8 max-w-md text-center min-h-[4rem] px-4">
        <p className="text-lg leading-relaxed">{aiText}</p>
      </div>
    </div>
  )
}
