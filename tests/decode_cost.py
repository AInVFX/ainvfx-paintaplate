"""What a video VAE's decode costs, and where its tiles show, on one latent, in a process of its own on a GPU machine:
the seconds and the peak VRAM of each way to decode, and each way's bands against the whole decode (hdr_plate.py
bands). Run it with ComfyUI's Python:

  /data/ComfyUI/.venv/bin/python tests/decode_cost.py --comfy /data/ComfyUI --latent <file.latent> --out <folder>
  /data/ComfyUI/.venv/bin/python tests/decode_cost.py --comfy /data/ComfyUI --plate <movie> --dtype default --space none --out <folder>

The latent comes from `hdr_plate.py finish --latent`; with --plate, the VAE encodes the movie's first 121 frames at
1920 x 1088, a stand-in for an SDR pass's latent, once per --encodes way (`whole`, or `T/O`: the VAE's tiled encode with
tiles of T px and O px of overlap, as an IC-LoRA guide encoded in tiles), each timed with its peak, and decodes the
latent of the first. A way is `whole`, one decode of the whole latent; `T/O`, core's VAE
Decode (Tiled) with tiles of T px and O px of overlap, at most a quarter of the tile; or `T/Ov`, the VAE's own tiled
decode called with that overlap, up to half a tile. Every way decodes in 128-frame temporal tiles with 32 frames of
overlap, as the pack's workflows do. --dtype is the VAE's compute dtype: fp32, as SDR to HDR decodes, or `default`, the
VAE's own, as the SDR passes decode. --space ACEScct writes the frames in ACEScg (scene-linear) and reads the bands in
stops; `none` writes them as decoded and reads the bands in 8-bit steps. The peaks are torch's counts for this process,
allocated and reserved, each way starting from an empty cache with the VAE loaded. Every --every th frame is written.
"""
import argparse
import gc
import os
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
sys.path.insert(0, HERE)

VAE = "ltx-2.5-video-vae-conv-bf16.safetensors"  # LTX 2.5's video VAE, as tools/build_workflows.py names it


def way(text: str) -> dict:
    """`whole`, `T/O` or `T/Ov` as {name, tile, overlap, own}."""
    if text == "whole":
        return {"name": text, "tile": 0, "overlap": 0, "own": False}
    own = text.endswith("v")
    tile, overlap = (int(v) for v in text.rstrip("v").split("/"))
    if not own and overlap * 4 > tile:
        raise SystemExit(f"{text}: VAE Decode (Tiled) takes an overlap of at most a quarter of the tile; "
                         f"{tile}/{overlap}v calls the VAE's own tiled decode")
    return {"name": text, "tile": tile, "overlap": overlap, "own": own}


