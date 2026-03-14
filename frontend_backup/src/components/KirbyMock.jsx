// frontend/src/components/KirbyMock.jsx
// 本番ではimageUrlを渡すと画像に差し替えられる

export function KirbyMock({ isTalking, imageUrl }) {
  if (imageUrl) {
    return (
      <img
        src={imageUrl}
        alt="ぱむぱむ"
        className={`w-48 h-48 object-contain ${isTalking ? 'animate-bounce' : ''}`}
      />
    )
  }

  // モック: CSS丸 + 口アニメ
  return (
    <div className="relative w-48 h-48 flex items-center justify-center">
      <div className="w-full h-full rounded-full bg-pink-300 flex items-center justify-center">
        <div className="flex flex-col items-center">
          {/* 目 */}
          <div className="flex gap-6 mb-3">
            <div className="w-4 h-4 rounded-full bg-gray-800" />
            <div className="w-4 h-4 rounded-full bg-gray-800" />
          </div>
          {/* 口: 喋っているときは大きく開く */}
          <div
            className={`bg-red-500 rounded-full transition-all duration-150 ${
              isTalking ? 'w-10 h-7' : 'w-8 h-2'
            }`}
          />
        </div>
      </div>
    </div>
  )
}
