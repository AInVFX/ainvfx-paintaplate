"""Download the models Paint a plate's workflows load, at the tested revisions, into a ComfyUI models folder.

    python get_models.py [MODELS_FOLDER] [--list] [--no-fluid] [--no-hdr] [--only FILE ...]

Run it with the Python that runs ComfyUI, which has huggingface_hub. It works the same on Windows, macOS and Linux, on a
local machine and on a pod. Without MODELS_FOLDER it uses the models folder of the ComfyUI this pack is installed in
(custom_nodes/ainvfx-paintaplate). --list prints each file with its size and whether it is in place, and downloads nothing.

First accept the licences of FLUX 3 Image Klein, LTX 2.5, the in-outpainting IC-LoRA and the SDR-to-HDR IC-LoRA on
Hugging Face, then set the HF_TOKEN environment variable to a read token. A file already in place is skipped, and
several files download at once: about 62 GB in all, ainvfx-fluid 0.65 GB and SDR to HDR 1.32 GB of it. The last line
says how many files were downloaded, were already there and are missing; the exit code is 1 while a file the workflows
need is missing, 2 when the folder or huggingface_hub is not found. tools/pod_setup.sh runs this script on a pod, so every model file, its size and its revision have one
home: here. get_plates.py, beside this file, downloads the example plates with the same code.
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
    "AInVFX/ainvfx-fluid": "6102c50e9629ab4bf32a36d184e705b7a829e4f3",  # retrained on synthetic data (1 November 2026)
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
    ("Kijai/LTX2.3_comfy", "vae/taeltx2_3.safetensors", "vae_approx"),  # the live preview's tiny decoder: madebyollin/taehv (MIT), from a repository whose card names the LTX-2 Community License Agreement
    ("Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR", "ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors", "loras"),  # SDR to HDR
    ("Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR", "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors", "embeddings"),  # its prompt
    ("AInVFX/ainvfx-fluid", "ltx-2.5/ainvfx-fluid.safetensors", "loras"),  # optional: fluid shots from a blank plate
]
FLUID = "ainvfx-fluid.safetensors"
HDR = ("ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors", "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors")  # gated
OPTIONAL = (FLUID, *HDR)  # without them, fluid shots or SDR to HDR switch off and the rest works
NVFP4 = ("black-forest-labs/flux-3-image-klein-comfy", "diffusion_models/flux3-image-klein-nvfp4.safetensors", "diffusion_models")
SIZES = {  # bytes of each file at its revision (Hugging Face, read 11 November 2026): --list prints them and adds them up
    "flux3-image-klein-int8-convrot.safetensors": 5827874779,
    "qwen3vl_4b_int8_convrot.safetensors": 4858559240,
    "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors": 6724090780,
    "flux2-vae.safetensors": 336211292,
    "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors": 21504034224,
    "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors": 15372969374,
    "ltx-2.5-video-vae-conv-bf16.safetensors": 1452269922,
    "ltx-2.5-audio-vae-bf16.safetensors": 364866540,
    "LTX25_Ripple_v11.safetensors": 654443392,
    "ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors": 1308778338,
    "sam3.1_multiplex_fp16.safetensors": 1745546848,
    "taeltx2_3.safetensors": 23531296,
    "ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors": 1308787472,
    "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors": 12614165,
    "ainvfx-fluid.safetensors": 654446320,
    "flux3-image-klein-nvfp4.safetensors": 5277685632,
}
STAGING = ".paintaplate_downloads"  # inside the destination folder, so a finished file moves into place without a copy
TOKENS = "https://huggingface.co/settings/tokens"
NO_HUB = ("This Python has no huggingface_hub package. Run this command with the Python that runs ComfyUI (activate its virtual "
          "environment first), or install the package: python -m pip install huggingface_hub")


# ---------- Shared with get_plates.py ----------

def comfy_folder(name: str) -> str | None:
    """A folder of the ComfyUI this file is installed in: ComfyUI/custom_nodes/<pack>/<this file>."""
    folder = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", name))
    return folder if os.path.isdir(folder) else None


def hub():
    """huggingface_hub, or one sentence that says what to do: the system's Python rarely has the package, ComfyUI's does."""
    try:
        import huggingface_hub
    except ImportError:
        print(NO_HUB, file=sys.stderr)
        raise SystemExit(2) from None
    return huggingface_hub


def in_place(target: str) -> bool:
    return os.path.isfile(target) and os.path.getsize(target) > 0


def size(n: int) -> str:  # as Hugging Face shows it: 21.5 GB, 654 MB
    return f"{n / 1e9:.1f} GB" if n >= 1e9 else f"{n / 1e6:.0f} MB"


def why(exc: Exception, page: str) -> str:
    """Why a download failed, in one sentence, with the page to open when Hugging Face refused the file."""
    code = getattr(getattr(exc, "response", None), "status_code", None)
    if code == 401:
        return f"Hugging Face asks for a token: set HF_TOKEN to a read token ({TOKENS}), and accept the licence at {page}"
    if code == 403:
        return f"this token's account has not accepted the licence: open {page} and accept it"
    return (str(exc).splitlines() or [type(exc).__name__])[0][:300]


def download(files, folder: str, noun: str, repo_type: str = "model") -> list[str]:
    """Each file of `files`, (repository, path in it, revision, path under `folder`), put in place: six at once, each
    downloaded beside its place and moved there when complete, so a download that stops leaves no partial file. One
    line per file, then one closing line. Returns the files that are still missing."""
    hf_hub_download = hub().hf_hub_download
    staging = os.path.join(folder, STAGING)
    site = "https://huggingface.co/" + ("datasets/" if repo_type == "dataset" else "")

    def fetch(repo, path, revision, rel) -> bool:
        target = os.path.join(folder, rel)
        if in_place(target):
            return False
        got = hf_hub_download(repo, path, revision=revision, repo_type=repo_type, local_dir=os.path.join(staging, repo.replace("/", "__")))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        os.replace(got, target)
        return True

    new, missing = 0, []
    with ThreadPoolExecutor(6) as pool:
        for (repo, _, _, rel), job in [(f, pool.submit(fetch, *f)) for f in files]:
            try:
                fetched = job.result()
                new += fetched
                print(f"{'downloaded' if fetched else 'already there'}: {rel}", flush=True)
            except Exception as exc:  # no token, a licence not accepted, no network: say which file and why, go on with the others
                missing.append(rel)
                print(f"MISSING: {rel}: {why(exc, site + repo)}", flush=True)
    shutil.rmtree(staging, ignore_errors=True)
    print(f"{len(files) - len(missing)} of {len(files)} {noun} in {folder}: {new} downloaded, {len(files) - len(missing) - new} already there"
          + (f", {len(missing)} missing. Each MISSING line says why. Then run this again: what is there is skipped." if missing else ""))
    return missing


def listing(files, folder: str, noun: str, sizes: dict) -> list[str]:
    """--list: each file with its size and whether it is in place, then one closing line. Returns the missing files."""
    missing = [rel for _, _, _, rel in files if not in_place(os.path.join(folder, rel))]
    for repo, _, revision, rel in files:
        print(f"{'missing ' if rel in missing else 'in place'}  {size(sizes[rel]):>8}  {rel}  ({repo} at {revision[:7]})")
    print(f"{len(files) - len(missing)} of {len(files)} {noun} in place in {folder}"
          + (f": {size(sum(sizes[rel] for rel in missing))} to download" if missing else ""))
    return missing


# ---------- The models ----------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Download the models Paint a plate's workflows load, at the tested revisions.")
    ap.add_argument("models", nargs="?", default=comfy_folder("models"), help="ComfyUI's models folder (default: the one this pack is in)")
    ap.add_argument("--no-fluid", action="store_true", help="skip ainvfx-fluid: fluid shots from a blank plate switch off")
    ap.add_argument("--no-hdr", action="store_true", help="skip the SDR-to-HDR IC-LoRA (gated): SDR to HDR switches off")
    ap.add_argument("--nvfp4", action="store_true", help=argparse.SUPPRESS)  # FLUX 3 Image Klein's nvfp4 file: tests/gpu_bench.py only
    ap.add_argument("--only", nargs="+", metavar="FILE", help="these files only")
    ap.add_argument("--list", action="store_true", help="print each file with its size and whether it is in place, then stop")
    a = ap.parse_args(argv)
    todo = [m for m in MODELS + ([NVFP4] if a.nvfp4 else [])
            if not (a.no_fluid and m[1].endswith(FLUID)) and not (a.no_hdr and os.path.basename(m[1]) in HDR) and (not a.only or os.path.basename(m[1]) in a.only)]
    if not a.models or not os.path.isdir(a.models):
        print("Name ComfyUI's models folder: python get_models.py path/to/ComfyUI/models", file=sys.stderr)
        return 2
    files = [(repo, path, REVISIONS[repo], f"{folder}/{os.path.basename(path)}") for repo, path, folder in todo]
    if a.list:
        missing = listing(files, a.models, "model files", {rel: SIZES[os.path.basename(rel)] for _, _, _, rel in files})
    else:
        missing = download(files, a.models, "model files")
    missing = {os.path.basename(rel) for rel in missing}
    off = [name for name, group in (("fluid shots", (FLUID,)), ("SDR to HDR", HDR)) if missing & set(group)]
    if off and not a.list:
        print(f"Off while their files are missing: {', '.join(off)}. The rest works without them.")
    return 1 if missing - set(OPTIONAL) else 0


if __name__ == "__main__":
    sys.exit(main())
