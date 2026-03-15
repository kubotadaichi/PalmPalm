import { useCallback, useEffect, useRef, useState } from 'react'

const BACKEND_URL = import.meta.env.VITE_BACKEND_URL || ''

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
  // 'ai' から始めることで、初回 AI 挨拶が終わるまで音声送信を抑制する
  const [turn, setTurn] = useState('ai')
  const [vadError, setVadError] = useState(null)
  const [sessionReady, setSessionReady] = useState(false)

  const socketRef = useRef(null)
  const audioCtxRef = useRef(null)
  const captureCtxRef = useRef(null)
  const workletNodeRef = useRef(null)
  const streamRef = useRef(null)
  const nextPlayTimeRef = useRef(0)
  const enabledRef = useRef(enabled)
  const moduleLoadedRef = useRef(false)
  const sessionReadyRef = useRef(sessionReady)
  const aiTurnTimeoutRef = useRef(null)
  const turnRef = useRef('ai')
  const sentPcmChunksRef = useRef(0)
  const receivedAudioChunksRef = useRef(0)

  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  useEffect(() => {
    sessionReadyRef.current = sessionReady
  }, [sessionReady])

  useEffect(() => {
    turnRef.current = turn
  }, [turn])

  const setTurnWithReason = useCallback((nextTurn, reason, extra = '') => {
    setTurn((prevTurn) => {
      const suffix = extra ? ` ${extra}` : ''
      if (prevTurn !== nextTurn) {
        console.log(`[useSession] turn ${prevTurn} -> ${nextTurn} reason=${reason}${suffix}`)
      } else {
        console.log(`[useSession] turn ${nextTurn} unchanged reason=${reason}${suffix}`)
      }
      turnRef.current = nextTurn
      return nextTurn
    })
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
    const worklet = workletNodeRef.current
    if (worklet) {
      worklet.port.onmessage = null
      worklet.disconnect()
      workletNodeRef.current = null
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

      // AI ターン中は送信しない: START_OF_ACTIVITY_INTERRUPTS で AI 発話が中断されるのを防ぐ
      worklet.port.onmessage = (event) => {
        const socket = socketRef.current
        if (
          !enabledRef.current ||
          !sessionReadyRef.current ||
          socket?.readyState !== WebSocket.OPEN ||
          turnRef.current !== 'user'
        ) {
          return
        }
        sentPcmChunksRef.current += 1
        if (sentPcmChunksRef.current === 1 || sentPcmChunksRef.current % 200 === 0) {
          console.log(`[useSession] sent pcm count=${sentPcmChunksRef.current} turn=${turnRef.current}`)
        }
        socket.send(event.data)
      }

      source.connect(worklet)
      worklet.connect(captureCtx.destination)
      console.log('[useSession] recording started')
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
          sentPcmChunksRef.current = 0
          receivedAudioChunksRef.current = 0
          setSessionReady(true)
          console.log('[useSession] session ready')
          return
        }
        if (message.type === 'audio_chunk') {
          receivedAudioChunksRef.current += 1
          console.log(
            `[useSession] received audio_chunk count=${receivedAudioChunksRef.current} turn=${turnRef.current}`,
          )
          setTurnWithReason('ai', 'audio_chunk', `audioChunkCount=${receivedAudioChunksRef.current}`)
          // AIが喋り始めたら30秒タイムアウトをセット
          if (aiTurnTimeoutRef.current) clearTimeout(aiTurnTimeoutRef.current)
          aiTurnTimeoutRef.current = setTimeout(() => {
            console.warn('[useSession] AI turn timeout, forcing user turn')
            setTurnWithReason('user', 'ai_timeout')
            aiTurnTimeoutRef.current = null
          }, 30000)
          void playAudioChunk(message.data)
          return
        }
        if (message.type === 'turn_complete') {
          console.log('[useSession] received turn_complete')
          if (aiTurnTimeoutRef.current) {
            clearTimeout(aiTurnTimeoutRef.current)
            aiTurnTimeoutRef.current = null
          }
          const audioCtx = audioCtxRef.current
          const remaining = audioCtx ? nextPlayTimeRef.current - audioCtx.currentTime : 0
          setTimeout(
            () => setTurnWithReason('user', 'turn_complete', `remainingMs=${Math.max(0, remaining * 1000).toFixed(0)}`),
            Math.max(0, remaining * 1000),
          )
          return
        }
        if (message.type === 'error') {
          console.log('[useSession] received error', message)
          if (aiTurnTimeoutRef.current) {
            clearTimeout(aiTurnTimeoutRef.current)
            aiTurnTimeoutRef.current = null
          }
          setVadError(message.message ?? 'セッションエラー')
          setTurnWithReason('user', 'error')
        }
      } catch {
        // ignore non-JSON frames
      }
    }

    socket.onerror = () => {
      console.log('[useSession] websocket error')
      setVadError('WebSocket 接続に失敗しました')
    }
    socket.onclose = (event) => {
      console.log(`[useSession] websocket close code=${event.code} reason=${event.reason}`)
      setSessionReady(false)
    }
    socketRef.current = socket
  }, [playAudioChunk, setTurnWithReason])

  const stopSession = useCallback(() => {
    setSessionReady(false)
    const socket = socketRef.current
    socketRef.current = null
    if (socket?.readyState === WebSocket.OPEN) {
      socket.send(JSON.stringify({ type: 'session_end' }))
      socket.close()
    }
  }, [])

  // セッション開始/終了
  useEffect(() => {
    if (!enabled) {
      stopRecording()
      stopSession()
      setVadError(null)
      setSessionReady(false)
      setTurnWithReason('ai', 'disabled')
      return
    }

    startSession()
  }, [enabled, setTurnWithReason, startSession, stopRecording, stopSession])

  // session_ready になったら録音開始し、以後ずっと送信し続ける
  useEffect(() => {
    if (!enabled || !sessionReady) return
    void startRecording()
  }, [enabled, sessionReady, startRecording])

  useEffect(() => {
    return () => {
      stopRecording()
      stopSession()
      streamRef.current?.getTracks().forEach((track) => track.stop())
      captureCtxRef.current?.close()
      audioCtxRef.current?.close()
    }
  }, [stopRecording, stopSession])

  return { turn, vadError }
}
