import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

function FortuneTelling() {
  const navigate = useNavigate();
  // 占い中の残り時間（120秒）
  const [timeLeft, setTimeLeft] = useState(10);

  useEffect(() => {
    // 1秒ごとに timeLeft を減らすタイマーを設定
    const timerId = setInterval(() => {
      setTimeLeft((prevTime) => prevTime - 1);
    }, 1000);

    // 0秒になったら自動的に次のページ（または結果画面）へ遷移
    if (timeLeft <= 0) {
      clearInterval(timerId); // タイマーを止める
      // 4ページ目（占い結果など）へ遷移する想定
      navigate('/page4');
    }

    // コンポーネントがアンマウントされたらタイマーをクリア
    return () => clearInterval(timerId);
  }, [timeLeft, navigate]);

  return (
    <div className="fortune-container">
      {/* 画面右上のタイマー枠 */}
      <div className="top-right-timer">
        残り {timeLeft} 秒
      </div>

      {/* 画面中央のぱむぱむ画像エリア */}
      <div className="main-character-area">
        {/* 画像コンテナ */}
        <div className="image-container talking-image">
          <img
            src="/p3_listen.jpg"
            alt="ぱむぱむ"
            className="main-image"
          />
        </div>
      </div>
    </div>
  );
}

export default FortuneTelling;
