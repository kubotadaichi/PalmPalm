export function EndPage({ onBack }) {
  return (
    <div className="flex flex-col items-center justify-center h-screen bg-gray-900 text-white">
      <div className="w-64 h-64 rounded-full bg-gray-700 flex flex-col items-center justify-center gap-6">
        <p className="text-xl font-bold">終了しました</p>
        <button
          onClick={onBack}
          className="px-6 py-2 bg-white text-gray-900 rounded font-bold hover:bg-gray-200 transition-colors"
        >
          戻る
        </button>
      </div>
    </div>
  )
}
