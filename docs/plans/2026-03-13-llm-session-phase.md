# LLMセッション フェーズ管理 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** `TwoStageSessionManager` に4フェーズ（INTRO→CORE→HYPE→CLIMAX）の状態機械を追加し、agitation連動でフェーズが進行する占いセッションを実現する。

**Architecture:** `PhaseEnum` + フェーズ設定辞書で各フェーズのプロンプト・遷移条件を定義。Stage1コールで音声からユーザー発言要約と占い師応答を同時生成し、テキストのみの履歴に保存。Stage2コール後にagitationを見てフェーズ遷移判定。

**Tech Stack:** Python, FastAPI, google-genai, pytest-asyncio

---

### Task 1: PhaseEnum とフェーズ設定を追加

**Files:**
- Modify: `backend/src/two_stage_session.py`

**Step 1: フェーズ定義をファイル冒頭に追加するテストを書く**

`backend/tests/test_two_stage_session.py` に追記:

```python
from src.two_stage_session import PhaseEnum, PHASE_CONFIG

def test_phase_enum_has_four_phases():
    assert list(PhaseEnum) == [
        PhaseEnum.INTRO, PhaseEnum.CORE, PhaseEnum.HYPE, PhaseEnum.CLIMAX
    ]

def test_phase_config_has_all_phases():
    for phase in PhaseEnum:
        cfg = PHASE_CONFIG[phase]
        assert "system" in cfg
        assert "min_turns" in cfg
        assert "max_turns" in cfg or phase == PhaseEnum.CLIMAX
        assert "agitation_threshold" in cfg or phase == PhaseEnum.CLIMAX
```

**Step 2: テスト失敗を確認**

```bash
cd backend && uv run pytest tests/test_two_stage_session.py::test_phase_enum_has_four_phases -v
```
Expected: FAIL with `ImportError`

**Step 3: 実装を追加**

`backend/src/two_stage_session.py` の `MODEL = ...` より前に追記:

```python
import enum

class PhaseEnum(enum.Enum):
    INTRO = "intro"
    CORE = "core"
    HYPE = "hype"
    CLIMAX = "climax"

PHASE_CONFIG = {
    PhaseEnum.INTRO: {
        "system": (
            "あなたはAI手相占い師「ぱむぱむ」です。"
            "初めて手を見る緊張感と神秘的な雰囲気を出しながら、"
            "手相から何かが見えてきた…という前置きを2文で語ってください。"
        ),
        "min_turns": 1,
        "max_turns": 3,
        "agitation_threshold": 30,
    },
    PhaseEnum.CORE: {
        "system": (
            "あなたはAI手相占い師「ぱむぱむ」です。"
            "運命線・感情線から、この人の性格・過去・隠された本音を"
            "低くゆっくりと確信を持って2文で読み解いてください。"
        ),
        "min_turns": 2,
        "max_turns": 4,
        "agitation_threshold": 50,
    },
    PhaseEnum.HYPE: {
        "system": (
            "あなたはAI手相占い師「ぱむぱむ」です。"
            "占いが当たっていると確信してきた。"
            "相手の反応を指摘しながら、テンションを上げて1〜2文で煽ってください。"
        ),
        "min_turns": 1,
        "max_turns": 3,
        "agitation_threshold": 70,
    },
    PhaseEnum.CLIMAX: {
        "system": (
            "あなたはAI手相占い師「ぱむぱむ」です。"
            "すべてが繋がった。感情的に畳み掛けて、"
            "この占いが完全に正しいと断言する1〜2文を叫ぶように語ってください。"
        ),
    },
}
```

**Step 4: テスト通過を確認**

```bash
cd backend && uv run pytest tests/test_two_stage_session.py::test_phase_enum_has_four_phases tests/test_two_stage_session.py::test_phase_config_has_all_phases -v
```
Expected: 2 passed

**Step 5: コミット**

```bash
git add backend/src/two_stage_session.py backend/tests/test_two_stage_session.py
git commit -m "feat: add PhaseEnum and PHASE_CONFIG"
```

