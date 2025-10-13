FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=7860 \
    HF_HOME=/tmp/hf-cache \
    TRANSFORMERS_CACHE=/tmp/hf-cache \
    TORCH_HOME=/tmp/torch-cache

WORKDIR /workspace

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        build-essential \
        git \
        libgomp1 \
    && rm -rf /var/lib/apt/lists/*

RUN mkdir -p "${HF_HOME}" "${TORCH_HOME}" && chmod -R 777 "${HF_HOME}" "${TORCH_HOME}"

COPY . .

WORKDIR /workspace/apps/api

RUN python -m pip install --upgrade pip setuptools wheel && \
    python -m pip install --no-cache-dir -r requirements.txt

EXPOSE ${PORT}

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "7860"]
