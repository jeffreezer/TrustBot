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
# This makes the first `docker compose up --build` heavier (downloads BGE-M3 plus the
# small reranker) but means the running container has no network dependency and no
# first-request download. The reranker (~80 MB) backs Phase 3 hybrid retrieval. These
# layers depend only on the stable installs above, so they survive requirements.txt edits.
#
# Then prune redundant duplicate weight formats from the baked HF cache to shrink the
# image, IN THE SAME RUN as the bake so the bytes actually leave the layer (a delete in a
# later layer wouldn't reclaim space). Hugging Face can cache more than one weight format
# per model — e.g. BGE-M3 ships pytorch_model.bin while a bot auto-converts a
# model.safetensors into a *separate, weight-only* snapshot — but only ONE is ever loaded:
# the weight in the loadable snapshot (the one carrying config.json). We keep every blob
# referenced by a config.json-bearing snapshot and delete other weight blobs (~2 GB for
# BGE-M3's orphan safetensors). Keyed on config.json, not refs/main, because pinning by
# commit SHA doesn't write a refs/main — so this prunes correctly whether pinned or not.
# Conservative: never hardcodes a model/format, skips a model with no loadable snapshot,
# only touches blobs >= 50 MB, never removes a loaded weight, config, or tokenizer.
ARG EMBEDDING_MODEL=BAAI/bge-m3
ARG RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
# Pin to explicit upstream commit revisions so the bake is reproducible + tamper-evident
# (not whatever each repo's `main` happens to point at). These MUST equal the runtime
# revisions in config.py (EMBEDDING_MODEL_REVISION / RERANKER_MODEL_REVISION) or the
# container will try to fetch a different revision and fail offline; docker-compose drives
# the build arg and the runtime env from the same variable to keep them in lockstep.
ARG EMBEDDING_MODEL_REVISION=5617a9f61b028005a4858fdac845db406aefb181
ARG RERANKER_MODEL_REVISION=c5ee24cb16019beea0893ab7796b1df96625c6b8
ENV HF_HOME=/app/.hf_cache
# The ARGs above are exposed to this RUN as env vars and read by bake_models.sh. Using a
# script file (not a Dockerfile heredoc) keeps this builder-agnostic — it builds the same
# on local Docker and on Cloud Build, with no BuildKit syntax directive required.
COPY bake_models.sh ./
RUN sh bake_models.sh

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
# Seed corpus, baked in for Cloud Run (which has no host bind-mount). Empty placeholder
# locally — docker-compose mounts ../seed over /seed at runtime; deploy.sh populates
# seed_bundle/ from the repo seed before the cloud build. SEED_DATA_DIR=/seed/northwind_ai.
COPY seed_bundle/ /seed/

RUN chmod +x entrypoint.sh

EXPOSE 8000
# Migrate + seed (idempotent) + serve. See entrypoint.sh.
CMD ["./entrypoint.sh"]
