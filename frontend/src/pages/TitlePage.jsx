export function TitlePage({ onStart }) {
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-900 text-white">
      <h1 className="text-5xl font-bold mb-2 tracking-widest">ぱむぱむ</h1>
      <p className="text-gray-400 mb-16 text-lg">〜 AI手相占い 〜</p>
      <div className="w-36 h-36 rounded-full bg-gray-700 mb-16" />
      <button
        onClick={onStart}
        className="px-10 py-4 bg-white text-gray-900 rounded font-bold text-lg hover:bg-gray-200 transition-colors"
      >
        start
      </button>
    </div>
  )
}
