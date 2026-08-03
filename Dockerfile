# Dockerfile
#
# Two-stage build. Stage one installs dependencies (including a CPU-only build
# of torch, which is roughly 200MB instead of the 2GB+ CUDA build you get by
# default), stage two copies just the installed packages and the app.

# ---------- stage 1: build ----------
FROM python:3.11-slim-bookworm AS builder
# NOTE: slim-buster is end of life and has been pulled from the Debian
# archives, so the old base image no longer builds.

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# CPU-only torch keeps the image small; nothing here needs a GPU.
RUN pip install --no-cache-dir \
        --extra-index-url https://download.pytorch.org/whl/cpu \
        -r requirements.txt

# Bake the embedding model into the image so the container does not download
# ~90MB from Hugging Face on every cold start (and still works offline).
ARG EMBEDDING_MODEL=all-MiniLM-L6-v2
ENV HF_HOME=/opt/hf
RUN python -c "from sentence_transformers import SentenceTransformer; \
    SentenceTransformer('${EMBEDDING_MODEL}')"

# ---------- stage 2: runtime ----------
FROM python:3.11-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HF_HOME=/opt/hf

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 appuser

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /opt/hf /opt/hf

COPY --chown=appuser:appuser . .

RUN mkdir -p /app/uploaded_files && chown -R appuser:appuser /app/uploaded_files /opt/hf

USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=90s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]