# Prompt Refactor: フェーズ廃止・agitation純粋反応型 実装プラン

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `TwoStageSessionManager` のフェーズ管理を廃止し、agitation の level/trend だけで応答スタイルを動的に決定する Cold Reading ベースのプロンプト設計に書き換える。

**Architecture:** Stage1 は Cold Reading のバーナム効果・レインボーラスを活用した感情仮説投下プロンプトに統一。Stage2 は agitation の level/trend を5段階にマッピングして断言強度を変え、必ず問いかけで終わる。フェーズ関連コード（PhaseEnum, PHASE_CONFIG, _phase, _phase_turns, _advance_phase_if_needed）を全削除。

**Tech Stack:** Python, FastAPI, google-genai, pytest-asyncio

設計ドキュメント: `docs/plans/2026-03-14-prompt-design.md`

---

### Task 1: フェーズ関連テストを削除し、新しいテストを書く（TDD の第一歩）

**Files:**
- Modify: `backend/tests/test_two_stage_session.py`

既存のフェーズ依存テストを削除し、新しい振る舞いのテストを追加する。
テストが「まだ通らない状態」で終わること（実装は Task 2 で行う）。

**Step 1: フェーズ関連テストを削除する**

`backend/tests/test_two_stage_session.py` から以下の関数を削除する:

```
- test_phase_enum_has_four_phases
- test_phase_config_has_all_phases
- test_initial_phase_is_intro
- test_advance_phase_on_agitation_threshold
- test_advance_phase_on_max_turns
- test_no_advance_when_min_turns_not_met
- test_climax_does_not_advance
- test_build_stage1_system_returns_phase_prompt
- test_build_stage1_system_injects_history
```

また、ファイル先頭の import から `PhaseEnum, PHASE_CONFIG` を削除する:

```python
# 削除する行:
from src.two_stage_session import PhaseEnum, PHASE_CONFIG
```

**Step 2: 新しいテストを追加する**

`backend/tests/test_two_stage_session.py` の末尾に追加:

```python
# --- Stage1 system prompt tests ---

def test_build_stage1_system_contains_cold_reading_instructions():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    system = manager._build_stage1_system()
    assert "ぱむぱむ" in system
    assert "感情線" in system  # 手相の具体的な線への言及
    assert "仮説" in system or "ではないですか" in system  # 仮説投下スタイル


def test_build_stage1_system_injects_history():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    manager._history = [
        {"role": "user", "parts": [{"text": "恋愛について聞きたい"}]},
        {"role": "model", "parts": [{"text": "感情線に流れが見えます"}]},
    ]
    system = manager._build_stage1_system()
    assert "恋愛について聞きたい" in system
    assert "感情線に流れが見えます" in system


def test_build_stage1_system_no_phase_mentions():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    system = manager._build_stage1_system()
    # フェーズ名が残っていないことを確認
    for word in ["INTRO", "CORE", "HYPE", "CLIMAX", "フェーズ"]:
        assert word not in system


# --- Stage2 prompt tests ---

def test_build_stage2_prompt_low_agitation():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=20, trend="stable", stage1_text="何かが見えます")
    assert "微か" in prompt or "暗示" in prompt or "0〜30" in prompt or "level" in prompt


def test_build_stage2_prompt_high_rising_agitation():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=75, trend="rising", stage1_text="あなたは孤独です")
    assert "断言" in prompt or "言い切" in prompt or "60〜80" in prompt


def test_build_stage2_prompt_max_agitation():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=85, trend="rising", stage1_text="隠せません")
    assert "80" in prompt or "完全" in prompt or "畳み掛け" in prompt


def test_build_stage2_prompt_falling_agitation():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=65, trend="falling", stage1_text="体が覚えています")
    assert "落ち着こう" in prompt or "falling" in prompt or "逃げ" in prompt


def test_build_stage2_prompt_ends_with_question_rule():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    prompt = manager._build_stage2_prompt(level=50, trend="rising", stage1_text="何か感じます")
    # 問いかけで終わるルールがプロンプトに含まれていること
    assert "問いかけ" in prompt or "？" in prompt or "疑問" in prompt


def test_build_stage2_prompt_contains_stage1_text():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    stage1 = "あなたの感情線には秘密が刻まれています"
    prompt = manager._build_stage2_prompt(level=40, trend="rising", stage1_text=stage1)
    assert stage1 in prompt


# --- Integration: no phase attributes ---

def test_manager_has_no_phase_attributes():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    assert not hasattr(manager, "_phase")
    assert not hasattr(manager, "_phase_turns")
```

