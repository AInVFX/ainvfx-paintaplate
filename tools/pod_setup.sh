#!/usr/bin/env bash
# Standalone setup of a PaintAPlate GPU machine (tested on a Runpod RTX PRO 6000).
#   HF_TOKEN=... [PLATES=1] bash tools/pod_setup.sh [comfyui_ref] [ltxvideo_ref]
# PLATES=1 also downloads the AInVFX test plates into ComfyUI's input/plates folder (tools/get_plates.sh);
# FLUID=0 skips AInVFX's ainvfx-fluid IC-LoRA (0.65 GB), which the blank plate's fluid shots need. The models and their
# revisions are in get_models.py, at the root of the pack.
# The refs default to the tested commits, in tools/pins.sh. The pack is the repo this script lives in.
# Code, models and pins live in $WORKDIR (a network volume survives the pod); the Python env
# goes on the fast container disk. Accept the Hugging Face licences of FLUX 3 Image Klein,
# LTX 2.5 and the LTX in-outpainting IC-LoRA first: the downloads use your token.
set -euo pipefail
W=${WORKDIR:-/workspace}; VENV=${VENV:-/opt/venv}
# shellcheck source-path=SCRIPTDIR source=pins.sh
. "$(dirname "$0")/pins.sh"
COMFY_REF=${1:-${COMFY_REF:-$COMFY_PIN}}; LTX_REF=${2:-${LTX_REF:-$LTX_PIN}}
PACK=${PACK:-$(cd "$(dirname "$0")/.." && pwd)}
log() { echo "[$(date +%H:%M:%S)] $*"; }
# Code comes from GitHub, or from an upload when a pod cannot reach it (tools/offline_bundle.sh).
# A copy without git history is used as it is; git never waits more than a minute for GitHub.
fetch() { timeout 60 git fetch -q origin || log "git fetch failed: using the local copy"; }
pin() { # name: record the version of the folder we are in
  if [ -d .git ]; then echo "$1 $(git rev-parse --short HEAD) $(git log -1 --format=%cd)"
  else echo "$1 $(cat PINNED 2>/dev/null || echo "copy without git history")"; fi
}
clone() { # url, folder
  timeout 300 git clone -q "$1" "$2" && return
  log "cannot clone $1: GitHub does not answer from this machine."
  log "Upload the offline bundle instead: see the comments at the top of tools/offline_bundle.sh"
  exit 1
}

log "python env"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
# shellcheck source=/dev/null
. "$VENV/bin/activate"
pip install -q -U pip uv huggingface_hub hf_transfer

log "models (in the background)"
M=$W/models; mkdir -p "$M"
# get_models.py, at the root of the pack, holds every model file and its tested revision: FLUID=0 skips ainvfx-fluid, HDR=0 the SDR-to-HDR IC-LoRA,
# WITH_NVFP4=1 adds FLUX 3 Image Klein's nvfp4 file (only tests/gpu_bench.py compares it)
flags=(); [ "${FLUID:-1}" = 0 ] && flags+=(--no-fluid); [ "${HDR:-1}" = 0 ] && flags+=(--no-hdr); [ "${WITH_NVFP4:-0}" = 1 ] && flags+=(--nvfp4)
( HF_HUB_ENABLE_HF_TRANSFER=1 python "$PACK/get_models.py" "$M" ${flags[@]+"${flags[@]}"} || log "model files missing: see above"; log "models done" ) > "$W/models.log" 2>&1 &

log "ComfyUI $COMFY_REF"
[ -d "$W/ComfyUI" ] || clone https://github.com/comfyanonymous/ComfyUI "$W/ComfyUI"
cd "$W/ComfyUI"
if [ -d .git ]; then
  fetch
  git checkout -q "$COMFY_REF"
  git pull -q --ff-only 2>/dev/null || true  # moves a branch forward; a pinned commit stays as it is
fi
pin ComfyUI > "$W/pins.txt"
log "ComfyUI: PyTorch for CUDA 13.0"
uv pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cu130
log "ComfyUI: its Python packages"
uv pip install -q -r requirements.txt
[ -e models ] && [ ! -L models ] && rm -rf models
ln -sfn "$M" models
mkdir -p "$M/diffusion_models" "$M/text_encoders" "$M/vae" "$M/loras" "$M/checkpoints" "$M/vae_approx" "$M/embeddings"

log "ComfyUI-LTXVideo $LTX_REF"
cd custom_nodes
[ -d ComfyUI-LTXVideo ] || clone https://github.com/Lightricks/ComfyUI-LTXVideo ComfyUI-LTXVideo
(
  cd ComfyUI-LTXVideo
  if [ -d .git ]; then
    fetch
    git checkout -q "$LTX_REF"
    git pull -q --ff-only 2>/dev/null || true
  fi
  pin ComfyUI-LTXVideo >> "$W/pins.txt"
  log "ComfyUI-LTXVideo: its Python packages"
  uv pip install -q -r requirements.txt
)

log "PaintAPlate"
dst="$W/ComfyUI/custom_nodes/ainvfx-paintaplate"
if [ "$PACK" != "$dst" ]; then
  [ -L "$dst" ] || rm -rf "$dst"  # an older copy is replaced by a link to this repo
  ln -sfn "$PACK" "$dst"
fi
uv pip install -q -r "$PACK/requirements.txt"
if [ "${PLATES:-0}" != 0 ]; then  # the AInVFX test plates into input/plates, where the Open plate dialog lists them
  log "test plates from Hugging Face"
  bash "$PACK/tools/get_plates.sh" "$W/ComfyUI" || log "the test plates did not download: run bash tools/get_plates.sh later"
fi
cat "$W/pins.txt"; log "setup done"
