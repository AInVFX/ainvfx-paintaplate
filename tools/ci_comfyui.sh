#!/bin/bash
# Prepare a CPU ComfyUI for the live tests: the pinned ComfyUI and ComfyUI-LTXVideo, this pack linked in,
# empty placeholder model files. The last line printed is COMFYUI_DIR=<path>.
#   bash tools/ci_comfyui.sh [workdir]
set -euo pipefail
W=${1:-$PWD/.ci}
PACK=$(cd "$(dirname "$0")/.." && pwd)
PY=${PYTHON:-python}
COMFY_REF=${COMFY_REF:-426f5eea}
LTX_REF=${LTX_REF:-220e1d4}
C="$W/ComfyUI"
mkdir -p "$W"
[ -d "$C" ] || git clone -q --filter=blob:none https://github.com/comfyanonymous/ComfyUI "$C"
git -C "$C" checkout -q "$COMFY_REF"
L="$C/custom_nodes/ComfyUI-LTXVideo"
[ -d "$L" ] || git clone -q --filter=blob:none https://github.com/Lightricks/ComfyUI-LTXVideo "$L"
git -C "$L" checkout -q "$LTX_REF"
ln -sfn "$PACK" "$C/custom_nodes/ainvfx-paintaplate"
"$PY" -c "import torch" 2>/dev/null || "$PY" -m pip install -q torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cpu
"$PY" -m pip install -q -r "$C/requirements.txt" -r "$L/requirements.txt" -r "$PACK/requirements.txt"
"$PY" "$PACK/tools/placeholders.py" "$C" >&2
echo "COMFYUI_DIR=$C"
