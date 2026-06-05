FROM python:3.12-slim

WORKDIR /app

# Heavy, stable model libraries first, as their own layer, so the model bake below is
# cached independently of the fast-changing requirements.txt: a dependency edit no
# longer re-downloads the ~1-2 GB model. Their pins live in exactly one place —
# requirements-models.txt — which also carries the PyTorch CPU index directive and the
# explicit +cpu torch build, so torch never pulls the multi-GB CUDA build. requirements.txt
# pulls this same file in via `-r`, so the pins can't drift. CPU inference is fine at demo scale.
COPY requirements-models.txt ./
RUN pip install --no-cache-dir -r requirements-models.txt

# Bake the models into the image at build time (needs sentence-transformers, above).
# This makes the first `docker compose up --build` heavier (downloads BGE-M3, ~1-2 GB,
# plus the small reranker) but means the running container has no network dependency and
# no first-request download. The reranker (~80 MB) backs Phase 3 hybrid retrieval. These
# layers depend only on the stable installs above, so they survive requirements.txt edits.
ARG EMBEDDING_MODEL=BAAI/bge-m3
ARG RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
ENV HF_HOME=/app/.hf_cache
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}', device='cpu')"
RUN python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RERANKER_MODEL}', device='cpu')"

# Remaining Python deps. requirements.txt pulls in requirements-models.txt via `-r`, so
# torch and sentence-transformers are already satisfied here (no reinstall, model-bake
# cache intact); only the app deps install. Changing requirements.txt re-runs only this
# layer. psycopg[binary] needs no build tools, so system deps stay minimal.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY alembic.ini ./
COPY entrypoint.sh ./
COPY app ./app
COPY evals ./evals

RUN chmod +x entrypoint.sh

EXPOSE 8000
# Migrate + seed (idempotent) + serve. See entrypoint.sh.
CMD ["./entrypoint.sh"]
