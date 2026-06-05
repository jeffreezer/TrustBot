FROM python:3.12-slim

WORKDIR /app

# Heavy, stable model libraries first, as their own layer, so the model bake below is
# cached independently of the fast-changing requirements.txt: a dependency edit no
# longer re-downloads the ~1-2 GB model. CPU-only torch (from PyTorch's CPU index) is
# installed before sentence-transformers so the latter finds torch already satisfied
# and never pulls the multi-GB CUDA build. CPU inference is expected at demo scale.
#
# NOTE: these pins MUST stay in sync with requirements.txt. If they drift, the
# `pip install -r requirements.txt` step below reinstalls them and defeats this caching.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu "torch==2.*"
RUN pip install --no-cache-dir "sentence-transformers==3.*"

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

# Remaining Python deps. Changing requirements.txt re-runs only this layer (torch and
# sentence-transformers are already satisfied from the pinned installs above), not the
# model bake. psycopg[binary] needs no build tools, so system deps stay minimal.
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
