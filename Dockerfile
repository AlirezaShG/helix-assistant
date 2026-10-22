FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1. Dependencies first: changing the code does not reinstall them (layer cache).
COPY requirements.txt .
RUN pip install -r requirements.txt

# 2. Bake the embedding model into the image, so the running container needs no
#    internet access for embeddings (~230 MB, ONNX, CPU only).
ARG EMBEDDING_MODEL=sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
ENV EMBEDDING_MODEL=${EMBEDDING_MODEL} \
    EMBEDDING_CACHE_DIR=/app/models
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBEDDING_MODEL}', cache_dir='/app/models')"

# 3. Code, sample PDFs, database schema, evaluation set and tests.
COPY pytest.ini ./
COPY app ./app
COPY data ./data
COPY scripts ./scripts
COPY evaluation ./evaluation
COPY tests ./tests

# 4. Build the SQLite database and the vector index now, so startup is instant.
#    (At startup the index is rebuilt only if the PDFs or the model changed.)
RUN python -m app.bootstrap

# Run as an unprivileged user.
RUN useradd --create-home appuser && chown -R appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health')"

# --no-access-log: the app logs every request itself (with its duration).
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
