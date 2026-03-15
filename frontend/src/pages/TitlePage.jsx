export function TitlePage({ onStart }) {
  return (
    <div className="home-container">
      <h1 className="title">
        ぱむぱむ<br />
        <span style={{ fontSize: '0.6em' }}>〜AI手相占い〜</span>
      </h1>
      <div className="image-container">
        <img src="/p1_center.png" alt="ぱむぱむ" className="main-image" />
      </div>
      <button className="start-button" onClick={onStart}>
        スタート
      </button>
    </div>
  )
}
