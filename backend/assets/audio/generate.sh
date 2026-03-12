#!/bin/bash
set -e
cd "$(dirname "$0")"

generate() {
  local text="$1"
  local name="$2"
  say -v Kyoko "$text" -o "${name}.aiff"
  afconvert -f m4af -d aac "${name}.aiff" "${name}.m4a"
  rm "${name}.aiff"
  echo "Generated ${name}.m4a"
}

# 通常台本
generate "あなたの手相には、深い感情線が刻まれています。" line1
generate "生命線は力強く、長い旅路を示しています。" line2
generate "知能線が少し湾曲している。創造性の証です。" line3
generate "小指の付け根に薄い縦線が、コミュニケーション運が高い。" line4
generate "運命線がはっきりと中央を走っている。強い意志を感じます。" line5
generate "太陽線が複数本ある。多才で、人を惹きつける力があります。" line6

# 豹変台本
generate "ほら、震えてますよね！当たったでしょ！！" spike1
generate "手が揺れてる！この反応、隠せないですよ！" spike2
generate "やっぱり！今の線のこと、心当たりがあるでしょ！" spike3
generate "動揺してますよね？当たりすぎて怖いですか？" spike4

echo "Done! Generated $(ls *.m4a | wc -l) files."
