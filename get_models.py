"""Download the models Paint a plate's workflows load, at the tested revisions, into a ComfyUI models folder.

    python get_models.py [MODELS_FOLDER] [--no-fluid] [--no-hdr] [--list] [--only FILE ...]

Run it with the Python that runs ComfyUI, which has huggingface_hub; it works the same on Windows, macOS and Linux.
Without MODELS_FOLDER it uses the models folder of the ComfyUI this pack is installed in (custom_nodes/ainvfx-paintaplate).
First accept the licences of FLUX 3 Image Klein, LTX 2.5, the in-outpainting IC-LoRA and the SDR-to-HDR IC-LoRA on Hugging Face, then set the
HF_TOKEN environment variable to a read token. A file already in place is skipped, and several files download at once:
about 61 GB in all, ainvfx-fluid 0.65 GB and SDR to HDR 1.32 GB of it. tools/pod_setup.sh runs this script on a pod, so every model file and
its revision has one home: here.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor

REVISIONS = {  # the tested revision of each repository
    "black-forest-labs/flux-3-image-klein-comfy": "feef60b0aaf63a4773ace96636ebbcf43b881312",
    "Lightricks/LTX-2.5": "49b093a39c19169a8a81721dcc541e07e945232f",
    "Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting": "8becd61405133263d9e580be41a92e8f827b01ed",
    "WepeNerd/LTX-Ripple": "76abac5ede8a3415b9d1cd803843a38ecb351600",
    "Comfy-Org/sam3.1": "7bb8374780a725b4353ed31f3a9395c9742b5621",
    "Kijai/LTX2.3_comfy": "6d980fde0d330f2fed6ff8dfdfddb06d88a004e5",
    "Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR": "c7578ebddb54f4210e534e4d8cad698a5a520692",  # gated: accept its licence first
    "AInVFX/ainvfx-fluid": "fd4855a18d879c551bf4c5f49b1a877874437cb6",  # version 2, trained on synthetic data
}
MODELS = [  # (repository, file in the repository, folder under models/)
    ("black-forest-labs/flux-3-image-klein-comfy", "diffusion_models/flux3-image-klein-int8-convrot.safetensors", "diffusion_models"),
    ("black-forest-labs/flux-3-image-klein-comfy", "text_encoders/qwen3vl_4b_int8_convrot.safetensors", "text_encoders"),
    ("black-forest-labs/flux-3-image-klein-comfy", "text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors", "text_encoders"),
    ("black-forest-labs/flux-3-image-klein-comfy", "vae/flux2-vae.safetensors", "vae"),
    ("Lightricks/LTX-2.5", "diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors", "diffusion_models"),
    ("Lightricks/LTX-2.5", "text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors", "text_encoders"),
    ("Lightricks/LTX-2.5", "vae/ltx-2.5-video-vae-conv-bf16.safetensors", "vae"),
    ("Lightricks/LTX-2.5", "vae/ltx-2.5-audio-vae-bf16.safetensors", "vae"),
    ("WepeNerd/LTX-Ripple", "LTX25_Ripple_v11.safetensors", "loras"),
    ("Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting", "ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors", "loras"),
    ("Comfy-Org/sam3.1", "checkpoints/sam3.1_multiplex_fp16.safetensors", "checkpoints"),
    ("Kijai/LTX2.3_comfy", "vae/taeltx2_3.safetensors", "vae_approx"),  # the live preview's tiny decoder (MIT, madebyollin/taehv)
    ("Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR", "ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors", "loras"),  # SDR to HDR
    ("Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR", "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors", "embeddings"),  # its prompt
    ("AInVFX/ainvfx-fluid", "ltx-2.5/ainvfx-fluid.safetensors", "loras"),  # optional: fluid shots from a blank plate
]
FLUID = "ainvfx-fluid.safetensors"
HDR = ("ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors", "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors")  # gated
OPTIONAL = (FLUID, *HDR)  # without them, fluid shots or SDR to HDR switch off and the rest works
NVFP4 = ("black-forest-labs/flux-3-image-klein-comfy", "diffusion_models/flux3-image-klein-nvfp4.safetensors", "diffusion_models")
STAGING = ".paintaplate_downloads"  # inside the models folder, so a finished file moves into place without a copy


def comfy_models() -> str | None:
    """The models folder of the ComfyUI this file is installed in: ComfyUI/custom_nodes/<pack>/get_models.py."""
    folder = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "models"))
    return folder if os.path.isdir(folder) else None


def fetch(model, models: str) -> str:
    repo, path, folder = model
    name = os.path.basename(path)
    target = os.path.join(models, folder, name)
    if os.path.isfile(target) and os.path.getsize(target) > 0:
        return f"already there: {folder}/{name}"
    from huggingface_hub import hf_hub_download
    got = hf_hub_download(repo, path, revision=REVISIONS[repo], local_dir=os.path.join(models, STAGING, folder))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    os.replace(got, target)
    return f"downloaded: {folder}/{name}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Download the models Paint a plate's workflows load, at the tested revisions.")
    ap.add_argument("models", nargs="?", default=comfy_models(), help="ComfyUI's models folder (default: the one this pack is in)")
    ap.add_argument("--no-fluid", action="store_true", help="skip ainvfx-fluid: fluid shots from a blank plate switch off")
    ap.add_argument("--no-hdr", action="store_true", help="skip the SDR-to-HDR IC-LoRA (gated): SDR to HDR switches off")
    ap.add_argument("--nvfp4", action="store_true", help=argparse.SUPPRESS)  # FLUX 3 Image Klein's nvfp4 file: tests/gpu_bench.py only
    ap.add_argument("--only", nargs="+", metavar="FILE", help="these files only")
    ap.add_argument("--list", action="store_true", help="list the files, their folders and repositories, then stop")
    a = ap.parse_args(argv)
    todo = [m for m in MODELS + ([NVFP4] if a.nvfp4 else [])
            if not (a.no_fluid and m[1].endswith(FLUID)) and not (a.no_hdr and os.path.basename(m[1]) in HDR) and (not a.only or os.path.basename(m[1]) in a.only)]
    if a.list:
        for repo, path, folder in todo:
            print(f"{folder}/{os.path.basename(path)}  from {repo} at {REVISIONS[repo][:7]}")
        return 0
    if not a.models or not os.path.isdir(a.models):
        print("Name ComfyUI's models folder: python get_models.py path/to/ComfyUI/models", file=sys.stderr)
        return 2
    failed, missing = 0, []
    with ThreadPoolExecutor(6) as pool:
        for model, job in [(m, pool.submit(fetch, m, a.models)) for m in todo]:
            try:
                print(job.result(), flush=True)
            except Exception as exc:  # a licence not accepted, no token, no network: say which file, go on with the others
                failed += 1
                missing.append(os.path.basename(model[1]))
                print(f"FAILED: {model[2]}/{os.path.basename(model[1])} from {model[0]}: {str(exc).splitlines()[0][:300]}", flush=True)
    shutil.rmtree(os.path.join(a.models, STAGING), ignore_errors=True)
    print(f"{len(todo) - failed} of {len(todo)} model files in {a.models}" +
          (". Accept the licences on Hugging Face, set HF_TOKEN, then run this again: what is there is skipped." if failed else ""))
    if any(f in HDR for f in missing):
        print("SDR to HDR stays off: accept the licence of Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR on Hugging Face, then run this again.")
    return 1 if any(f not in OPTIONAL for f in missing) else 0  # an optional file missing leaves the rest working


if __name__ == "__main__":
    sys.exit(main())
