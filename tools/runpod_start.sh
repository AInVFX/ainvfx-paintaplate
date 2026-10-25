#!/usr/bin/env bash
# Start PaintAPlate on a Runpod pod: the setup, the models, then ComfyUI on port 8188.
# In the pod's JupyterLab terminal:
#   git clone https://github.com/AInVFX/ainvfx-paintaplate /workspace/ainvfx-paintaplate
#   bash /workspace/ainvfx-paintaplate/tools/runpod_start.sh
# As a container's start command (process 1), it also starts Runpod's services and keeps the pod running.
set -uo pipefail
W=${WORKDIR:-/workspace}; VENV=${VENV:-/opt/venv}
HERE=$(cd "$(dirname "$0")/.." && pwd)
APP="https://${RUNPOD_POD_ID:-<pod-id>}-8188.proxy.runpod.net/extensions/ainvfx-paintaplate/paintaplate.html"
log() { echo "[$(date +%H:%M:%S)] PaintAPlate: $*"; }
main=0
if [ $$ -eq 1 ]; then main=1; fi
if [ "$main" = 1 ] && [ -x /start.sh ]; then  # JupyterLab and SSH, as in Runpod's own images
  /start.sh > "$W/runpod_services.log" 2>&1 &
fi
[ -n "${HF_TOKEN:-}" ] || log "HF_TOKEN is not set: the FLUX 3 Image Klein and LTX 2.5 downloads need it"

if curl -s -m 3 -o /dev/null http://127.0.0.1:8188/system_stats; then
  log "ComfyUI is already running: $APP"
else
  log "setup: ComfyUI, ComfyUI-LTXVideo, this pack and 52 GB of models (log: $W/setup.log)"
  if ! bash "$HERE/tools/pod_setup.sh" > "$W/setup.log" 2>&1; then
    log "setup failed: see $W/setup.log"
    if [ "$main" = 1 ]; then sleep infinity; fi
    exit 1
  fi
  log "waiting for the models (log: $W/models.log)"
  for _ in $(seq 360); do
    grep -q "models done" "$W/models.log" 2>/dev/null && break
    sleep 5
  done
  flags=(--listen 0.0.0.0 --port 8188 --preview-method latent2rgb)
  vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1)
  if [ "${vram:-0}" -ge 80000 ]; then flags+=(--highvram); fi  # every model stays loaded on a 96 GB card
  cd "$W/ComfyUI" || exit 1
  nohup "$VENV/bin/python" main.py "${flags[@]}" > "$W/comfyui.log" 2>&1 &
  for _ in $(seq 120); do
    curl -s -m 3 -o /dev/null http://127.0.0.1:8188/system_stats && break
    sleep 2
  done
  log "ready: $APP"
fi
if [ "$main" = 1 ]; then sleep infinity; fi  # keep the pod running
