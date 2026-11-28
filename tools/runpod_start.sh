#!/usr/bin/env bash
# Start Paint a plate on a Runpod pod: the setup, the models, then ComfyUI on port 8188.
# In the pod's JupyterLab terminal:
#   git clone https://github.com/AInVFX/ainvfx-paintaplate /workspace/ainvfx-paintaplate
#   bash /workspace/ainvfx-paintaplate/tools/runpod_start.sh
# After updating the code on a pod where ComfyUI already runs, --restart stops it first, so the new
# nodes load:  cd /workspace/ainvfx-paintaplate && git pull && bash tools/runpod_start.sh --restart
# PLATES=1 adds the example plates to ComfyUI's input/plates folder, where the Open plate dialog lists them:
#   PLATES=1 bash tools/runpod_start.sh         (or, on a pod that is already running: python get_plates.py)
# Each start keeps the log of the ComfyUI that ran before, as comfyui.<date>-<time>.log: after a stop, it holds what ran.
# The Hugging Face token comes from the pod's HF_TOKEN variable, whose value can be a Runpod secret: {{ RUNPOD_SECRET_HF_TOKEN }}.
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
# The Hugging Face token. A Runpod secret reaches a pod only through a variable of the pod whose value is
# {{ RUNPOD_SECRET_HF_TOKEN }}, and an SSH session receives only the pod's RUNPOD_ variables. So the token is read under
# both names, here and in the environment of the pod's first process, which holds every variable of the pod.
pod_var() { { tr '\0' '\n' < /proc/1/environ; } 2>/dev/null | sed -n "s/^$1=//p" | head -n 1; }
for name in HF_TOKEN RUNPOD_SECRET_HF_TOKEN; do
  [ -z "${HF_TOKEN:-}" ] || break
  HF_TOKEN=${!name:-}
  [ -n "$HF_TOKEN" ] || HF_TOKEN=$(pod_var "$name")
done
export HF_TOKEN
case "$HF_TOKEN" in
  "") log "HF_TOKEN is not set: the FLUX 3 Image Klein and LTX 2.5 downloads need it. On Runpod, give the pod a variable HF_TOKEN: your token, or {{ RUNPOD_SECRET_HF_TOKEN }} for a secret named HF_TOKEN" ;;
  "{{"*) log "HF_TOKEN holds $HF_TOKEN as it was typed: Runpod found no secret of that name. Create the secret, then restart the pod" ;;
esac
if [ "${1:-}" = "--restart" ] && pkill -f "^$VENV/bin/python main.py"; then  # the pattern never matches this script
  log "stopped the running ComfyUI"
  for _ in $(seq 30); do curl -s -m 1 -o /dev/null http://127.0.0.1:8188/system_stats || break; sleep 1; done
fi

if curl -s -m 3 -o /dev/null http://127.0.0.1:8188/system_stats; then
  log "ComfyUI is already running: $APP"
  if [ "${PLATES:-0}" != 0 ]; then "$VENV/bin/python" "$HERE/get_plates.py" "$W/ComfyUI/input/plates" || log "example plates missing"; fi
else
  log "setup: ComfyUI, ComfyUI-LTXVideo, this pack and 79 GB of models (log: $W/setup.log)"
  bash "$HERE/tools/pod_setup.sh" > "$W/setup.log" 2>&1 &
  setup=$!
  shown=0; last=0
  report() { # each new setup line, then the models arriving, every 15 s
    local n; n=$(wc -l < "$W/setup.log" 2>/dev/null || echo 0)
    if [ "$n" -gt "$shown" ]; then sed -n "$((shown + 1)),${n}p" "$W/setup.log" | sed 's/^/    /'; shown=$n; fi
    if [ $((SECONDS - last)) -ge 15 ] && ! grep -q "models done" "$W/models.log" 2>/dev/null; then
      last=$SECONDS
      log "models: $(du -sb "$W/models" 2>/dev/null | awk '{printf "%.1f", $1 / 1e9}') of 79 GB"
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
  flags=(--listen 0.0.0.0 --port 8188)
  vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -n 1)
  if [ "${vram:-0}" -ge 80000 ]; then flags+=(--highvram); fi  # every model stays loaded on a 96 GB GPU
  read -r -a extra <<< "${COMFY_ARGS:-}"  # more ComfyUI flags, such as COMFY_ARGS=--disable-dynamic-vram
  flags+=("${extra[@]}")
  cd "$W/ComfyUI" || exit 1
  if [ -s "$W/comfyui.log" ]; then  # a ComfyUI that stopped left its last lines there, and its trace: the log is kept
    kept="$W/comfyui.$(date +%Y%m%d-%H%M%S).log"
    mv "$W/comfyui.log" "$kept" && log "the log of the ComfyUI that ran before is kept: $kept"
  fi
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
