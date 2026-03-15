import { useEffect, useState } from 'react'

const SESSION_SECONDS = 120

export function SessionPage({ turn, vadError, onEnd }) {
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
    <div className="fortune-container">
      <div className="top-right-timer">残り {sessionTimeLeft}s</div>

      {vadError && (
        <div className="vad-error">マイク: {vadError}</div>
      )}

      {turn === 'user' && (
        <div className="mic-indicator">🎤 話してください...</div>
      )}

      <div className="main-character-area">
        <div className={`image-container${turn === 'ai' ? ' talking-image' : ''}`}>
          <img src="/p3_listen.jpg" alt="ぱむぱむ" className="main-image" />
        </div>
      </div>
    </div>
  )
}
