#!/bin/sh
# Download (bake) the embedding + reranker models at the pinned revisions, then prune
# redundant duplicate weight formats from the HF cache IN THE SAME step so the bytes
# actually leave the image layer (a delete in a later layer wouldn't reclaim space).
#
# Hugging Face can cache more than one weight format per model — e.g. BGE-M3 ships
# pytorch_model.bin while a bot auto-converts a model.safetensors into a *separate,
# weight-only* snapshot — but only ONE is ever loaded: the weight in the loadable snapshot
# (the one carrying config.json). We keep every blob referenced by a config.json-bearing
# snapshot and delete other weight blobs (~2 GB for BGE-M3's orphan safetensors). Keyed on
# config.json, not refs/main, because pinning by commit SHA doesn't write a refs/main.
# Conservative: never hardcodes a model/format, skips a model with no loadable snapshot,
# only touches blobs >= 50 MB, never removes a loaded weight, config, or tokenizer.
#
# Reads EMBEDDING_MODEL / EMBEDDING_MODEL_REVISION / RERANKER_MODEL / RERANKER_MODEL_REVISION
# / HF_HOME from the environment (the Dockerfile ARG/ENV). Plain POSIX sh + a script file
# (no Dockerfile heredoc), so it builds on any builder — local Docker or Cloud Build.
set -eu

python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('${EMBEDDING_MODEL}', revision='${EMBEDDING_MODEL_REVISION}', device='cpu')"
python -c "from sentence_transformers import CrossEncoder; CrossEncoder('${RERANKER_MODEL}', revision='${RERANKER_MODEL_REVISION}', device='cpu')"

HUB="$HF_HOME/hub"
for model_dir in "$HUB"/models--*; do
    [ -d "$model_dir" ] || continue
    # Blob hashes referenced by a loadable snapshot (one with config.json). Revision-
    # agnostic, so pinning by commit SHA (no refs/main) still identifies what loads.
    keep=""
    for snap in "$model_dir"/snapshots/*/; do
        [ -e "${snap}config.json" ] || continue        # skip weight-only orphan snapshots
        keep="$keep $(find "$snap" -type l -exec readlink -f {} \; 2>/dev/null \
                      | while read -r p; do basename "$p"; done)"
    done
    [ -n "$keep" ] || continue                          # no loadable snapshot → leave alone
    for blob in "$model_dir"/blobs/*; do
        [ -f "$blob" ] || continue
        bh="$(basename "$blob")"
        case "$keep" in *"$bh"*) continue ;; esac       # referenced by a loaded snapshot → keep
        sz="$(stat -c%s "$blob" 2>/dev/null || echo 0)"
        if [ "$sz" -ge 52428800 ]; then                 # >= 50 MB: a redundant weight blob
            echo "pruning redundant weight blob ($sz bytes): $blob"
            rm -f "$blob"
        fi
    done
done
find "$HUB" -xtype l -delete 2>/dev/null || true        # drop now-dangling snapshot symlinks
