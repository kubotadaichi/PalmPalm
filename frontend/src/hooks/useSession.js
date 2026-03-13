import { useCallback, useEffect, useRef, useState } from 'react'

const MAX_RECORD_SECONDS = 10
const MICROPHONE_UNAVAILABLE_MESSAGE =
  'この環境ではマイクが利用できません。HTTPS または localhost で開いてください。'

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
  const [aiText, setAiText] = useState('')
  const [vadError, setVadError] = useState(null)
  const [timeLeft, setTimeLeft] = useState(MAX_RECORD_SECONDS)

  const streamRef = useRef(null)
  const recorderRef = useRef(null)
  const chunksRef = useRef([])
  const countdownRef = useRef(null)
  const stopTimerRef = useRef(null)
  const enabledRef = useRef(enabled)

  const audioQueueRef = useRef([])
  const isPlayingRef = useRef(false)
  const sseCompleteRef = useRef(false)

  const playNext = useCallback(() => {
    if (isPlayingRef.current) return
    const url = audioQueueRef.current.shift()
    if (!url) {
      if (sseCompleteRef.current) setTurn('user')
      return
    }
    isPlayingRef.current = true
    const audio = new Audio(url)
    const onDone = () => {
      isPlayingRef.current = false
      playNext()
    }
    audio.onended = onDone
    audio.onerror = onDone
    audio.play().catch(onDone)
  }, [])

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

  const resetPlaybackState = useCallback(() => {
    audioQueueRef.current = []
    isPlayingRef.current = false
    sseCompleteRef.current = false
  }, [])

  const startRecording = useCallback(async () => {
    setVadError(null)
    const mediaDevices = globalThis.navigator?.mediaDevices
    if (!mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setVadError(MICROPHONE_UNAVAILABLE_MESSAGE)
      return
    }
    try {
      if (!streamRef.current) {
        streamRef.current = await mediaDevices.getUserMedia({ audio: true })
      }
      const preferredType = 'audio/webm;codecs=opus'
      const options = MediaRecorder.isTypeSupported(preferredType)
        ? { mimeType: preferredType }
        : undefined
      const recorder = new MediaRecorder(streamRef.current, options)
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (e) => {
        if (e.data?.size > 0) chunksRef.current.push(e.data)
      }
      recorder.onerror = (e) => setVadError(e.error?.message ?? '録音エラー')
      recorder.onstop = async () => {
        clearTimers()
        setTimeLeft(MAX_RECORD_SECONDS)
        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || 'audio/webm',
        })
        chunksRef.current = []
        if (!enabledRef.current) {
          return
        }
        if (blob.size > 0) {
          await sendAudioRef.current?.(blob, recorder.mimeType || 'audio/webm')
        } else {
          setTurn('user')
        }
      }

      recorder.start()
      setTimeLeft(MAX_RECORD_SECONDS)
      countdownRef.current = setInterval(
        () => setTimeLeft((t) => Math.max(0, t - 1)),
        1000,
      )
      stopTimerRef.current = setTimeout(() => {
        if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
      }, MAX_RECORD_SECONDS * 1000)
    } catch (err) {
      setVadError(err?.message ?? 'マイク初期化失敗')
    }
  }, [clearTimers])

  const sendAudioRef = useRef(null)

  useEffect(() => {
    enabledRef.current = enabled
  }, [enabled])

  const sendAudio = useCallback(async (blob, mimeType) => {
    resetPlaybackState()
    setTurn('ai')
    setAiText('')

    try {
      const response = await fetch('/api/audio', {
        method: 'POST',
        headers: { 'Content-Type': mimeType },
        body: blob,
      })
      for await (const event of readSseStream(response)) {
        if (event.type === 'stage1' || event.type === 'stage2') {
          setAiText((prev) => prev + event.text)
          if (event.audio_url) {
            audioQueueRef.current.push(event.audio_url)
            playNext()
          }
        } else if (event.type === 'turn_end') {
          sseCompleteRef.current = true
          if (!isPlayingRef.current && audioQueueRef.current.length === 0) {
            setTurn('user')
          }
        }
      }
    } catch (err) {
      console.error('[useSession] sendAudio error:', err)
      setTurn('user')
    }
  }, [playNext, resetPlaybackState])

  useEffect(() => {
    sendAudioRef.current = sendAudio
  }, [sendAudio])

  const startRecordingRef = useRef(startRecording)

  useEffect(() => {
    startRecordingRef.current = startRecording
  }, [startRecording])

  useEffect(() => {
    if (!enabled) {
      clearTimers()
      if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
      return
    }
    if (turn === 'user') {
      startRecordingRef.current()
    } else {
      clearTimers()
      if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
    }
  }, [enabled, turn, clearTimers])

  useEffect(() => {
    if (!enabled) {
      clearTimers()
      setVadError(null)
      setTimeLeft(MAX_RECORD_SECONDS)
      resetPlaybackState()
      setAiText('')
      setTurn('user')
      return
    }
    setVadError(null)
    setTimeLeft(MAX_RECORD_SECONDS)
    resetPlaybackState()
    setAiText('')
    setTurn('user')
  }, [enabled, clearTimers, resetPlaybackState])

  useEffect(() => {
    return () => {
      clearTimers()
      if (recorderRef.current?.state === 'recording') recorderRef.current.stop()
      streamRef.current?.getTracks().forEach((t) => t.stop())
    }
  }, [clearTimers])

  return { turn, aiText, vadError, timeLeft }
}
