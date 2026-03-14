import React from 'react';
import { useNavigate } from 'react-router-dom';

function Result() {
  const navigate = useNavigate();

  const handleBack = () => {
    // 最初のページに戻る
    navigate('/');
  };

  return (
    <div className="fortune-container">
      {/* 画面右上のタイマー枠（終了なので 0 秒固定） */}
      <div className="top-right-timer">
        残り 0 秒
      </div>

      {/* 画面中央のぱむぱむ画像エリア（背景として残す） */}
      <div className="main-character-area">
        <div className="image-container talking-image">
          <img 
            src="https://placehold.jp/300x300.png?text=PamPam" 
            alt="ぱむぱむ" 
            className="main-image"
          />
        </div>
      </div>

      {/* --- ここからが4ページ目のメイン（オーバーレイ） --- */}
      <div className="result-overlay">
        <div className="result-content">
          <h2 className="result-text">終了しました</h2>
          <button className="back-button" onClick={handleBack}>
            戻る
          </button>
        </div>
      </div>
    </div>
  );
}

export default Result;
