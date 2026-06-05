# syntax=docker/dockerfile:1
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
# per model — e.g. BGE-M3's `main` revision ships pytorch_model.bin while an auto-converted
# model.safetensors lands on a separate revision — but only ONE is ever loaded: the weight
# referenced by each model's `main`-ref snapshot. We delete large weight blobs NOT
# referenced by `main` (~2 GB for BGE-M3). Conservative and general: keyed on what actually
# loads (never hardcodes a model/format), skips a model with no refs/main, only touches
# blobs >= 50 MB, and never removes the main-referenced weights, configs, or tokenizers.
ARG EMBEDDING_MODEL=BAAI/bge-m3
ARG RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
ENV HF_HOME=/app/.hf_cache
RUN <<'BAKE'
set -eu
python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}', device='cpu')"
python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RERANKER_MODEL}', device='cpu')"
HUB="$HF_HOME/hub"
for model_dir in "$HUB"/models--*; do
    [ -d "$model_dir" ] || continue
    [ -f "$model_dir/refs/main" ] || continue          # only prune when we know what loads
    main_snap="$model_dir/snapshots/$(cat "$model_dir/refs/main")"
    [ -d "$main_snap" ] || continue
    # Blob hashes the main (loaded) snapshot points at — these are kept no matter what.
    keep="$(find "$main_snap" -type l -exec readlink -f {} \; 2>/dev/null \
            | while read -r p; do basename "$p"; done)"
    for blob in "$model_dir"/blobs/*; do
        [ -f "$blob" ] || continue
        bh="$(basename "$blob")"
        case "$keep" in *"$bh"*) continue ;; esac       # referenced by main → keep
        sz="$(stat -c%s "$blob" 2>/dev/null || echo 0)"
        if [ "$sz" -ge 52428800 ]; then                 # >= 50 MB: a redundant weight blob
            echo "pruning redundant weight blob ($sz bytes): $blob"
            rm -f "$blob"
        fi
    done
done
find "$HUB" -xtype l -delete 2>/dev/null || true        # drop now-dangling snapshot symlinks
BAKE

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
