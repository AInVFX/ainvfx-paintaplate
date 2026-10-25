"""The four PaintAPlate nodes. Each one fills a gap in core ComfyUI.

Colour conversion, compositing, masks, Klein, LTX and SAM 3 stay in core nodes:
these nodes only load and save plates, fit generated frames to the plate, and
transfer a new light onto it. The heavy maths lives in mathops and plateio.
"""
from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
import torch.nn.functional as F

import comfy.model_management as mm
import comfy.utils
import folder_paths
from comfy_api.v0_0_2 import InputImpl, io, ui

from . import mathops, plateio

Plate = io.Custom("PAINTAPLATE_PLATE")
CATEGORY = "AInVFX/PaintAPlate"
COLOR_SPACES = ["sRGB", "HDR", "HDR ACEScct", "HDR LogC3", "HDR PQ", "linear", "linear ACEScg"]


def resolve(path: str) -> str:
    """'output:sub/dir' reads from the output folder; any other path from the input folder.

    Absolute paths are refused unless PAINTAPLATE_ALLOW_ABSOLUTE=1, which suits a
    workstation and keeps a shared server's disk private.
    """
    path = path.strip()
    root = folder_paths.get_output_directory() if path.startswith("output:") else folder_paths.get_input_directory()
    rel = path.removeprefix("output:")
    if os.path.isabs(rel):
        if os.environ.get("PAINTAPLATE_ALLOW_ABSOLUTE") != "1":
            raise ValueError("Absolute plate paths need PAINTAPLATE_ALLOW_ABSOLUTE=1")
        return rel
    full = os.path.abspath(os.path.join(root, rel))
    if os.path.commonpath([full, os.path.abspath(root)]) != os.path.abspath(root):
        raise ValueError(f"Plate path leaves the ComfyUI folders: {path}")
    return full


def frames_np(images: torch.Tensor):
    for frame in images:
        yield frame.float().cpu().numpy()


def to_image(frames: list[np.ndarray]) -> torch.Tensor:
    return torch.from_numpy(np.stack(frames)).to(device=mm.intermediate_device(), dtype=mm.intermediate_dtype())


def resize(t: torch.Tensor, h: int, w: int) -> torch.Tensor:
    """(N, H, W[, C]) to (N, h, w[, C]), bicubic, antialiased when shrinking."""
    if t.shape[1:3] == (h, w):
        return t
    x = t.unsqueeze(-1) if t.ndim == 3 else t
    x = F.interpolate(x.movedim(-1, 1).float(), size=(h, w), mode="bicubic", antialias=True, align_corners=False)
    x = x.movedim(1, -1)
    return x[..., 0] if t.ndim == 3 else x


class LoadPlate(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_LoadPlate",
            display_name="Load Plate",
            category=CATEGORY,
            description="Loads a video file or a folder of frames (EXR, PNG, TIFF, DPX) at full precision, "
                        "with the spec Save Plate needs. Pixels stay in the plate's colour space: convert "
                        "them with Convert Image Color Space.",
            search_aliases=["plate", "image sequence", "exr sequence", "load frames"],
            inputs=[
                io.String.Input("path", tooltip="A file or a folder of frames in ComfyUI's input folder. "
                                                "Start with 'output:' to read from the output folder."),
                io.Int.Input("max_frames", default=121, min=1, max=1024,
                             tooltip="Frames to load from the start. 121 frames are 5 s at 24 fps."),
                io.Boolean.Input("pad_8n1", default=False,
                                 tooltip="Repeat the last frame up to 8k+1 frames, the length LTX needs. "
                                         "'frames' keeps the real count."),
            ],
            outputs=[
                io.Image.Output(display_name="images"),
                io.Mask.Output(display_name="alpha"),
                Plate.Output(display_name="plate"),
                io.Float.Output(display_name="fps"),
                io.Int.Output(display_name="frames"),
                io.String.Output(display_name="spec"),
            ],
        )

    @classmethod
    def fingerprint_inputs(cls, path, max_frames, pad_8n1):
        full = resolve(path)
        files = plateio.find_sequence(full) if os.path.isdir(full) else [full]
        return f"{path}|{max_frames}|{pad_8n1}|{len(files)}|{max(os.path.getmtime(f) for f in files)}"

    @classmethod
    def execute(cls, path, max_frames, pad_8n1) -> io.NodeOutput:
        full = resolve(path)
        spec = plateio.probe_plate(full)
        if spec["kind"] == "video":  # core's decoder, trimmed before decoding
            parts = [InputImpl.VideoFromFile(full, duration=max_frames / spec["fps"]).get_components()]
        else:  # frames decode in parallel: PyAV releases the GIL while decoding
            with ThreadPoolExecutor(min(16, os.cpu_count() or 4)) as pool:
                parts = list(pool.map(lambda f: InputImpl.VideoFromFile(f).get_components(), spec["files"][:max_frames]))
        images = torch.cat([p.images for p in parts])[:max_frames]
        if parts[0].alpha is not None:
            alpha = torch.cat([p.alpha[..., -1] for p in parts])[:max_frames]
        else:
            alpha = torch.ones(images.shape[:3], dtype=images.dtype, device=images.device)
        count = images.shape[0]
        spec.update(frames=count, color_space_guess=plateio.guess_color_space(spec))
        if pad_8n1 and (extra := plateio.pad_count_8n1(count) - count):
            images = torch.cat([images, images[-1:].expand(extra, -1, -1, -1)])
            alpha = torch.cat([alpha, alpha[-1:].expand(extra, -1, -1)])
        device, dtype = mm.intermediate_device(), mm.intermediate_dtype()
        return io.NodeOutput(images.to(device=device, dtype=dtype), alpha.to(device=device, dtype=dtype),
                             spec, float(spec["fps"]), count, plateio.spec_json(spec))


