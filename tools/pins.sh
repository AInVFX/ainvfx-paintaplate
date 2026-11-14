#!/usr/bin/env bash
# shellcheck disable=SC2034  # read by the scripts that source this file
# The tested commits of ComfyUI (v0.45.3) and ComfyUI-LTXVideo. tools/pod_setup.sh, tools/ci_comfyui.sh and
# tools/offline_bundle.sh read them here, so a pin changes in one place. Model revisions live in get_models.py.
COMFY_PIN=71096d1a
LTX_PIN=220e1d4
