import { useCallback, useEffect, useRef, useState } from 'react'

const HTTP_BASE = import.meta.env.VITE_BACKEND_URL ?? 'http://localhost:8000'

async function* readSseStream(response) {
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop()
    for (const line of lines) {
      if (line.startsWith('data: ')) {
        try {
          yield JSON.parse(line.slice(6))
        } catch {
          // ignore malformed
        }
      }
    }
  }
}

export function useSession() {
  const [aiText, setAiText] = useState('')
  const [aiAudioQueue, setAiAudioQueue] = useState([])
  const [turn, setTurn] = useState('ai')
  const [aiTurnEnded, setAiTurnEnded] = useState(false)
  const audioPlayedRef = useRef(0)

  const handleEvent = useCallback((event) => {
    if (event.type === 'intro' || event.type === 'stage1' || event.type === 'stage2') {
      setAiText((prev) => prev + event.text)
      if (event.audio_url) {
        setAiAudioQueue((prev) => [...prev, HTTP_BASE + event.audio_url])
      }
    } else if (event.type === 'turn_end') {
      setAiTurnEnded(true)
    }
  }, [])

  // イントロ: EventSource (GET /api/session/start)
  useEffect(() => {
    const es = new EventSource(`${HTTP_BASE}/api/session/start`)
    es.onmessage = (e) => {
      try { handleEvent(JSON.parse(e.data)) } catch {}
    }
    es.onerror = () => es.close()
    return () => es.close()
  }, [handleEvent])

  const sendAudio = useCallback(async (blob, mimeType) => {
    setTurn('ai')
    setAiText('')
    setAiAudioQueue([])
    setAiTurnEnded(false)
    audioPlayedRef.current = 0

    try {
      const response = await fetch(`${HTTP_BASE}/api/audio`, {
        method: 'POST',
        headers: { 'Content-Type': mimeType },
        body: blob,
      })
      for await (const event of readSseStream(response)) {
        handleEvent(event)
      }
    } catch (e) {
      console.error('[useSession] sendAudio error:', e)
    }
  }, [handleEvent])

  const startUserTurn = useCallback(() => {
    setTurn('user')
    setAiTurnEnded(false)
    setAiAudioQueue([])
    audioPlayedRef.current = 0
  }, [])

  const setTurnToAi = useCallback(() => setTurn('ai'), [])

  return { aiText, aiAudioQueue, turn, aiTurnEnded, audioPlayedRef, startUserTurn, setTurnToAi, sendAudio }
}
