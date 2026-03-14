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
      <h1 className="title">ぱむぱむ~AI手相占い</h1>
      
      <div className="image-container">
        {/* 後で本物の画像に差し替えます */}
        <img 
          src="https://placehold.jp/300x300.png?text=PamPam" 
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
