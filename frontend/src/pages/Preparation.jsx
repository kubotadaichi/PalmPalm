import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';

function Preparation() {
  const navigate = useNavigate();
  // カウントダウンの秒数（10秒に設定）
  const [timeLeft, setTimeLeft] = useState(10);

  useEffect(() => {
    // 1秒ごとに timeLeft を減らすタイマーを設定
    const timerId = setInterval(() => {
      setTimeLeft((prevTime) => prevTime - 1);
    }, 1000);

    // 0秒になったら自動的に次のページ（/page3）へ遷移
    if (timeLeft <= 0) {
      clearInterval(timerId); // タイマーを止める
      navigate('/page3');
    }

    // コンポーネントがアンマウント（画面が切り替わる時）されたらタイマーをクリア
    return () => clearInterval(timerId);
  }, [timeLeft, navigate]);

  return (
    <div className="preparation-container">
      {/* 1分割目 */}
      <div className="step-section">
        <div className="placeholder-image">
          {/* ここに模擬の手にユーザーの手をのせた画像を挿入します */}
          <span>画像エリア 1</span>
        </div>
        <div className="step-text">手をのせる</div>
      </div>

      <div className="step-arrow">▶</div>

      {/* 2分割目 */}
      <div className="step-section">
        <div className="placeholder-image">
          {/* ここに深呼吸している画像を挿入します */}
          <span>画像エリア 2</span>
        </div>
        <div className="step-text">深呼吸</div>
      </div>

      <div className="step-arrow">▶</div>

      {/* 3分割目 */}
      <div className="step-section">
        <div className="placeholder-image">
          {/* ここに自動でスタートする画像を挿入します */}
          <span>画像エリア 3</span>
        </div>
        <div className="step-text">５秒後開始</div>
      </div>

      {/* 中央下部のタイマー */}
      <div className="timer-display">
        開始まで {timeLeft} 秒
      </div>
    </div>
  );
}

export default Preparation;