**Step 3: テストが失敗することを確認する**

```bash
cd /Users/kubotadaichi/dev/github/PalmPalm/backend
uv run pytest tests/test_two_stage_session.py -v
```

期待: 新しいテスト群が FAIL（`_build_stage2_prompt` 未定義、`_phase` が存在するなど）
既存の `test_receive_audio_*` と WAV helper テストは引き続き PASS であること。

**Step 4: コミット**

```bash
git add backend/tests/test_two_stage_session.py
git commit -m "test: replace phase tests with cold-reading agitation tests"
```

---

### Task 2: two_stage_session.py のフェーズ関連コードを削除し新プロンプトを実装する

**Files:**
- Modify: `backend/src/two_stage_session.py`

**Step 1: フェーズ関連コードを削除する**

以下をすべて削除する:

```python
# 削除対象:
class PhaseEnum(enum.Enum): ...          # クラス全体
PHASE_CONFIG = { ... }                   # dict全体
_PHASE_ORDER = [...]                     # リスト
STAGE1_SYSTEM = "..."                    # 定数
STAGE2_SYSTEM = "..."                    # 定数

# TwoStageSessionManager.__init__ 内:
self._phase: PhaseEnum = PhaseEnum.INTRO
self._phase_turns: int = 0

# メソッド全体:
def _advance_phase_if_needed(self, agitation_level: int) -> None: ...
```

`enum` の import も不要になるので削除:
```python
# 削除:
import enum
```

**Step 2: 新しいプロンプト定数を追加する**

`two_stage_session.py` の定数セクション（`MODEL = ...` の後）に追加:

```python
STAGE1_SYSTEM_BASE = """\
あなたはAI手相占い師「ぱむぱむ」です。

【手相読みの姿勢】
手の感情線・運命線・頭脳線・生命線を具体的に言及しながら語ること。
最初は広い仮説を投げること（例:「あなたは人前では強く見せているが、内側では違う面がある」）。
会話が進むにつれてユーザーの感情を絞り込む。

【会話の方針】
- ユーザーが言ったことの「裏にある感情」を推測して名指しする
- 断言は避け、「〜ではないですか」「〜が見えます」という形で仮説として語る
- 前のターンの発言と矛盾しないこと
- 神秘的かつ低いトーンで、2文以内で語る

【出力形式（厳守）】
<user_said>相手の発言を1文で要約</user_said>
<response>占い師の応答（2文以内）</response>
"""

STAGE2_SYSTEM_TEMPLATE = """\
あなたはAI手相占い師「ぱむぱむ」です。
手に触れるセンサーが今 level={level}%, trend={trend} を示しています。
これは意識的な反応ではなく、無意識の身体が正直に答えているものです。

直前の発言: 「{stage1_text}」

以下の強度で応じてください:

■ level 0〜30（反応薄）
  「何かが微かに動いています」程度の暗示にとどめる。断言しない。

■ level 30〜60, trend=rising（反応あり・上昇中）
  「体が反応しました」として、直前の仮説を確信に変える。

■ level 60〜80, trend=rising（強い反応・上昇中）
  感情を名指しで断言する。「それは○○への恐れです」のように言い切る。

■ level 60〜80, trend=falling（強い反応・落ち着きかけ）
  「今落ち着こうとしていますね——でも体は覚えています」と逃げを指摘する。

■ level 80以上（最大反応）
  「隠せていません」として完全断言・畳み掛ける。

【必須ルール】
- 必ず問いかけの文章（？で終わる）で締めること
- 1〜2文で完結させること
"""
```

**Step 3: `_build_stage1_system()` を書き換える**

既存の `_build_stage1_system()` を以下で置き換える:

