# Mock Setup Design (2026-03-11)

## 目的

Gemini Live APIとRaspberry Piが手元にない状態でも、フロントエンド開発が進められるようにする。
コラボレーターが接続窓口（本番の `GeminiSessionManager`）の実装に集中できるよう、モックと本番実装を明確に分離する。

## 構成変更

```
backend/
  src/
    main.py                  # MOCK_MODEでクラスを切り替えるだけ (変更)
    gemini_session.py        # 本番実装 (コラボレーターが実装, 変更なし)
    mock_gemini_session.py   # 新規: モック実装
docker-compose.yml           # backendサービスを追加 (変更)
```

## MockGeminiSessionManager

`GeminiSessionManager` と同じインターフェースを持つモッククラス。

### `start_session()`

バックグラウンドで2つのループを起動する:

1. **振動モック** (既存): `mock_vibration_loop()` でランダムに `agitation_update` を送信
2. **台本ループ** (新規): 3〜6秒ごとに手相占いテキストをチャンクに分けて `ai_text` として送信。台本が終わったら先頭に戻る。

### `send_push(level, trend)`

動揺急上昇時に「豹変」スクリプトを割り込み送信する。

### 台本

- 通常: 手相占いの口上を数パターン用意（神秘的・低トーン）
- 豹変: 動揺レベルに応じた畳み掛けセリフ数パターン

## main.py の変更

```python
if mock_mode:
    gemini = MockGeminiSessionManager(engine)
else:
    gemini = GeminiSessionManager(engine)
```

`mock_vibration_loop` は `MockGeminiSessionManager.start_session()` 内に移動し、`main.py` をシンプルに保つ。

## docker-compose.yml の変更

backendサービスを追加:
- イメージ: Python + uv でビルド
- 環境変数: `MOCK_MODE=true`、`GEMINI_API_KEY`（モック時は不要だが定義しておく）
- ポート: `8000:8000`
- ホットリロード: `src/` をボリュームマウント

`docker compose up` 一発でfrontend + backendが起動する状態にする。
