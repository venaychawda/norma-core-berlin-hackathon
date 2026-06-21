FROM python:3.11-slim

WORKDIR /app
RUN pip install --no-cache-dir uv

COPY pyproject.toml uv.lock ./
COPY smolvla/ ./smolvla/
COPY scripts/ ./scripts/
COPY data/ ./datasets/
COPY run.sh .
RUN chmod +x run.sh

RUN uv sync

ENV HF_HOME=/app/.cache/huggingface
EXPOSE 7860

CMD ["./run.sh"]
