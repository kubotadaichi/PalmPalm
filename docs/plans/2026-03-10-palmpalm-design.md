# PalmPalm 設計ドキュメント

## 概要

AI手相占い「ぱむぱむ」のハッカソン向け設計。
**コンセプト:** ユーザーの物理的な揺れをリアルタイムに検知し、「占いが当たっている証拠」としてLLMに解釈させ、AIが畳み掛けるリアクションで笑いを取る。

---

## システム構成

```
Raspberry Pi（振動センサー 0/1パルス）
    ↓ WebSocket
Mac Backend（FastAPI）
    ├── 動揺率エンジン（スライディングウィンドウ）
    ├── Gemini Live API セッション管理
    │   ├── Pull: get_agitation_level() Tool Use
    │   └── Push: 急上昇時に割り込み指示
    └── フロントエンド向け WebSocket 配信
         ↓
Frontend（React / Vite / Docker）
    └── 4画面構成 + カービィキャラクター + エフェクト
```

---

## 動揺率エンジン

### センサー → 動揺率変換

- センサー出力: 0/1 バイナリパルス
- スライディングウィンドウ（直近10秒の揺れ回数）で `agitation_level`（0〜100）を算出
- `trend`（rising / falling / stable）も計算する

```python
# 疑似コード
agitation_level = (pulse_count_last_10s / MAX_PULSES) * 100
trend = "rising" if current > previous + 10 else "falling" if current < previous - 10 else "stable"
```

### LLMへの渡し方（Push/Pull 両用）

| モード | 発火条件 | 内容 |
|--------|----------|------|
| Pull（Tool Use） | Geminiが自発的に呼び出す | `get_agitation_level()` → `{ level, trend }` |
| Push（割り込み） | 動揺率が前回比+30以上の急上昇 | セッションに「今{level}%動揺しています」を挿入 |

### Gemini基本プロンプト方針

> ユーザーの揺れ率は占いの的確度への反応です。
> `level`が高いほど当たっている。`trend: rising`なら確信を持って追い込め。
> Push通知が来たら必ずリアクションしろ。

---

## フロントエンド構成

### 画面フロー

```
① タイトル画面
    → スタートボタンクリック
① ルール説明画面
    → 手を乗せる → 深呼吸 → 落ち着いたら自分でスタート（カウントダウン）
② セッション画面（メイン）
    → カービィ口ぱくアニメーション + 残り時間 + 動揺エフェクト
③ 終了画面
    → 「終了しました」+ 戻るボタン
```

### ディレクトリ構成

```
src/
├── pages/
│   ├── TitlePage.tsx          # ①スタートボタン
│   ├── RulesPage.tsx          # ①'カウントダウン
│   ├── SessionPage.tsx        # ②カービィ＋残り時間
│   └── EndPage.tsx            # ③終了
├── components/
│   ├── KirbyMock.tsx          # モック：CSS丸＋口アニメ（後で画像差替）
│   └── VibrationEffect.tsx    # 初心者担当：動揺エフェクト（CSS shake）
└── hooks/
    └── useBackendWS.ts        # あなた死守：WebSocket接続＋データパース
```

### 技術選定

- React + Vite + Tailwind CSS
- Framer Motion **不使用**（CSS `@keyframes` で十分）
- キャラクター素材: 既存画像（ハッカソン当日まではCSS丸モック）

---

## 事前準備タスク（今日〜金曜）

| 優先 | タスク | 担当 | 完了条件 |
|------|--------|------|----------|
| 🔴 | Gemini Live API PoC | あなた | 音声入力→応答＋セッション中割り込みが動く |
| 🔴 | Dockerスキャフォールド生成 | バイブコーディング | `docker compose up`で画面①が表示される |
| 🟡 | ラズパイ→Mac WebSocket疎通確認 | あなた | イベントがMacに届くことを確認 |
| 🟡 | モックWebSocket実装 | あなた | 30秒ごとにランダム動揺レベルを配信 |
| 🟢 | 初心者用タスク準備 | あなた | コメント仕込み済みの`VibrationEffect.tsx` |

---

## 役割分担（ハッカソン当日）

### あなたが死守

- `useBackendWS.ts`（WebSocket接続・データパース・非同期処理）
- Gemini Live APIのプロンプトエンジニアリング・Tool Use制御
- 動揺率エンジン（バックエンド）

### 初心者に振る

1. `docker compose up` で環境を立てる
2. `VibrationEffect.tsx` の動揺エフェクトをいじる（`agitationLevel` 0〜100を受け取るだけ）
3. 占い結果テキストのタイポグラフィ・アニメーション調整

---

## リスクと対策

| リスク | 対策 |
|--------|------|
| Gemini Live API が当日初見 | **事前にPoC必須**。セッション管理・割り込みまで検証する |
| Dockerホットリロード設定ミス | `volumes`設定をスキャフォールド時に必ず確認。当日前に動作確認済みにする |
| 音声処理の複雑化 | フロントは「AIが喋っているか」「テキスト」を受け取るだけ。音声バイナリはバックエンドで完結 |
| カービィ素材が間に合わない | CSSモックで代替可能な構成にしておく |
| センサーが0/1しか返せない | 動揺率エンジンでスライディングウィンドウ集計。精度より反応速度を優先 |
