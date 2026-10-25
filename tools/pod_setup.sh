#!/usr/bin/env bash
# Standalone setup of a PaintAPlate GPU machine (tested on a Runpod RTX PRO 6000).
#   HF_TOKEN=... bash pod_setup.sh [comfyui_ref] [ltxvideo_ref]
# Code, models and pins live in $WORKDIR (a network volume survives the pod); the Python env
# goes on the fast container disk. Accept the Hugging Face licences of FLUX 3 Image Klein,
# LTX 2.5 and SAM 3.1 first: the downloads use your token.
set -euo pipefail
W=${WORKDIR:-/workspace}; VENV=${VENV:-/opt/venv}
COMFY_REF=${1:-master}; LTX_REF=${2:-master}
log() { echo "[$(date +%H:%M:%S)] $*"; }

log "python env"
[ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
# shellcheck source=/dev/null
. "$VENV/bin/activate"
pip install -q -U pip uv huggingface_hub hf_transfer

log "models (in the background)"
M=$W/models; mkdir -p "$M"
get() { # repo, file in repo, target folder
  [ -s "$M/$3/$(basename "$2")" ] && return
  HF_HUB_ENABLE_HF_TRANSFER=1 hf download "$1" "$2" --local-dir "$M/.dl/$3" >/dev/null && mkdir -p "$M/$3" && mv "$M/.dl/$3/$2" "$M/$3/"
}
SAM=$(python -c "from huggingface_hub import list_repo_files as l; print(next(f for f in l('Comfy-Org/sam3.1') if f.endswith('sam3.1_multiplex_fp16.safetensors')))")
( get black-forest-labs/flux-3-image-klein-comfy diffusion_models/flux3-image-klein-int8-convrot.safetensors diffusion_models &
  get black-forest-labs/flux-3-image-klein-comfy diffusion_models/flux3-image-klein-nvfp4.safetensors diffusion_models &
  get black-forest-labs/flux-3-image-klein-comfy text_encoders/qwen3vl_4b_int8_convrot.safetensors text_encoders &
  get black-forest-labs/flux-3-image-klein-comfy vae/flux2-vae.safetensors vae &
  get Lightricks/LTX-2.5 diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors diffusion_models &
  get Lightricks/LTX-2.5 text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors text_encoders &
  get Lightricks/LTX-2.5 vae/ltx-2.5-video-vae-conv-bf16.safetensors vae &
  get Lightricks/LTX-2.5 vae/ltx-2.5-audio-vae-bf16.safetensors vae &
  get WepeNerd/LTX-Ripple LTX25_Ripple_v11.safetensors loras &
  get Comfy-Org/sam3.1 "$SAM" checkpoints &
  wait; log "models done" ) > "$W/models.log" 2>&1 &

log "ComfyUI $COMFY_REF"
[ -d "$W/ComfyUI" ] || git clone -q https://github.com/comfyanonymous/ComfyUI "$W/ComfyUI"
cd "$W/ComfyUI"
git fetch -q origin || log "git fetch failed: using the local copy"
git checkout -q "$COMFY_REF"
git pull -q --ff-only 2>/dev/null || true  # moves a branch forward; a pinned commit stays as it is
echo "ComfyUI $(git rev-parse --short HEAD) $(git log -1 --format=%cd)" > "$W/pins.txt"
uv pip install -q torch torchvision --index-url https://download.pytorch.org/whl/cu130
uv pip install -q -r requirements.txt
[ -e models ] && [ ! -L models ] && rm -rf models
ln -sfn "$M" models
mkdir -p "$M/diffusion_models" "$M/text_encoders" "$M/vae" "$M/loras" "$M/checkpoints" "$M/vae_approx"

log "ComfyUI-LTXVideo $LTX_REF"
cd custom_nodes
[ -d ComfyUI-LTXVideo ] || git clone -q https://github.com/Lightricks/ComfyUI-LTXVideo
(
  cd ComfyUI-LTXVideo
  git fetch -q origin || log "git fetch failed: using the local copy"
  git checkout -q "$LTX_REF"
  git pull -q --ff-only 2>/dev/null || true
  echo "ComfyUI-LTXVideo $(git rev-parse --short HEAD) $(git log -1 --format=%cd)" >> "$W/pins.txt"
  uv pip install -q -r requirements.txt
)

log "PaintAPlate"
rm -rf ainvfx-paintaplate && cp -r "$W/pack/ainvfx-paintaplate" . && uv pip install -q -r ainvfx-paintaplate/requirements.txt
cat "$W/pins.txt"; log "setup done"