---

### Task 2: TwoStageSessionManager にフェーズ状態を追加

**Files:**
- Modify: `backend/src/two_stage_session.py`

**Step 1: フェーズ状態の初期化テストを書く**

```python
def test_initial_phase_is_intro():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    assert manager._phase == PhaseEnum.INTRO
    assert manager._phase_turns == 0
```

**Step 2: テスト失敗を確認**

```bash
cd backend && uv run pytest tests/test_two_stage_session.py::test_initial_phase_is_intro -v
```
Expected: FAIL

**Step 3: `__init__` に状態追加**

`TwoStageSessionManager.__init__` に追記:

```python
self._phase: PhaseEnum = PhaseEnum.INTRO
self._phase_turns: int = 0
self._history: list[dict] = []  # {"user": str, "model": str}
```

既存の `self._history: list[dict] = []` は置き換える（型ヒントだけ変わる）。

**Step 4: テスト通過を確認**

```bash
cd backend && uv run pytest tests/test_two_stage_session.py::test_initial_phase_is_intro -v
```
Expected: PASS

**Step 5: コミット**

```bash
git add backend/src/two_stage_session.py backend/tests/test_two_stage_session.py
git commit -m "feat: add phase state to TwoStageSessionManager"
```

---

### Task 3: フェーズ遷移ロジックを実装

**Files:**
- Modify: `backend/src/two_stage_session.py`

**Step 1: フェーズ遷移テストを書く**

```python
def test_advance_phase_on_agitation_threshold():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    manager._phase = PhaseEnum.INTRO
    manager._phase_turns = 1  # min_turns=1 を満たす
    manager._advance_phase_if_needed(agitation_level=35)  # threshold=30 超
    assert manager._phase == PhaseEnum.CORE
    assert manager._phase_turns == 0

def test_advance_phase_on_max_turns():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    manager._phase = PhaseEnum.INTRO
    manager._phase_turns = 3  # max_turns=3 に達した
    manager._advance_phase_if_needed(agitation_level=0)  # threshold未満でも進む
    assert manager._phase == PhaseEnum.CORE

def test_no_advance_when_min_turns_not_met():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    manager._phase = PhaseEnum.INTRO
    manager._phase_turns = 0  # min_turns=1 未満
    manager._advance_phase_if_needed(agitation_level=100)
    assert manager._phase == PhaseEnum.INTRO

def test_climax_does_not_advance():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    manager._phase = PhaseEnum.CLIMAX
    manager._phase_turns = 99
    manager._advance_phase_if_needed(agitation_level=100)
    assert manager._phase == PhaseEnum.CLIMAX
```

**Step 2: テスト失敗を確認**

```bash
cd backend && uv run pytest tests/test_two_stage_session.py::test_advance_phase_on_agitation_threshold -v
```
Expected: FAIL with `AttributeError`

**Step 3: `_advance_phase_if_needed` を実装**

`TwoStageSessionManager` にメソッド追加:

```python
_PHASE_ORDER = [PhaseEnum.INTRO, PhaseEnum.CORE, PhaseEnum.HYPE, PhaseEnum.CLIMAX]

def _advance_phase_if_needed(self, agitation_level: int) -> None:
    if self._phase == PhaseEnum.CLIMAX:
        return
    cfg = PHASE_CONFIG[self._phase]
    min_turns = cfg.get("min_turns", 0)
    max_turns = cfg.get("max_turns", float("inf"))
    threshold = cfg.get("agitation_threshold", 100)
    should_advance = (
        self._phase_turns >= max_turns
        or (self._phase_turns >= min_turns and agitation_level >= threshold)
    )
    if should_advance:
        idx = _PHASE_ORDER.index(self._phase)
        self._phase = _PHASE_ORDER[idx + 1]
        self._phase_turns = 0
```

**Step 4: テスト通過を確認**

