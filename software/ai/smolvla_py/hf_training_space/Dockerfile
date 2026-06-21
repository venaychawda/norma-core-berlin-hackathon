FROM python:3.11-slim

WORKDIR /app

RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY smolvla/ ./smolvla/
COPY scripts/train_hf_space.py ./scripts/train_hf_space.py

RUN uv sync

ENV HF_HOME=/app/.cache/huggingface

COPY run.sh .
RUN chmod +x run.sh

CMD ["./run.sh"]
