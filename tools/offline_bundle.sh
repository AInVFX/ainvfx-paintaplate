#!/usr/bin/env bash
# An offline bundle, for a GPU machine that cannot reach GitHub (Hugging Face and PyPI still needed).
#   bash tools/offline_bundle.sh [paintaplate_offline.tar.gz]
# Run it where GitHub answers (a laptop). The bundle holds ComfyUI and ComfyUI-LTXVideo at the tested
# commits and this repo as committed, laid out as in /workspace. On the GPU machine:
#   1. In JupyterLab, open the workspace folder and drag the bundle into it.
#   2. In a terminal: cd /workspace && tar xzf paintaplate_offline.tar.gz
#   3. bash /workspace/ainvfx-paintaplate/tools/runpod_start.sh
# pod_setup.sh then skips git for these folders and records their versions from PINNED.
set -euo pipefail
# shellcheck source-path=SCRIPTDIR source=pins.sh
. "$(dirname "$0")/pins.sh"
COMFY_REF=${COMFY_REF:-$COMFY_PIN}; LTX_REF=${LTX_REF:-$LTX_PIN}
OUT=$(realpath -m "${1:-paintaplate_offline.tar.gz}")
PACK=$(cd "$(dirname "$0")/.." && pwd)
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
get() { # github repo, ref, folder: the source archive GitHub serves for that commit
  mkdir -p "$3"
  curl -fsSL --retry 3 "https://github.com/$1/archive/$2.tar.gz" | tar xz -C "$3" --strip-components=1
  echo "$2 (offline bundle, $(date +%Y-%m-%d))" > "$3/PINNED"
}
get comfyanonymous/ComfyUI "$COMFY_REF" "$T/ComfyUI"
get Lightricks/ComfyUI-LTXVideo "$LTX_REF" "$T/ComfyUI/custom_nodes/ComfyUI-LTXVideo"
mkdir -p "$T/ainvfx-paintaplate"
git -C "$PACK" archive HEAD | tar x -C "$T/ainvfx-paintaplate"
tar czf "$OUT" -C "$T" ComfyUI ainvfx-paintaplate
echo "wrote $OUT ($(du -h "$OUT" | cut -f1)): ComfyUI $COMFY_REF, ComfyUI-LTXVideo $LTX_REF, $(git -C "$PACK" log -1 --format='PaintAPlate %h')"
