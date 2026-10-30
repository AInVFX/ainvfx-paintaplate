#!/usr/bin/env bash
# Start Paint a plate on a Runpod pod: the setup, the models, then ComfyUI on port 8188.
# In the pod's JupyterLab terminal:
#   git clone https://github.com/AInVFX/ainvfx-paintaplate /workspace/ainvfx-paintaplate
#   bash /workspace/ainvfx-paintaplate/tools/runpod_start.sh
# After updating the code on a pod where ComfyUI already runs, --restart stops it first, so the new
# nodes load:  cd /workspace/ainvfx-paintaplate && git pull && bash tools/runpod_start.sh --restart
# When the pod cannot reach GitHub, upload the offline bundle instead (tools/offline_bundle.sh).
# PLATES=1 adds the AInVFX test plates to ComfyUI's input/plates folder, where the Open plate dialog lists them:
#   PLATES=1 bash tools/runpod_start.sh         (or, on a pod that is already running: bash tools/get_plates.sh)
# As a container's start command (process 1), it also starts Runpod's services and keeps the pod running.
set -uo pipefail
W=${WORKDIR:-/workspace}; VENV=${VENV:-/opt/venv}
HERE=$(cd "$(dirname "$0")/.." && pwd)
APP="https://${RUNPOD_POD_ID:-<pod-id>}-8188.proxy.runpod.net/extensions/ainvfx-paintaplate/paintaplate.html"
log() { echo "[$(date +%H:%M:%S)] Paint a plate: $*"; }
main=0
if [ $$ -eq 1 ]; then main=1; fi
if [ "$main" = 1 ] && [ -x /start.sh ]; then  # JupyterLab and SSH, as in Runpod's own images
  /start.sh > "$W/runpod_services.log" 2>&1 &
fi
[ -n "${HF_TOKEN:-}" ] || log "HF_TOKEN is not set: the FLUX 3 Image Klein and LTX 2.5 downloads need it"
if [ "${1:-}" = "--restart" ] && pkill -f "^$VENV/bin/python main.py"; then  # the pattern never matches this script
  log "stopped the running ComfyUI"
  for _ in $(seq 30); do curl -s -m 1 -o /dev/null http://127.0.0.1:8188/system_stats || break; sleep 1; done
fi

if curl -s -m 3 -o /dev/null http://127.0.0.1:8188/system_stats; then
  log "ComfyUI is already running: $APP"
  if [ "${PLATES:-0}" != 0 ]; then bash "$HERE/tools/get_plates.sh" "$W/ComfyUI" || log "the test plates did not download"; fi
else
  log "setup: ComfyUI, ComfyUI-LTXVideo, this pack and 60 GB of models (log: $W/setup.log)"
  bash "$HERE/tools/pod_setup.sh" > "$W/setup.log" 2>&1 &
  setup=$!
  shown=0; last=0
  report() { # each new setup line, then the models arriving, every 15 s
    local n; n=$(wc -l < "$W/setup.log" 2>/dev/null || echo 0)
    if [ "$n" -gt "$shown" ]; then sed -n "$((shown + 1)),${n}p" "$W/setup.log" | sed 's/^/    /'; shown=$n; fi
    if [ $((SECONDS - last)) -ge 15 ] && ! grep -q "models done" "$W/models.log" 2>/dev/null; then
      last=$SECONDS
      log "models: $(du -sb "$W/models" 2>/dev/null | awk '{printf "%.1f", $1 / 1e9}') of 60 GB"
    fi
  }
  while kill -0 "$setup" 2>/dev/null; do report; sleep 2; done
  report
  if ! wait "$setup"; then
    log "setup failed: see $W/setup.log"
    if [ "$main" = 1 ]; then sleep infinity; fi
    exit 1
  fi
  for _ in $(seq 720); do
    grep -q "models done" "$W/models.log" 2>/dev/null && break
    report; sleep 5
  done
  log "models ready: $(du -sb "$W/models" 2>/dev/null | awk '{printf "%.1f", $1 / 1e9}') GB"
  flags=(--listen 0.0.0.0 --port 8188 --preview-method latent2rgb)
  vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1)
  if [ "${vram:-0}" -ge 80000 ]; then flags+=(--highvram); fi  # every model stays loaded on a 96 GB card
  cd "$W/ComfyUI" || exit 1
  log "starting ComfyUI (log: $W/comfyui.log)"
  nohup "$VENV/bin/python" main.py "${flags[@]}" > "$W/comfyui.log" 2>&1 &
  t0=$SECONDS
  for _ in $(seq 120); do
    curl -s -m 3 -o /dev/null http://127.0.0.1:8188/system_stats && break
    sleep 2
  done
  log "ComfyUI answered after $((SECONDS - t0)) s"
  log "ready: $APP"
fi
if [ "$main" = 1 ]; then sleep infinity; fi  # keep the pod running
