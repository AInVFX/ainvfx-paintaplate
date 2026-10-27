#!/usr/bin/env bash
# Standalone setup of a PaintAPlate GPU machine (tested on a Runpod RTX PRO 6000).
#   HF_TOKEN=... bash tools/pod_setup.sh [comfyui_ref] [ltxvideo_ref]
# The refs default to the tested commits. The pack is the repo this script lives in.
# Code, models and pins live in $WORKDIR (a network volume survives the pod); the Python env
# goes on the fast container disk. Accept the Hugging Face licences of FLUX 3 Image Klein,
# LTX 2.5 and the LTX in-outpainting IC-LoRA first: the downloads use your token.
set -euo pipefail
W=${WORKDIR:-/workspace}; VENV=${VENV:-/opt/venv}
COMFY_REF=${1:-${COMFY_REF:-19ae172b}}; LTX_REF=${2:-${LTX_REF:-220e1d4}}
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
rev() { # the tested revision of each model repository (checked 27 Oct 2026)
  case "$1" in
    black-forest-labs/flux-3-image-klein-comfy) echo feef60b0aaf63a4773ace96636ebbcf43b881312 ;;
    Lightricks/LTX-2.5) echo 49b093a39c19169a8a81721dcc541e07e945232f ;;
    Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting) echo 8becd61405133263d9e580be41a92e8f827b01ed ;;
    WepeNerd/LTX-Ripple) echo 76abac5ede8a3415b9d1cd803843a38ecb351600 ;;
    Comfy-Org/sam3.1) echo 7bb8374780a725b4353ed31f3a9395c9742b5621 ;;
    Kijai/LTX2.3_comfy) echo 6d980fde0d330f2fed6ff8dfdfddb06d88a004e5 ;;
  esac
}
get() { # repo, file in repo, target folder
  [ -s "$M/$3/$(basename "$2")" ] && return
  HF_HUB_ENABLE_HF_TRANSFER=1 hf download "$1" "$2" --revision "$(rev "$1")" --local-dir "$M/.dl/$3" >/dev/null &&
    mkdir -p "$M/$3" && mv "$M/.dl/$3/$2" "$M/$3/"
}
( get black-forest-labs/flux-3-image-klein-comfy diffusion_models/flux3-image-klein-int8-convrot.safetensors diffusion_models &
  if [ "${WITH_NVFP4:-0}" = 1 ]; then  # only tests/gpu_bench.py compares it
    get black-forest-labs/flux-3-image-klein-comfy diffusion_models/flux3-image-klein-nvfp4.safetensors diffusion_models &
  fi
  get black-forest-labs/flux-3-image-klein-comfy text_encoders/qwen3vl_4b_int8_convrot.safetensors text_encoders &
  get black-forest-labs/flux-3-image-klein-comfy text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors text_encoders &
  get black-forest-labs/flux-3-image-klein-comfy vae/flux2-vae.safetensors vae &
  get Lightricks/LTX-2.5 diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors diffusion_models &
  get Lightricks/LTX-2.5 text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors text_encoders &
  get Lightricks/LTX-2.5 vae/ltx-2.5-video-vae-conv-bf16.safetensors vae &
  get Lightricks/LTX-2.5 vae/ltx-2.5-audio-vae-bf16.safetensors vae &
  get WepeNerd/LTX-Ripple LTX25_Ripple_v11.safetensors loras &
  get Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors loras &
  get Comfy-Org/sam3.1 checkpoints/sam3.1_multiplex_fp16.safetensors checkpoints &
  get Kijai/LTX2.3_comfy vae/taeltx2_3.safetensors vae_approx &  # the live preview's tiny decoder (MIT, madebyollin/taehv)
  wait; log "models done" ) > "$W/models.log" 2>&1 &

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
mkdir -p "$M/diffusion_models" "$M/text_encoders" "$M/vae" "$M/loras" "$M/checkpoints" "$M/vae_approx"

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
cat "$W/pins.txt"; log "setup done"
