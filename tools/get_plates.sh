#!/usr/bin/env bash
# The example plates into ComfyUI's input/plates folder, with a pod's defaults. The tool is get_plates.py, at the root
# of the pack, which runs on any machine: this script only calls it.
#   bash tools/get_plates.sh [ComfyUI folder]        default: $WORKDIR/ComfyUI (/workspace/ComfyUI on a pod)
set -euo pipefail
PY=${VENV:-/opt/venv}/bin/python; [ -x "$PY" ] || PY=python
exec "$PY" "$(dirname "$0")/../get_plates.py" "${1:-${WORKDIR:-/workspace}/ComfyUI}/input/plates"
