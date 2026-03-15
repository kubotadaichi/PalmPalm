import React, { useEffect, useState } from 'react'

const STEPS = [
  { label: '手をのせる', img: '/p2_part1.png' },
  { label: '深呼吸',     img: '/p2_part2.png' },
  { label: '５秒後開始', img: '/p2_part3.png' },
]

export function RulesPage({ onReady }) {
  const [countdown, setCountdown] = useState(5)

  useEffect(() => {
    if (countdown <= 0) {
      onReady()
      return
    }
    const t = setTimeout(() => setCountdown((c) => c - 1), 1000)
    return () => clearTimeout(t)
  }, [countdown, onReady])

  return (
    <div className="preparation-container">
      {STEPS.map((step, i) => (
        <React.Fragment key={i}>
          {i > 0 && <div className="step-arrow">▶</div>}
          <div className="step-section">
            <div className="placeholder-image">
              <img src={step.img} alt={step.label} className="step-image" />
            </div>
            <div className="step-text">{step.label}</div>
          </div>
        </React.Fragment>
      ))}
      <div className="timer-display">開始まで {countdown} 秒</div>
    </div>
  )
}
