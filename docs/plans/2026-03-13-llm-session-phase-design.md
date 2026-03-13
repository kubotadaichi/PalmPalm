# LLMセッション フェーズ管理設計 (2026-03-13)

## 概要

`TwoStageSessionManager` に占いの「フェーズ（起承転結）」を導入し、
会話が自然に展開するセッション管理を実現する。

---

## 課題

- 現状の `STAGE1_SYSTEM` / `STAGE2_SYSTEM` は毎ターン固定プロンプトのため、占いの雰囲気が単調になりキャラクターが崩れやすい
- `_history` に音声バイナリが含まれ重く、ユーザー発言の文脈が後続ターンで失われる

---

## 設計方針

- **フェーズ状態機械 + agitation駆動の遷移** を採用
- フェーズ名は固定（4種）、各フェーズ内のターン数は agitation に応じて動的に変化
- Stage1 の1回のGeminiコールで「ユーザー発言要約（文字起こし）」と「占い師応答テキスト」を同時生成し、履歴をテキストのみで保持

---

## フェーズ定義

| フェーズ | 役割 | min_turns | max_turns | agitation_threshold |
|---|---|---|---|---|
| INTRO | 神秘的な前置き・手相を見始める | 1 | 3 | 30 |
| CORE | 運命・性格・過去を読み解く | 2 | 4 | 50 |
| HYPE | 「当たっている！」煽り開始 | 1 | 3 | 70 |
| CLIMAX | 畳み掛け（最終フェーズ） | — | — | — |

### 遷移ルール

```
agitation.level >= threshold AND _phase_turns >= min_turns → 次フェーズへ
_phase_turns >= max_turns                                  → 強制的に次フェーズへ
```

遷移判定タイミング: Stage2のagitationスナップショット取得後

---

## 状態追加

```python
class TwoStageSessionManager:
    _phase: PhaseEnum       # INTRO / CORE / HYPE / CLIMAX
    _phase_turns: int       # 現フェーズ内のターン数
    _history: list[dict]    # {"user": str, "model": str} テキストのみ
```

---

## 1ターンのフロー

```
1. Stage1コール (音声入力)
   - システムプロンプト: フェーズ別プロンプト + 直近履歴（最大4件）を注入
   - 出力: <user_said>ユーザー発言要約</user_said>
           <response>占い師の応答テキスト</response>
   → user_summary, stage1_text をパース

2. TTS(stage1_text) → stage1_audio_url  [並列で agitation 取得]

3. フェーズ遷移判定
   - agitation.level >= threshold AND _phase_turns >= min_turns → advance
   - _phase_turns >= max_turns → force advance

4. Stage2コール (テキスト入力)
   - システムプロンプト: 現フェーズのトーン + agitation情報
   → stage2_text

5. TTS(stage2_text) → stage2_audio_url

6. _history に {"user": user_summary, "model": stage1_text + stage2_text} 追記
   _phase_turns += 1

7. SSE yield: stage1 → stage2 → turn_end
```

---

## フェーズ別 Stage1 システムプロンプト

```
INTRO:
「あなたはAI手相占い師「ぱむぱむ」です。
初めて手を見る緊張感と神秘的な雰囲気を出しながら、
手相から何かが見えてきた…という前置きを2文で語ってください。」

CORE:
「あなたはAI手相占い師「ぱむぱむ」です。
運命線・感情線から、この人の性格・過去・隠された本音を
低くゆっくりと確信を持って2文で読み解いてください。」

HYPE:
「あなたはAI手相占い師「ぱむぱむ」です。
占いが当たっていると確信してきた。
相手の反応を指摘しながら、テンションを上げて1〜2文で煽ってください。」

CLIMAX:
「あなたはAI手相占い師「ぱむぱむ」です。
すべてが繋がった。感情的に畳み掛けて、
この占いが完全に正しいと断言する1〜2文を叫ぶように語ってください。」
```

各フェーズのプロンプトには直近4ターンの履歴を追記:
```
これまでの発言:
- ターン1: (user) ... / (model) ...
- ターン2: ...
前の発言と矛盾しないこと。
```

---

## Stage2 システムプロンプトテンプレート

```
「あなたはAI手相占い師「ぱむぱむ」です。
現在のフェーズ: {phase}。
動揺データ(level={level}, trend={trend})を証拠として使い、
フェーズのトーンを維持しながら追い込みコメントを1〜2文で返してください。」
```

---

## 変更対象ファイル

- `backend/src/two_stage_session.py` — メイン実装
- `backend/tests/test_two_stage_session.py` — テスト追加

---

## 既存インターフェースへの影響

- `POST /api/audio` のSSEレスポンス形式は変わらない（stage1/stage2/turn_end）
- フロントエンド変更不要
