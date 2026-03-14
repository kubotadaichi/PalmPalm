import { useCallback, useEffect, useRef, useState } from 'react'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || ''
const MAX_RECORD_SECONDS = 10

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
          // ignore
        }
      }
    }
  }
}

export function useSession({ enabled = false } = {}) {
  const [turn, setTurn] = useState('user')
  const [vadError, setVadError] = useState(null)
  const [timeLeft, setTimeLeft] = useState(MAX_RECORD_SECONDS)

  const sessionIdRef = useRef(null)
  const audioCtxRef = useRef(null)
  const captureCtxRef = useRef(null)
  const workletNodeRef = useRef(null)
  const streamRef = useRef(null)
  const pcmChunksRef = useRef([])
  const nextPlayTimeRef = useRef(0)
  const countdownRef = useRef(null)
  const stopTimerRef = useRef(null)
  const enabledRef = useRef(enabled)

  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  const startSession = useCallback(async () => {
    try {
      const response = await fetch(`${BACKEND_URL}/api/session/start`, { method: 'POST' })
      const { session_id: sessionId } = await response.json()
      sessionIdRef.current = sessionId
      console.log('[useSession] session started:', sessionId)
    } catch (err) {
      setVadError(`セッション開始失敗: ${err.message}`)
    }
  }, [])

  const stopSession = useCallback(async () => {
    const sessionId = sessionIdRef.current
    if (!sessionId) return
    sessionIdRef.current = null
    try {
      await fetch(`${BACKEND_URL}/api/session?session_id=${sessionId}`, { method: 'DELETE' })
    } catch {
      // ignore
    }
  }, [])

  const stopRecording = useCallback(async () => {
    if (countdownRef.current) {
      clearInterval(countdownRef.current)
      countdownRef.current = null
    }
    if (stopTimerRef.current) {
      clearTimeout(stopTimerRef.current)
      stopTimerRef.current = null
    }
    setTimeLeft(MAX_RECORD_SECONDS)

    const worklet = workletNodeRef.current
    if (worklet) {
      worklet.disconnect()
      workletNodeRef.current = null
    }

    const chunks = pcmChunksRef.current
    pcmChunksRef.current = []
    if (!enabledRef.current || chunks.length === 0) {
      setTurn('user')
      return
    }

    const total = chunks.reduce((sum, chunk) => sum + chunk.length, 0)
    const merged = new Int16Array(total)
    let offset = 0
    for (const chunk of chunks) {
      merged.set(chunk, offset)
      offset += chunk.length
    }

    const sessionId = sessionIdRef.current
    if (!sessionId) {
      setTurn('user')
      return
    }

    setTurn('ai')

    if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
      audioCtxRef.current = new AudioContext({ sampleRate: 24000 })
    }
    const audioCtx = audioCtxRef.current
    nextPlayTimeRef.current = audioCtx.currentTime

    try {
      const response = await fetch(`${BACKEND_URL}/api/audio?session_id=${sessionId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'audio/octet-stream' },
        body: merged.buffer,
      })
      for await (const event of readSseStream(response)) {
        if (event.type === 'audio_chunk') {
          const raw = atob(event.data)
          const int16 = new Int16Array(raw.length / 2)
          for (let i = 0; i < int16.length; i++) {
            int16[i] = raw.charCodeAt(i * 2) | (raw.charCodeAt(i * 2 + 1) << 8)
          }

          const float32 = new Float32Array(int16.length)
          for (let i = 0; i < int16.length; i++) {
            float32[i] = int16[i] / 32768
          }

          const buffer = audioCtx.createBuffer(1, float32.length, 24000)
          buffer.copyToChannel(float32, 0)
          const source = audioCtx.createBufferSource()
          source.buffer = buffer
          source.connect(audioCtx.destination)
          const startAt = Math.max(audioCtx.currentTime, nextPlayTimeRef.current)
          source.start(startAt)
          nextPlayTimeRef.current = startAt + buffer.duration
        } else if (event.type === 'turn_complete') {
          const remaining = nextPlayTimeRef.current - audioCtx.currentTime
          setTimeout(() => setTurn('user'), Math.max(0, remaining * 1000))
        }
      }
    } catch (err) {
      console.error('[useSession] sendAudio error:', err)
      setTurn('user')
    }
  }, [])

  const startRecording = useCallback(async () => {
    setVadError(null)
    const mediaDevices = globalThis.navigator?.mediaDevices
    if (!mediaDevices?.getUserMedia) {
      setVadError('マイクが利用できません。HTTPS または localhost で開いてください。')
      return
    }

    try {
      if (!streamRef.current) {
        streamRef.current = await mediaDevices.getUserMedia({ audio: true })
      }
      if (!captureCtxRef.current || captureCtxRef.current.state === 'closed') {
        captureCtxRef.current = new AudioContext({ sampleRate: 16000 })
      }
      const captureCtx = captureCtxRef.current
      await captureCtx.audioWorklet.addModule('/pcm-processor.js')

      const source = captureCtx.createMediaStreamSource(streamRef.current)
      const worklet = new AudioWorkletNode(captureCtx, 'pcm-processor')
      workletNodeRef.current = worklet

      pcmChunksRef.current = []
      worklet.port.onmessage = (event) => {
        pcmChunksRef.current.push(new Int16Array(event.data))
      }
      source.connect(worklet)
      worklet.connect(captureCtx.destination)

      setTimeLeft(MAX_RECORD_SECONDS)
      countdownRef.current = setInterval(
        () => setTimeLeft((value) => Math.max(0, value - 1)),
        1000,
      )
      stopTimerRef.current = setTimeout(() => stopRecording(), MAX_RECORD_SECONDS * 1000)
    } catch (err) {
      setVadError(err?.message ?? 'マイク初期化失敗')
    }
  }, [stopRecording])

  useEffect(() => {
    if (!enabled) {
      stopSession()
      setVadError(null)
      setTimeLeft(MAX_RECORD_SECONDS)
      setTurn('user')
      return
    }
    startSession()
  }, [enabled, startSession, stopSession])

  useEffect(() => {
    if (!enabled) return
    if (turn === 'user') {
      startRecording()
    } else if (workletNodeRef.current) {
      workletNodeRef.current.disconnect()
      workletNodeRef.current = null
    }
  }, [enabled, turn, startRecording])

  useEffect(() => {
    return () => {
      if (countdownRef.current) clearInterval(countdownRef.current)
      if (stopTimerRef.current) clearTimeout(stopTimerRef.current)
      streamRef.current?.getTracks().forEach((track) => track.stop())
      captureCtxRef.current?.close()
      audioCtxRef.current?.close()
    }
  }, [])

  return { turn, vadError, timeLeft }
}