class SavePlate(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_SavePlate",
            display_name="Save Plate",
            category=CATEGORY,
            description="Writes frames in the plate's own format: same file type, bit depth, frame numbers, "
                        "colour tags, timecode and audio. For EXR, every other layer and header attribute "
                        "is kept. Outside 'changed', the exact source pixels are written back.",
            is_output_node=True,
            inputs=[
                io.Image.Input("images", tooltip="Frames in the plate's colour space."),
                Plate.Input("plate"),
                io.String.Input("filename_prefix", default="paintaplate/shot"),
                io.Boolean.Input("keep_untouched", default=True,
                                 tooltip="Copy the source pixels wherever 'changed' is zero. "
                                         "Turn off when every pixel changed, as after a relight."),
                io.Mask.Input("changed", optional=True, tooltip="Where pixels may differ from the plate."),
                io.Mask.Input("alpha", optional=True, tooltip="New alpha. Leave empty to keep the source alpha."),
            ],
        )

    @classmethod
    def execute(cls, images, plate, filename_prefix, keep_untouched, changed=None, alpha=None) -> io.NodeOutput:
        spec = plate
        out_dir = os.path.join(folder_paths.get_output_directory(), filename_prefix)
        os.makedirs(out_dir, exist_ok=True)
        count = min(images.shape[0], spec["frames"])
        written, notes = [], []
        if spec["kind"] == "video":
            writer = plateio.VideoWriter(spec, os.path.join(out_dir, os.path.basename(spec["source"])),
                                         audio_source=spec["source"])
            bar = comfy.utils.ProgressBar(count)
            for frame in frames_np(images[:count]):
                writer.write(frame)
                bar.update(1)
            writer.close()
            written, notes = [writer.path], writer.notes
        else:
            has_alpha = alpha is not None
            codec, pix_fmt, options = plateio.still_target(spec, has_alpha)
            bar = comfy.utils.ProgressBar(count)
            for i, rgb in enumerate(frames_np(images[:count])):
                bar.update(1)
                src = spec["files"][i]
                out = plateio.output_frame_name(spec, i, out_dir)
                a = alpha[i].float().cpu().numpy() if has_alpha else None
                keep = None
                if keep_untouched and changed is not None:
                    keep = changed[min(i, changed.shape[0] - 1)].float().cpu().numpy() <= 1.0 / 1024
                if spec["ext"] == ".exr" and plateio.OpenEXR is not None:
                    plateio.write_exr_like(src, rgb, a, out, keep=keep)
                else:
                    if keep is not None and codec != "exr":  # exact integers from the source
                        rgb = np.where(keep[..., None], plateio.read_native(src, has_alpha),
                                       plateio.to_uint16(rgb, a))
                        a = None
                    with open(out, "wb") as f:
                        f.write(plateio.encode_still(rgb, a, codec, pix_fmt, options))
                written.append(out)
            if spec["ext"] == ".exr" and plateio.OpenEXR is None:
                notes.append("OpenEXR is not installed: extra EXR layers were not copied.")
        text = f"{len(written)} file(s) in {out_dir}\n" + "\n".join(notes + [os.path.basename(p) for p in written[:3]])
        return io.NodeOutput(ui=ui.PreviewText(text))