```bash
cd backend && uv run pytest tests/test_two_stage_session.py -k "advance_phase" -v
```
Expected: 4 passed

**Step 5: コミット**

```bash
git add backend/src/two_stage_session.py backend/tests/test_two_stage_session.py
git commit -m "feat: implement phase transition logic"
```

---

### Task 4: Stage1でユーザー発言要約と応答を同時生成

**Files:**
- Modify: `backend/src/two_stage_session.py`

**Step 1: フェーズ別システムプロンプト生成のテストを書く**

```python
def test_build_stage1_system_returns_phase_prompt():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    manager._phase = PhaseEnum.INTRO
    system = manager._build_stage1_system()
    assert "ぱむぱむ" in system
    assert "前置き" in system  # INTROプロンプトの一部

def test_build_stage1_system_injects_history():
    manager = TwoStageSessionManager(client=_FakeClient([]))
    manager._history = [{"user": "占いについて", "model": "手相が見えます"}]
    system = manager._build_stage1_system()
    assert "占いについて" in system
```

**Step 2: テスト失敗を確認**

```bash
cd backend && uv run pytest tests/test_two_stage_session.py -k "build_stage1_system" -v
```
Expected: FAIL

**Step 3: `_build_stage1_system` を実装**

```python
def _build_stage1_system(self) -> str:
    base = PHASE_CONFIG[self._phase]["system"]
    recent = self._history[-4:]
    if not recent:
        return base
    history_lines = "\n".join(
        f"- ターン{i+1}: (あなた) {h['model']} / (相手) {h['user']}"
        for i, h in enumerate(recent)
    )
    return (
        f"{base}\n\n"
        f"これまでの会話:\n{history_lines}\n"
        "前の発言と矛盾せず、会話の流れを自然に続けること。"
    )
```

**Step 4: Stage1プロンプトを変更してuser_said/responseを同時生成**

`receive_audio` の stage1 部分を修正:

```python
# 変更前
stage1_prompt = (
    "占いの続きを一言ください。"
    "まだ相手を煽りすぎず、神秘的なトーンを維持してください。"
)

# 変更後
stage1_prompt = (
    "以下の2つを必ず出力してください:\n"
    "<user_said>相手が言ったことを1文で要約</user_said>\n"
    "<response>占い師としての応答を2文</response>"
)
```

`_generate_text` の結果をパースするヘルパーを追加:

```python
import re

def _parse_stage1(raw: str) -> tuple[str, str]:
    """<user_said>...</user_said> と <response>...</response> を抽出。"""
    user_said = ""
    response = raw
    m_user = re.search(r"<user_said>(.*?)</user_said>", raw, re.DOTALL)
    m_resp = re.search(r"<response>(.*?)</response>", raw, re.DOTALL)
    if m_user:
        user_said = m_user.group(1).strip()
    if m_resp:
        response = m_resp.group(1).strip()
    return user_said, response
```

**Step 5: `receive_audio` のstage1呼び出し箇所を修正**

```python
# 変更前
stage1_text = await self._generate_text(contents1, STAGE1_SYSTEM)

# 変更後
stage1_raw = await self._generate_text(contents1, self._build_stage1_system())
user_summary, stage1_text = _parse_stage1(stage1_raw)
```

**Step 6: テスト追加して通過確認**

```python
def test_parse_stage1_extracts_tags():
    from src.two_stage_session import _parse_stage1
    raw = "<user_said>恋愛について聞いた</user_said><response>手相に流れが見える</response>"
    user, response = _parse_stage1(raw)
    assert user == "恋愛について聞いた"
    assert response == "手相に流れが見える"

def test_parse_stage1_fallback_when_no_tags():
    from src.two_stage_session import _parse_stage1
    raw = "タグなしのテキスト"
    user, response = _parse_stage1(raw)
    assert user == ""
    assert response == "タグなしのテキスト"
```

```bash
cd backend && uv run pytest tests/test_two_stage_session.py -k "parse_stage1 or build_stage1" -v
```
Expected: 4 passed

