import { useEffect, useState } from 'react'

const STEPS = [
  { label: '手を乗せる' },
  { label: '深呼吸' },
  { label: '落ち着いたら\n自分でスタート' },
]

export function RulesPage({ onReady }) {
  const [countdown, setCountdown] = useState(10)

  useEffect(() => {
    if (countdown <= 0) {
      onReady()
      return
    }
    const t = setTimeout(() => setCountdown((c) => c - 1), 1000)
    return () => clearTimeout(t)
  }, [countdown, onReady])

  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-900 text-white">
      <h2 className="text-3xl font-bold mb-12">ルール説明</h2>
      <div className="flex gap-10 mb-12">
        {STEPS.map((step, i) => (
          <div key={i} className="flex flex-col items-center gap-3">
            <div className="w-20 h-20 bg-gray-700 rounded-lg flex items-center justify-center text-2xl font-bold text-gray-400">
              {i + 1}
            </div>
            <p className="text-sm text-center text-gray-300 whitespace-pre">{step.label}</p>
          </div>
        ))}
      </div>
      <p className="text-gray-400 text-lg">開始まで {countdown} 秒</p>
    </div>
  )
}