class FitToPlate(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_FitToPlate",
            display_name="Fit to Plate",
            category=CATEGORY,
            description="Prepares generated frames for compositing: resizes them to the plate, aligns them "
                        "to it, matches colour and grain around the edit, and returns the edit mask at "
                        "plate size, grown and softened. Feed both outputs to Image Composite Masked.",
            inputs=[
                io.Image.Input("plate", tooltip="The plate, in the same colour space as 'image'."),
                io.Image.Input("image", tooltip="Generated frames, any size."),
                io.Mask.Input("mask", optional=True, tooltip="The edited area, any size. Empty means no edit."),
                io.Boolean.Input("align", default=True, tooltip="Measure and remove a small shift per frame."),
                io.Float.Input("max_shift", default=8.0, min=0.0, max=64.0, step=0.5,
                               tooltip="Largest shift in pixels treated as misalignment."),
                io.Boolean.Input("match_color", default=True,
                                 tooltip="Match colour to the plate in a band around the edit."),
                io.Float.Input("grain", default=1.0, min=0.0, max=2.0, step=0.05,
                               tooltip="Add grain up to the plate's level. 0 adds none."),
                io.Int.Input("grow", default=8, min=0, max=256, tooltip="Grow the mask, in plate pixels."),
                io.Int.Input("feather", default=12, min=0, max=256, tooltip="Soften the mask edge, in plate pixels."),
            ],
            outputs=[io.Image.Output(display_name="image"), io.Mask.Output(display_name="mask")],
        )

    @classmethod
    def execute(cls, plate, image, align, max_shift, match_color, grain, grow, feather, mask=None) -> io.NodeOutput:
        n, h, w = min(plate.shape[0], image.shape[0]), plate.shape[1], plate.shape[2]
        image = resize(image[:n], h, w)
        if mask is None:
            mask = torch.zeros((n, h, w))
        mask = resize(mask[:n] if mask.shape[0] >= n else mask[:1].expand(n, -1, -1), h, w).clamp(0, 1)
        scale = min(1.0, 512 / max(h, w))  # alignment runs on a small structure map
        target = np.median([mathops.noise_sigma(f) for f in frames_np(plate[: n : max(1, n // 3)][:3])], 0)  # the plate's grain, once
        reach = max(8, grow + feather) + 2 * feather
        bar = comfy.utils.ProgressBar(n)

        def small(a):
            return mathops.ndimage.zoom(a, scale, order=1) if scale < 1 else a

        def fit(args):
            i, p, g, m = args
            if align:
                keep = small(1.0 - m)
                dy, dx = mathops.phase_shift(small(mathops.structure(p)) * keep, small(mathops.structure(g)) * keep, max_shift * scale)
                if dy or dx:
                    g = mathops.ndimage.shift(g, (dy / scale, dx / scale, 0), order=1, mode="nearest")
            ys, xs = np.nonzero(m > 0)
            if len(ys):  # colour and grain only where the edit is, plus a margin
                y0, y1 = max(0, ys.min() - reach), min(h, ys.max() + reach + 1)
                x0, x1 = max(0, xs.min() - reach), min(w, xs.max() + reach + 1)
                crop, gc = (slice(y0, y1), slice(x0, x1)), g[y0:y1, x0:x1]
                if match_color:
                    gc = mathops.match_color(gc, p[crop], mathops.ring(m[crop], max(8, grow + feather)))
                if grain > 0:
                    gc = mathops.add_grain(gc, target, np.random.default_rng(i), grain)
                g = g.copy()
                g[crop] = gc
            if grow:
                m = (mathops.ndimage.distance_transform_edt(m < 0.5) <= grow).astype(np.float32)
            if feather:
                m = mathops.ndimage.gaussian_filter(m, feather / 2.0)
            bar.update(1)
            return g.astype(np.float32), np.clip(m, 0, 1).astype(np.float32)

        with ThreadPoolExecutor(min(16, os.cpu_count() or 4)) as pool:  # numpy and scipy release the GIL
            done = list(pool.map(fit, zip(range(n), frames_np(plate[:n]), frames_np(image), frames_np(mask))))
        return io.NodeOutput(to_image([d[0] for d in done]), to_image([d[1] for d in done]))


class RelightTransfer(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_RelightTransfer",
            display_name="Relight Transfer",
            category=CATEGORY,
            description="Moves the new light of a regenerated shot onto the plate. Light, shadows and "
                        "reflections come from the regeneration; texture, grain, sharpness and highlights "
                        "stay the plate's. All three inputs are linear light.",
            inputs=[
                io.Image.Input("plate", tooltip="The plate in linear light, any size."),
                io.Image.Input("source", tooltip="The plate as the model saw it, in linear light."),
                io.Image.Input("relit", tooltip="The regenerated shot, same size as 'source', in linear light."),
                io.Int.Input("radius", default=16, min=1, max=256,
                             tooltip="Detail size kept from the plate. Lower lets sharper new shadows through."),
                io.Float.Input("strength", default=1.0, min=0.0, max=2.0, step=0.05),
                io.Boolean.Input("align", default=True, tooltip="Remove a small shift of 'relit' first."),
            ],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, plate, source, relit, radius, strength, align) -> io.NodeOutput:
        n = min(plate.shape[0], source.shape[0], relit.shape[0])
        bar = comfy.utils.ProgressBar(n)

        def one(args):
            p, s, r = args
            if align:
                dy, dx = mathops.phase_shift(mathops.structure(s), mathops.structure(r), 8.0)
                if dy or dx:
                    r = mathops.ndimage.shift(r, (dy, dx, 0), order=1, mode="nearest")
            half = (0.5, 0.5, 1)  # light is smooth: its ratio is computed at half size, then upsampled
            out = mathops.relight(p, mathops.ndimage.zoom(s, half, order=1), mathops.ndimage.zoom(r, half, order=1),
                                  max(1, radius // 2), strength)
            bar.update(1)
            return out.astype(np.float32)

        with ThreadPoolExecutor(min(16, os.cpu_count() or 4)) as pool:
            out = list(pool.map(one, zip(frames_np(plate[:n]), frames_np(source[:n]), frames_np(relit[:n]))))
        return io.NodeOutput(to_image(out))


NODES = [LoadPlate, SavePlate, FitToPlate, RelightTransfer]
