// frontend/src/components/VibrationEffect.jsx
//
// ============================================================
// 🎨 ここを自由に編集してください！（初心者担当エリア）
//
// agitationLevel: 0〜100 の数値です
//   0   = 平静（通常の状態）
//   50  = 少し動揺している
//   100 = 最大動揺（占いがバチバチに当たっている！）
//
// やってみること例:
//   - 背景色を変える: agitationLevel が高いほど赤くなる
//   - 画面を揺らす: CSS の shake アニメーションを使う
//   - テキストをぼかす
//   - 枠線を点滅させる
//
// 使い方:
//   agitationLevel を使って className や style を変えるだけです！
// ============================================================

export function VibrationEffect({ agitationLevel, children }) {
  const isAgitated = agitationLevel > 50

  return (
    <div
      className={`min-h-screen transition-colors duration-300 ${
        isAgitated ? 'animate-pulse' : ''
      }`}
      style={{
        // ヒント: agitationLevelを使って動的にスタイルを変えられます
        // 例: backgroundColor: `rgba(255, 0, 0, ${agitationLevel / 300})`
        backgroundColor: isAgitated
          ? `rgba(255, 50, 50, ${agitationLevel / 400})`
          : 'transparent',
      }}
    >
      {children}
    </div>
  )
}
