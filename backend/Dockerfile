FROM python:3.11-slim

# PyAudioビルドに必要な最小依存
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential portaudio19-dev \
    && rm -rf /var/lib/apt/lists/*

# uv をインストール
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# 依存関係を先にコピーしてキャッシュを効かせる
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# ソースはvolumesでマウントするのでCOPYしない
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