```python
def _build_stage1_system(self) -> str:
    if not self._history:
        return STAGE1_SYSTEM_BASE
    pairs = [
        {
            "user": self._history[i]["parts"][0]["text"],
            "model": self._history[i + 1]["parts"][0]["text"],
        }
        for i in range(0, len(self._history) - 1, 2)
        if self._history[i]["role"] == "user"
        and self._history[i + 1]["role"] == "model"
    ]
    recent = pairs[-6:]
    history_lines = "\n".join(
        f"- ターン{i+1}: (相手) {h['user']} / (あなた) {h['model']}"
        for i, h in enumerate(recent)
    )
    return (
        f"{STAGE1_SYSTEM_BASE}\n"
        f"【これまでの会話】\n{history_lines}\n"
        "前の発言と矛盾しないこと。"
    )
```

**Step 4: `_build_stage2_prompt()` を新規追加する**

`_build_stage1_system()` の直後に追加:

```python
def _build_stage2_prompt(self, level: int, trend: str, stage1_text: str) -> str:
    return STAGE2_SYSTEM_TEMPLATE.format(
        level=level,
        trend=trend,
        stage1_text=stage1_text,
    )
```

**Step 5: `receive_audio()` の Stage2 呼び出しを書き換える**

`receive_audio()` 内の Stage2 生成部分を変更する。

変更前:
```python
stage2_prompt = (
    f"動揺データ: level={snapshot['level']}, trend={snapshot['trend']}。"
    f"直前の発言: {stage1_text} "
    "この情報を踏まえ、当たっている実感を強める補足をしてください。"
)
contents2 = self._history + [
    {"role": "user", "parts": [{"text": stage2_prompt}]}
]
try:
    stage2_text = await self._generate_text(contents2, STAGE2_SYSTEM)
```

変更後:
```python
stage2_system = self._build_stage2_prompt(
    level=snapshot["level"],
    trend=snapshot["trend"],
    stage1_text=stage1_text,
)
contents2 = self._history + [
    {"role": "user", "parts": [{"text": "次の応答をしてください。"}]}
]
try:
    stage2_text = await self._generate_text(contents2, stage2_system)
```

また、`receive_audio()` 内のフェーズ関連コードを削除する:

```python
# 削除:
self._phase_turns += 1
self._advance_phase_if_needed(snapshot["level"])
```

**Step 6: テストを実行する**

```bash
cd /Users/kubotadaichi/dev/github/PalmPalm/backend
uv run pytest tests/test_two_stage_session.py -v
```

期待: 全テスト PASS

**Step 7: コミット**

```bash
git add backend/src/two_stage_session.py
git commit -m "feat: replace phase system with agitation-driven cold reading prompts"
```

---

### Task 3: 全テストスイートを通す

**Files:**
- Read: `backend/tests/` 全体

**Step 1: 全テストを実行する**

```bash
cd /Users/kubotadaichi/dev/github/PalmPalm/backend
uv run pytest tests/ -v
```

期待: 全テスト PASS

失敗するテストがあれば原因を確認する。よくある原因:
- `mock_gemini_session.py` 側が `PhaseEnum` を import していないか確認
- `main.py` が `PhaseEnum` を import していないか確認

**Step 2: 依存箇所があれば修正する**

```bash
grep -r "PhaseEnum\|PHASE_CONFIG\|_phase_turns\|_advance_phase" \
  /Users/kubotadaichi/dev/github/PalmPalm/backend/src/
```

見つかった箇所があれば削除または修正する。

**Step 3: 再度全テストを実行して PASS を確認する**

```bash
cd /Users/kubotadaichi/dev/github/PalmPalm/backend
uv run pytest tests/ -v
```

期待: 全テスト PASS

**Step 4: コミット**

```bash
git add -u backend/
git commit -m "fix: remove remaining phase references from codebase"
```

---

### Task 4: 動作確認（手動）

**Step 1: Docker を起動する**

```bash
cd /Users/kubotadaichi/dev/github/PalmPalm
docker compose up --build
```

**Step 2: セッション開始を curl で確認する**

```bash
curl -N http://localhost:8000/api/session/start
```

期待: SSE で `audio_url` を含むイベントが返ってくる

**Step 3: ブラウザで動作確認する**

`http://localhost:5173` を開いてマイクで話しかけ、以下を確認する:
- Stage1 の音声が再生される（手相に関する仮説的な語りかけ）
- Stage2 の音声が問いかけで終わっている
- ターンが自然に続く

**Step 4: 最終コミット**

```bash
git add -A
git commit -m "chore: verify prompt refactor end-to-end"
```
