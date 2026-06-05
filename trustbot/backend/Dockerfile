FROM python:3.12-slim

WORKDIR /app

# CPU-only torch first, from PyTorch's CPU index, so the sentence-transformers
# install below finds torch already satisfied and never pulls the multi-GB CUDA
# build. CPU inference is expected at demo scale.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.*"

# System deps kept minimal; psycopg[binary] needs no build tools.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Bake the embedding model into the image at build time. This makes the first
# `docker compose up --build` heavier (downloads BGE-M3, ~1-2 GB) but means the
# running container has no network dependency and no first-request download.
ARG EMBEDDING_MODEL=BAAI/bge-m3
ENV HF_HOME=/app/.hf_cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}', device='cpu')"

COPY alembic.ini ./
COPY entrypoint.sh ./
COPY app ./app

RUN chmod +x entrypoint.sh

EXPOSE 8000
# Migrate + seed (idempotent) + serve. See entrypoint.sh.
CMD ["./entrypoint.sh"]
