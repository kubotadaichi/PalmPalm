import { useCallback, useEffect, useRef, useState } from 'react'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || ''
const MAX_RECORD_SECONDS = 10

function toWebSocketUrl(baseUrl) {
  if (!baseUrl) {
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
    return `${protocol}//${window.location.host}/ws/session`
  }
  if (baseUrl.startsWith('https://')) {
    return `wss://${baseUrl.slice('https://'.length)}/ws/session`
  }
  if (baseUrl.startsWith('http://')) {
    return `ws://${baseUrl.slice('http://'.length)}/ws/session`
  }
  return `${baseUrl}/ws/session`
}

export function useSession({ enabled = false } = {}) {
  const [turn, setTurn] = useState('user')
  const [vadError, setVadError] = useState(null)
  const [timeLeft, setTimeLeft] = useState(MAX_RECORD_SECONDS)
  const [sessionReady, setSessionReady] = useState(false)

  const socketRef = useRef(null)
  const audioCtxRef = useRef(null)
  const captureCtxRef = useRef(null)
  const workletNodeRef = useRef(null)
  const streamRef = useRef(null)
  const nextPlayTimeRef = useRef(0)
  const countdownRef = useRef(null)
  const stopTimerRef = useRef(null)
  const enabledRef = useRef(enabled)
  const moduleLoadedRef = useRef(false)
  const turnRef = useRef(turn)
  const sessionReadyRef = useRef(sessionReady)

  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  useEffect(() => {
    turnRef.current = turn
  }, [turn])

  useEffect(() => {
    sessionReadyRef.current = sessionReady
  }, [sessionReady])

  const clearTimers = useCallback(() => {
    if (countdownRef.current) {
      clearInterval(countdownRef.current)
      countdownRef.current = null
    }
    if (stopTimerRef.current) {
      clearTimeout(stopTimerRef.current)
      stopTimerRef.current = null
    }
  }, [])

  const playAudioChunk = useCallback(async (base64Data) => {
    if (!audioCtxRef.current || audioCtxRef.current.state === 'closed') {
      audioCtxRef.current = new AudioContext({ sampleRate: 24000 })
    }
    const audioCtx = audioCtxRef.current
    if (audioCtx.state === 'suspended') {
      await audioCtx.resume()
    }

    const raw = atob(base64Data)
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
  }, [])

  const stopRecording = useCallback(() => {
    clearTimers()
    setTimeLeft(MAX_RECORD_SECONDS)

    const worklet = workletNodeRef.current
    if (worklet) {
      worklet.disconnect()
      workletNodeRef.current = null
    }
  }, [clearTimers])

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
        moduleLoadedRef.current = false
      }
      const captureCtx = captureCtxRef.current
      if (!moduleLoadedRef.current) {
        await captureCtx.audioWorklet.addModule('/pcm-processor.js')
        moduleLoadedRef.current = true
      }

      const source = captureCtx.createMediaStreamSource(streamRef.current)
      const worklet = new AudioWorkletNode(captureCtx, 'pcm-processor')
      workletNodeRef.current = worklet

      worklet.port.onmessage = (event) => {
        const pcm = new Int16Array(event.data)
        const socket = socketRef.current
        if (
          !enabledRef.current ||
          turnRef.current !== 'user' ||
          !sessionReadyRef.current ||
          socket?.readyState !== WebSocket.OPEN
        ) {
          return
        }
        socket.send(event.data)
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

  const startSession = useCallback(() => {
    const socket = new WebSocket(toWebSocketUrl(BACKEND_URL))
    socket.binaryType = 'arraybuffer'

    socket.onmessage = (event) => {
      try {
        const message = JSON.parse(event.data)
        if (message.type === 'session_ready') {
          setSessionReady(true)
          console.log('[useSession] session ready')
          return
        }
        if (message.type === 'audio_chunk') {
          setTurn('ai')
          void playAudioChunk(message.data)
          return
        }
        if (message.type === 'turn_complete') {
          const audioCtx = audioCtxRef.current
          const remaining = audioCtx ? nextPlayTimeRef.current - audioCtx.currentTime : 0
          setTimeout(() => setTurn('user'), Math.max(0, remaining * 1000))
          return
        }
        if (message.type === 'error') {
          setVadError(message.message ?? 'セッションエラー')
          setTurn('user')
        }
      } catch {
        // ignore non-JSON frames
      }
    }

    socket.onerror = () => {
      setVadError('WebSocket 接続に失敗しました')
    }
    socket.onclose = () => {
      setSessionReady(false)
    }
    socketRef.current = socket
  }, [playAudioChunk])

  const stopSession = useCallback(() => {
    setSessionReady(false)
    const socket = socketRef.current
    socketRef.current = null
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'session_end' }))
      socket.close()
    }
  }, [])

  useEffect(() => {
    if (!enabled) {
      stopRecording()
      stopSession()
      setVadError(null)
      setSessionReady(false)
      setTimeLeft(MAX_RECORD_SECONDS)
      setTurn('user')
      return
    }

    startSession()
  }, [enabled, startSession, stopRecording, stopSession])

  useEffect(() => {
    if (!enabled || !sessionReady) return
    if (turn === 'user') {
      void startRecording()
    } else {
      stopRecording()
    }
  }, [enabled, sessionReady, turn, startRecording, stopRecording])

  useEffect(() => {
    return () => {
      stopRecording()
      stopSession()
      streamRef.current?.getTracks().forEach((track) => track.stop())
      captureCtxRef.current?.close()
      audioCtxRef.current?.close()
    }
  }, [stopRecording, stopSession])

  return { turn, vadError, timeLeft }
}
