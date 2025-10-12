FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    PORT=7860

WORKDIR /workspace

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        git \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && ln -s /root/.local/bin/uv /usr/local/bin/uv

ENV PATH="/root/.local/bin:${PATH}" \
    UV_PROJECT_ENV=.venv \
    UV_PYTHON_DOWNLOADS=none

COPY . .

WORKDIR /workspace/apps/api

RUN uv sync --frozen --no-dev

ENV PATH="/workspace/apps/api/.venv/bin:${PATH}"

EXPOSE ${PORT}

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
