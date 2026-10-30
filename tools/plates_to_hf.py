"""Publish test plates to a Hugging Face dataset, with clean metadata and a card.

    HF_TOKEN=hf_... python tools/plates_to_hf.py [--repo AInVFX/ainvfx-paintaplate] --src <folder of MP4 plates> [--dry-run]

What it does, in order:
1. Re-muxes every MP4 into a temporary folder with the streams copied bit for bit and the container metadata replaced.
   ComfyUI's Save Video embeds the whole workflow and prompt in the file, and those carry course notes; the copy keeps
   one provenance line instead (the AI-generated statement the LTX-2.x licence and the AInVFX ethics page ask for).
2. Writes the dataset card (README.md, marked WIP, CC BY 4.0) with a table of the plates. It replaces the card the
   repository was created with.
3. Creates the dataset repository if needed, uploads the folder in one commit and lists what arrived.

Needs huggingface_hub (pip install huggingface_hub) and PyAV (the pack's own requirement). A `hf download` of the
dataset into ComfyUI/input/plates is what tools/pod_setup.sh does with PLATES=1.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import tempfile
from fractions import Fraction

import av

COMMENT = ("AI-generated test plate for AInVFX Paint a plate (github.com/AInVFX/ainvfx-paintaplate). Made in ComfyUI: "
           "LTX 2.5 (Lightricks) made the shot and its sound, from a first frame by MOSS-Image or FLUX 3 Image Klein, or "
           "from text alone. No real people, no real locations, no stock footage. CC BY 4.0, AInVFX: see the dataset card.")

CARD = """---
license: cc-by-4.0
pretty_name: AInVFX Paint a plate test plates
task_categories:
- image-to-video
tags:
- vfx
- comfyui
- synthetic
- video
- plates
size_categories:
- n<1K
---

# AInVFX PaintAPlate test plates

**Work in progress.** The plates of [AInVFX PaintAPlate](https://github.com/AInVFX/ainvfx-paintaplate), the ComfyUI
node pack and page that lets you paint on the first frame of a shot to erase, add or relight, and get the shot back in
the plate's own format. These are the shots the app is tested and demonstrated on.

Every plate is synthetic, made in ComfyUI. **LTX 2.5** (Lightricks) made each shot and its sound track, from a first
frame by **MOSS-Image** or **FLUX 3 Image Klein** (Black Forest Labs), or from text alone. No real people, no real
locations, no stock footage. All are AI-generated: please say so when you show them.

## Use them with PaintAPlate

On a Runpod pod: `PLATES=1 bash tools/runpod_start.sh`, or `bash tools/get_plates.sh` once ComfyUI runs. Either
puts them in ComfyUI's `input/plates` folder, and the Open plate dialog lists them with a thumbnail. On your own machine:

```sh
hf download {repo} --repo-type dataset --include "*.mp4" --local-dir ComfyUI/input/plates
```

## The plates

All at 24 fps, 121 frames (5 seconds), H.264 in MP4 with an AAC track.

{table}

## Licence

CC BY 4.0: use, share and change the plates, with credit to AInVFX.

Notes on the licences of the models that made them, read on 27 and 28 October 2026:

- LTX 2.5 is under the [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x).
  Lightricks claims no rights in its outputs (section 5). The same licence counts a model trained on LTX outputs as a
  derivative of LTX-2.x (section 3.2): read it before you train on these plates.
- FLUX 3 Image Klein is under the FLUX Kommunity License, which does not allow using its outputs to train a similar
  image model.
- MOSS-Image is under Apache 2.0.

AInVFX statement of AI ethics: https://www.ainvfx.com/ai-ethics
"""


def remux(src: str, dst: str) -> dict:
    """Copy the streams of `src` into `dst` with the container metadata replaced by one provenance line."""
    info = {}
    with av.open(src) as i, av.open(dst, "w") as o:
        o.metadata.clear()
        o.metadata["comment"] = COMMENT
        streams = {s: o.add_stream_from_template(s) for s in i.streams if s.type in ("video", "audio")}
        for s_out in streams.values():
            s_out.metadata.clear()
        v = i.streams.video[0]
        rate = v.average_rate or v.guessed_rate or Fraction(24, 1)
        info = {"width": v.codec_context.width, "height": v.codec_context.height, "frames": int(v.frames or 0),
                "fps": float(rate), "codec": v.codec_context.name, "audio": i.streams.audio[0].codec_context.name if i.streams.audio else ""}
        for packet in i.demux(list(streams)):
            if packet.dts is None:
                continue
            packet.stream = streams[packet.stream]
            o.mux(packet)
    return info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--repo", default="AInVFX/ainvfx-paintaplate", help="the dataset repository (default AInVFX/ainvfx-paintaplate)")
    ap.add_argument("--src", required=True, help="the folder of MP4 plates to publish (plates never go in git)")
    ap.add_argument("--private", action="store_true", help="create the repository private")
    ap.add_argument("--dry-run", action="store_true", help="prepare the folder and the card, upload nothing")
    a = ap.parse_args()
    token = os.environ.get("HF_TOKEN", "")
    if not token and not a.dry_run:
        print("Set HF_TOKEN to a Hugging Face token with write access.", file=sys.stderr)
        return 2
    names = sorted(f for f in os.listdir(a.src) if f.lower().endswith(".mp4"))
    if not names:
        print(f"No MP4 plates in {a.src}", file=sys.stderr)
        return 2
    work = tempfile.mkdtemp(prefix="paintaplate_hf_")
    rows = []
    for name in names:
        info = remux(os.path.join(a.src, name), os.path.join(work, name))
        with av.open(os.path.join(work, name)) as c:
            left = {k: v for k, v in c.metadata.items() if k not in ("comment", "encoder", "major_brand", "minor_version", "compatible_brands")}
        if left:
            raise RuntimeError(f"{name}: container metadata survived the remux: {sorted(left)}")
        rows.append(f"| `{name}` | {info['width']} x {info['height']} | {info['frames']} | {info['fps']:g} | {os.path.getsize(os.path.join(work, name)) / 1e6:.1f} MB |")
        print(f"  {name}: {info['width']} x {info['height']}, {info['frames']} frames, metadata replaced")
    table = "| File | Size | Frames | fps | Weight |\n| --- | --- | --- | --- | --- |\n" + "\n".join(rows)
    with open(os.path.join(work, "README.md"), "w", encoding="utf-8") as f:
        f.write(CARD.format(repo=a.repo, table=table))
    print(f"\n{len(names)} plates and the card are ready in {work}")
    if a.dry_run:
        print("Dry run: nothing uploaded. Open the README.md there to check the card.")
        return 0
    from huggingface_hub import HfApi
    api = HfApi(token=token)
    url = api.create_repo(a.repo, repo_type="dataset", private=a.private, exist_ok=True)
    print(f"Repository: {url}")
    api.upload_folder(folder_path=work, repo_id=a.repo, repo_type="dataset",
                      commit_message=f"PaintAPlate test plates: {len(names)} synthetic shots, metadata replaced, WIP card")
    arrived = sorted(f for f in api.list_repo_files(a.repo, repo_type="dataset") if f.endswith(".mp4"))
    missing = sorted(set(names) - set(arrived))
    print(f"Uploaded: {len(arrived)} plates at https://huggingface.co/datasets/{a.repo}")
    if missing:
        print(f"Missing on the Hub: {missing}. Run the script again.", file=sys.stderr)
        return 1
    shutil.rmtree(work, ignore_errors=True)
    print("\nNow take the plates out of git, from the repository root:\n"
          "  git rm -r --quiet tests/plates && git commit -m \"Test plates moved to Hugging Face\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
