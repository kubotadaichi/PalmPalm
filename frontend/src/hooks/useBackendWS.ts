// frontend/src/hooks/useBackendWS.ts
import { useEffect, useRef, useState } from 'react'

export interface BackendMessage {
  type: 'agitation_update' | 'ai_text'
  level?: number
  trend?: 'rising' | 'falling' | 'stable'
  text?: string
}

export function useBackendWS() {
  const [agitationLevel, setAgitationLevel] = useState(0)
  const [agitationTrend, setAgitationTrend] = useState<'rising' | 'falling' | 'stable'>('stable')
  const [aiText, setAiText] = useState('')
  const [connected, setConnected] = useState(false)
  const wsRef = useRef<WebSocket | null>(null)

  useEffect(() => {
    const url = import.meta.env.VITE_BACKEND_WS_URL ?? 'ws://localhost:8000/ws/frontend'
    const ws = new WebSocket(url)
    wsRef.current = ws

    ws.onopen = () => setConnected(true)
    ws.onclose = () => setConnected(false)
    ws.onerror = () => setConnected(false)

    ws.onmessage = (event) => {
      try {
        const msg: BackendMessage = JSON.parse(event.data)
        if (msg.type === 'agitation_update') {
          setAgitationLevel(msg.level ?? 0)
          setAgitationTrend(msg.trend ?? 'stable')
        } else if (msg.type === 'ai_text') {
          setAiText((prev) => prev + msg.text)
        }
      } catch {
        // ignore parse errors
      }
    }

    return () => {
      ws.close()
    }
  }, [])

  return { agitationLevel, agitationTrend, aiText, connected }
}
