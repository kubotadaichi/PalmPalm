import React from 'react';
import { useNavigate } from 'react-router-dom';

function Home() {
  const navigate = useNavigate();

  const handleStart = () => {
    // 2ページ目（占い入力画面などを想定）へ遷移
    navigate('/page2');
  };

  return (
    <div className="home-container">
      <h1 className="title">ぱむぱむ<br /><span style={{ fontSize: '0.6em' }}>~AI手相占い~</span></h1>

      <div className="image-container">
        <img
          src="/p1_center.png"
          alt="ぱむぱむ"
          className="main-image"
        />
      </div>

      <button className="start-button" onClick={handleStart}>
        スタート
      </button>
    </div>
  );
}

export default Home;
