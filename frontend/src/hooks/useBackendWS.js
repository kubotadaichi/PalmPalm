import { useCallback, useEffect, useRef, useState } from 'react'

export function useBackendWS() {
  const [agitationLevel, setAgitationLevel] = useState(0)
  const [agitationTrend, setAgitationTrend] = useState('stable')
  const [aiText, setAiText] = useState('')
  const [aiAudioUrl, setAiAudioUrl] = useState(null)
  const [connected, setConnected] = useState(false)
  const [turn, setTurn] = useState('ai')
  const [aiTurnEnded, setAiTurnEnded] = useState(false)
  const wsRef = useRef(null)

  useEffect(() => {
    const wsUrl = import.meta.env.VITE_BACKEND_WS_URL ?? 'ws://localhost:8000/ws/frontend'
    const httpBase = wsUrl.replace(/^ws/, 'http').replace(/\/ws\/.*$/, '')

    const ws = new WebSocket(wsUrl)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)

    ws.onmessage = (event) => {
      try {
        const msg = JSON.parse(event.data)
        if (msg.type === 'agitation_update') {
          setAgitationLevel(msg.level ?? 0)
          setAgitationTrend(msg.trend ?? 'stable')
        } else if (msg.type === 'ai_text') {
          setAiText((prev) => prev + msg.text)
        } else if (msg.type === 'ai_audio') {
          setAiAudioUrl(httpBase + msg.url)
        } else if (msg.type === 'ai_turn_end') {
          setAiTurnEnded(true)
          setAiText('')
        }
      } catch {
        // ignore parse errors
      }
    }

    return () => {
      ws.close()
    }
  }, [])

  const setTurnToAi = useCallback(() => setTurn('ai'), [])
  const startUserTurn = useCallback(() => {
    setTurn('user')
    setAiTurnEnded(false)
  }, [])

  return { agitationLevel, agitationTrend, aiText, aiAudioUrl, connected, turn, aiTurnEnded, setTurnToAi, startUserTurn }
}
