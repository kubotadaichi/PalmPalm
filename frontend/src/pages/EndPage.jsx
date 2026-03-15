export function EndPage({ onBack }) {
  return (
    <div className="fortune-container">
      <div className="top-right-timer">残り 0s</div>
      <div className="main-character-area">
        <div className="image-container">
          <img src="/p3_listen.jpg" alt="ぱむぱむ" className="main-image" />
        </div>
      </div>
      <div className="result-overlay">
        <div className="result-content">
          <h2 className="result-text">終了しました</h2>
          <button className="back-button" onClick={onBack}>
            戻る
          </button>
        </div>
      </div>
    </div>
  )
}