def decode(vae, latent, w):
    """The frames (N, H, W, 3) of one way to decode `latent`."""
    import nodes
    if not w["own"]:  # a tile larger than the frame decodes the whole latent in one piece, with no blend
        return nodes.VAEDecodeTiled().decode(vae, {"samples": latent}, w["tile"] or 4096, w["overlap"] or 64, 128, 32)[0]
    c, t = vae.spacial_compression_decode(), vae.temporal_compression_decode()
    images = vae.decode_tiled(latent, tile_x=w["tile"] // c, tile_y=w["tile"] // c, overlap=w["overlap"] // c,
                              tile_t=max(2, 128 // t), overlap_t=max(1, min(128 // t // 2, 32 // t)))
    return images.reshape(-1, *images.shape[-3:])


def plate_pixels(path: str, frames: int = 121, width: int = 1920, height: int = 1088):
    import av
    import torch
    import comfy.utils
    with av.open(path) as c:
        imgs = [f.to_ndarray(format="rgb24") for _, f in zip(range(frames), c.decode(video=0))]
    x = torch.from_numpy(np.stack(imgs)).float() / 255.0
    return comfy.utils.common_upscale(x.movedim(-1, 1), width, height, "bilinear", "disabled").movedim(1, -1)


def measured(fn):
    """fn()'s result, its seconds and its peaks in GiB, allocated and reserved, from an empty cache."""
    import torch
    gc.collect()
    torch.cuda.synchronize()
    torch.cuda.empty_cache()
    torch.cuda.reset_peak_memory_stats()
    t0 = time.perf_counter()
    out = fn()
    torch.cuda.synchronize()
    return out, time.perf_counter() - t0, torch.cuda.max_memory_allocated() / 2 ** 30, torch.cuda.max_memory_reserved() / 2 ** 30


def main(a):
    sys.path.insert(0, a.comfy)
    import torch
    with torch.inference_mode():  # as ComfyUI runs its nodes: core's tiled decode returns inference tensors
        run(a)


def run(a):
    import torch
    import safetensors.torch
    import nodes
    import hdr_plate
    import ocio
    import plateio
    vae = nodes.VAELoader().load_vae(a.vae)[0]
    if a.dtype != "default":
        vae = vae.clone()
        vae.vae_dtype = {"fp32": torch.float32, "bf16": torch.bfloat16, "fp16": torch.float16}[a.dtype]
        vae.patcher.set_model_compute_dtype(vae.vae_dtype)
    if a.latent:
        data = safetensors.torch.load_file(a.latent)  # as core's Load Latent reads it
        latent = data["latent_tensor"].float() * (1.0 if "latent_format_version_0" in data else 1.0 / 0.18215)
        source = a.latent
    else:
        pixels, latent, encodes = plate_pixels(a.plate), None, []
        vae.encode(pixels[:9, :64, :64])  # the VAE on the GPU before the first measure
        for e in a.encodes:
            tile, overlap = (0, 0) if e == "whole" else (int(v) for v in e.split("/"))
            lat, seconds, peak, reserved = measured(lambda: vae.encode(pixels) if not tile else
                                                    vae.encode_tiled(pixels, tile_x=tile, tile_y=tile, overlap=overlap))
            encodes.append((e, seconds, peak, reserved))
            latent = lat if latent is None else latent
            print(f"encode {e}: {seconds:.1f} s, peak {peak:.2f} GiB allocated, {reserved:.2f} GiB reserved", flush=True)
        source = f"{a.plate}, encoded {a.encodes[0]}"
    vae.decode(latent[:, :, :1, :4, :4])  # the VAE on the GPU and its kernels chosen before the first measure
    os.makedirs(a.out, exist_ok=True)
    rows, folders = [], {}
    for w in map(way, a.ways):
        resident = torch.cuda.memory_allocated() / 2 ** 30
        images, seconds, peak, reserved = measured(lambda: decode(vae, latent, w))
        keep = list(range(0, images.shape[0], a.every))
        frames = [images[i].float().numpy() for i in keep]
        n, (h, wd) = images.shape[0], images.shape[1:3]
        del images
        if a.space != "none":
            frames = ocio.convert(frames, ocio.BUILTIN, a.space, "ACEScg")
        folder = folders[w["name"]] = os.path.join(a.out, w["name"].replace("/", "_"))
        os.makedirs(folder, exist_ok=True)
        plateio.write_exrs(lambda j: frames[j], [os.path.join(folder, f"f_{i + 1:05d}.exr") for i in keep])
        rows.append([w, seconds, resident, peak, reserved, None])
        print(f"{w['name']}: {seconds:.1f} s, peak {peak:.2f} GiB allocated, {reserved:.2f} GiB reserved", flush=True)
    whole = folders.get("whole")
    for row in rows:
        w = row[0]
        if whole and w["name"] != "whole":
            name = w["name"].replace("/", "_")
            row[5] = hdr_plate.bands(whole, folders[w["name"]], w["tile"], w["overlap"], steps=a.space == "none", every=1,
                                     out=os.path.join(a.out, f"bands_{name}.md"), sheet=os.path.join(a.out, f"sheet_{name}.png"))
    unit = "steps" if a.space == "none" else "stops"
    lines = [f"# Decode cost: `{source}`", "",
             f"Latent {tuple(latent.shape)}: {n} frames at {wd} x {h}. VAE `{a.vae}`, computed in {a.dtype}. "
             f"{torch.cuda.get_device_name()}. GiB means 2^30 bytes; the VAE's weights stay resident through every way.", "",
             f"| Way | Seconds | VAE resident, GiB | Peak allocated, GiB | Peak reserved, GiB | Largest band swing, {unit} | Bands over the limit |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    if not a.latent:
        lines[4:4] = ["| Encode | Seconds | Peak allocated, GiB | Peak reserved, GiB |", "| --- | --- | --- | --- |"] + [
            f"| {e} | {sec:.1f} | {pk:.2f} | {rs:.2f} |" for e, sec, pk, rs in encodes] + [""]
    for w, seconds, resident, peak, reserved, b in rows:
        swing = "reference" if b is None else f"{b['largest']:.3f}"
        over = "" if b is None else f"{len(b['shows'])} of {len(b['rows'])}"
        lines.append(f"| {w['name']} | {seconds:.1f} | {resident:.2f} | {peak:.2f} | {reserved:.2f} | {swing} | {over} |")
    text = "\n".join(lines) + "\n"
    with open(os.path.join(a.out, "decode_cost.md"), "w") as f:
        f.write(text)
    print(text)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--comfy", required=True, help="ComfyUI's folder, whose core and models the decode uses")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--latent", help="a .latent file, as core's Save Latent writes it")
    src.add_argument("--plate", help="a movie whose first 121 frames the VAE encodes whole")
    ap.add_argument("--out", required=True, help="the folder of the frames, the bands, the sheets and decode_cost.md")
    ap.add_argument("--vae", default=VAE, help="the VAE's file in ComfyUI's models/vae folder")
    ap.add_argument("--dtype", default="fp32", choices=("fp32", "bf16", "fp16", "default"))
    ap.add_argument("--space", default="ACEScct", help="the decoded values' colour space, or none")
    ap.add_argument("--ways", nargs="+", default=["whole", "512/128", "512/64", "256/64", "256/128v"])
    ap.add_argument("--every", type=int, default=10)
    ap.add_argument("--encodes", nargs="+", default=["whole"], help="with --plate: whole, or T/O for the VAE's tiled encode")
    main(ap.parse_args())