**Step 7: コミット**

```bash
git add backend/src/two_stage_session.py backend/tests/test_two_stage_session.py
git commit -m "feat: stage1 outputs user_said+response, phase-specific system prompt"
```

---

### Task 5: 履歴をテキストのみに変更 + Stage2にフェーズトーンを渡す

**Files:**
- Modify: `backend/src/two_stage_session.py`

**Step 1: 履歴保存のテストを書く**

```python
@pytest.mark.asyncio
async def test_history_stores_text_after_turn():
    responses = [
        "<user_said>質問した</user_said><response>stage1応答</response>",
        "stage2応答",
    ]
    client = _FakeClient(responses)
    manager = TwoStageSessionManager(client=client)
    manager._generate_tts = lambda text: _noop_tts(text)

    async for _ in manager.receive_audio(b"fake", "audio/webm"):
        pass

    assert len(manager._history) == 1
    assert manager._history[0]["user"] == "質問した"
    assert "stage1応答" in manager._history[0]["model"]
    assert "stage2応答" in manager._history[0]["model"]
```

**Step 2: テスト失敗を確認**

```bash
cd backend && uv run pytest tests/test_two_stage_session.py::test_history_stores_text_after_turn -v
```
Expected: FAIL

**Step 3: `receive_audio` の履歴保存部分を修正**

```python
# 変更前
self._history.extend([
    {"role": "user", "parts": [audio_part]},
    {"role": "model", "parts": [{"text": f"{stage1_text} {stage2_text}"}]},
])
self._history = self._history[-12:]

# 変更後
self._history.append({
    "user": user_summary,
    "model": f"{stage1_text} {stage2_text}",
})
self._history = self._history[-8:]
```

**Step 4: Stage2のcontents/systemを修正**

```python
# 変更前
contents2 = self._history + [
    {"role": "user", "parts": [{"text": stage2_prompt}]}
]
stage2_text = await self._generate_text(contents2, STAGE2_SYSTEM)

# 変更後
stage2_system = (
    f"あなたはAI手相占い師「ぱむぱむ」です。"
    f"現在のフェーズ: {self._phase.value}。"
    f"動揺データ(level={snapshot['level']}, trend={snapshot['trend']})を証拠として使い、"
    "フェーズのトーンを維持しながら追い込みコメントを1〜2文で返してください。"
)
contents2 = [{"role": "user", "parts": [{"text": stage2_prompt}]}]
stage2_text = await self._generate_text(contents2, stage2_system)
```

**Step 5: フェーズ遷移をstage2後に呼ぶ**

`yield {"type": "stage2", ...}` の直前に追加:

```python
self._advance_phase_if_needed(snapshot["level"])
self._phase_turns += 1
```

**Step 6: テスト通過を確認（全テスト）**

```bash
cd backend && uv run pytest tests/ -v
```
Expected: 全テスト PASS

**Step 7: コミット**

```bash
git add backend/src/two_stage_session.py backend/tests/test_two_stage_session.py
git commit -m "feat: text-only history, phase-aware stage2, phase advance after turn"
```

---

### Task 6: 統合動作確認

**Step 1: 不要な定数を削除**

`STAGE1_SYSTEM` と `STAGE2_SYSTEM` の定数（使われなくなったもの）を削除。

**Step 2: 全テスト通過確認**

```bash
cd backend && uv run pytest tests/ -v
```
Expected: 全テスト PASS

**Step 3: 手動動作確認（任意）**

```bash
docker compose up --build
# ブラウザで http://localhost:5173 を開いてセッションを複数ターン進め
# バックエンドログでフェーズ遷移を確認したい場合は two_stage_session.py に
# print(f"[Phase] {self._phase.value}, turns={self._phase_turns}") を追加
```

**Step 4: 最終コミット**

```bash
git add backend/src/two_stage_session.py
git commit -m "chore: remove unused STAGE1_SYSTEM/STAGE2_SYSTEM constants"
```
