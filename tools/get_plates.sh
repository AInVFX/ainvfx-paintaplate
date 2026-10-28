#!/usr/bin/env bash
# The AInVFX test plates, from the Hugging Face dataset into ComfyUI's input/plates folder: the Open plate dialog lists them.
#   bash tools/get_plates.sh [ComfyUI folder]        default: $WORKDIR/ComfyUI (/workspace/ComfyUI on a pod)
# On a pod, PLATES=1 bash tools/runpod_start.sh does the same during setup. Running it again only fetches what changed.
# PLATES_REPO picks another dataset (default AInVFX/ainvfx-paintaplate), PLATES_REVISION a branch or a commit.
set -euo pipefail
W=${WORKDIR:-/workspace}; VENV=${VENV:-/opt/venv}
COMFY=${1:-$W/ComfyUI}
REPO=${PLATES_REPO:-AInVFX/ainvfx-paintaplate}
[ -d "$COMFY" ] || { echo "No ComfyUI folder at $COMFY: give its path as the first argument."; exit 1; }
HF=$VENV/bin/hf
[ -x "$HF" ] || HF=$(command -v hf || true)
[ -n "$HF" ] || { echo "The hf command is missing: pip install huggingface_hub"; exit 1; }
DEST="$COMFY/input/plates"
mkdir -p "$DEST"
args=(download "$REPO" --repo-type dataset --include "*.mp4" --local-dir "$DEST")
[ -z "${PLATES_REVISION:-}" ] || args+=(--revision "$PLATES_REVISION")
"$HF" "${args[@]}" > /dev/null
echo "$(find "$DEST" -maxdepth 1 -name '*.mp4' | wc -l | tr -d ' ') plates in $DEST, from huggingface.co/datasets/$REPO"
