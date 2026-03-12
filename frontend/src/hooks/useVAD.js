import { useCallback, useEffect, useRef, useState } from 'react'

const DEFAULT_MAX_SECONDS = 10

/**
 * マイク音声を最大N秒録音してバックエンドへPOSTするフック
 * @param {string} httpBase - バックエンドのHTTPベースURL (例: "http://localhost:8000")
 */
export function useVAD({ httpBase, maxSeconds = DEFAULT_MAX_SECONDS, turn, onRecordingComplete }) {
  const [isSpeaking, setIsSpeaking] = useState(false)
  const [vadError, setVadError] = useState(null)
  const [isSending, setIsSending] = useState(false)
  const [timeLeft, setTimeLeft] = useState(maxSeconds)
  const [isSupported] = useState(
    typeof navigator !== 'undefined' &&
      Boolean(navigator.mediaDevices?.getUserMedia) &&
      typeof MediaRecorder !== 'undefined',
  )

  const streamRef = useRef(null)
  const recorderRef = useRef(null)
  const chunksRef = useRef([])
  const stopTimeoutRef = useRef(null)
  const countdownIntervalRef = useRef(null)

  const clearTimers = useCallback(() => {
    if (stopTimeoutRef.current) {
      clearTimeout(stopTimeoutRef.current)
      stopTimeoutRef.current = null
    }
    if (countdownIntervalRef.current) {
      clearInterval(countdownIntervalRef.current)
      countdownIntervalRef.current = null
    }
  }, [])

  const sendRecordedAudio = useCallback(
    async (blob) => {
      if (!blob || blob.size === 0) return

      setIsSending(true)
      try {
        await fetch(`${httpBase}/api/audio`, {
          method: 'POST',
          headers: { 'Content-Type': blob.type || 'application/octet-stream' },
          body: blob,
        })
      } catch {
        setVadError('音声送信に失敗しました')
      } finally {
        setIsSending(false)
      }
    },
    [httpBase],
  )

  const ensureStream = useCallback(async () => {
    if (streamRef.current) return streamRef.current
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    streamRef.current = stream
    return stream
  }, [])

  const stopRecording = useCallback(() => {
    const recorder = recorderRef.current
    if (recorder && recorder.state === 'recording') {
      recorder.stop()
    }
  }, [])

  const startRecording = useCallback(async () => {
    setVadError(null)
    if (isSpeaking || !isSupported) return

    try {
      const stream = await ensureStream()

      const preferredType = 'audio/webm;codecs=opus'
      const options = MediaRecorder.isTypeSupported(preferredType)
        ? { mimeType: preferredType }
        : undefined

      const recorder = new MediaRecorder(stream, options)
      recorderRef.current = recorder
      chunksRef.current = []

      recorder.ondataavailable = (event) => {
        if (event.data && event.data.size > 0) {
          chunksRef.current.push(event.data)
        }
      }
      recorder.onerror = (event) => {
        setVadError(event.error?.message ?? '録音中にエラーが発生しました')
      }
      recorder.onstop = async () => {
        clearTimers()
        setIsSpeaking(false)
        setTimeLeft(maxSeconds)

        const blob = new Blob(chunksRef.current, {
          type: recorder.mimeType || 'audio/webm',
        })
        chunksRef.current = []
        await sendRecordedAudio(blob)
        onRecordingComplete?.()
      }

      recorder.start()
      setIsSpeaking(true)
      setTimeLeft(maxSeconds)

      countdownIntervalRef.current = setInterval(() => {
        setTimeLeft((prev) => (prev > 1 ? prev - 1 : 1))
      }, 1000)
      stopTimeoutRef.current = setTimeout(() => {
        if (recorder.state === 'recording') {
          recorder.stop()
        }
      }, maxSeconds * 1000)
    } catch (error) {
      setVadError(error?.message ?? 'マイク初期化に失敗しました')
    }
  }, [clearTimers, ensureStream, isSpeaking, isSupported, maxSeconds, sendRecordedAudio])

  // turn が 'user' になったら自動録音開始
  useEffect(() => {
    if (turn === 'user') {
      startRecording()
    }
    if (turn === 'ai') {
      stopRecording()
    }
  }, [turn]) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    return () => {
      clearTimers()
      const recorder = recorderRef.current
      if (recorder && recorder.state === 'recording') {
        recorder.stop()
      }
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop())
        streamRef.current = null
      }
    }
  }, [clearTimers])

  return {
    isSpeaking,
    vadError,
    isSending,
    timeLeft,
    isSupported,
    startRecording,
    stopRecording,
  }
}
