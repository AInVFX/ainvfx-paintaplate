"""The twelve Paint a plate nodes. Each one does what core ComfyUI cannot.

Compositing, masks, Klein, LTX and SAM 3.1 stay in core nodes. These nodes load and save plates in their own format,
convert colour with OpenColorIO, fit generated frames to the plate, transfer a new light onto it, keep a matte on what an
edit made, level an erase's fill, fit an HDR shot to the plate, save frames and movies several at once, show a shot while LTX samples it, and build the
keyframe control video of a fluid shot. Each node converts tensors and calls plateio (files), mathops (pixels) or ocio
(colour), which are tested without torch or ComfyUI.
"""
from __future__ import annotations

import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import torch
import torch.nn.functional as F

import comfy.model_management as mm
import comfy.sd
import comfy.utils
import folder_paths
from comfy_api.v0_0_2 import io
from comfy_execution.utils import get_executing_context
from PIL import Image
from server import PromptServer

from . import folders, mathops, ocio, plateio


Plate = io.Custom("PAINTAPLATE_PLATE")
WORKERS = min(16, os.cpu_count() or 4)  # frames in parallel: numpy, scipy and PyAV release the GIL
CATEGORY = "AInVFX/Paint a plate"



resolve, output_folder = folders.plate_path, folders.output_folder


class Stop:
    """ComfyUI's interrupt check for a frame loop, called before each frame: it raises as soon as the person stops the job.
    ComfyUI clears its flag when the check raises, and frames are made in worker threads: the first raise is remembered,
    so every later call raises too and the frames still queued end at once."""

    def __init__(self):
        self.stopped = False

    def __call__(self):
        if self.stopped:
            raise mm.InterruptProcessingException()
        try:
            mm.throw_exception_if_processing_interrupted()
        except mm.InterruptProcessingException:
            self.stopped = True
            raise


def stoppable(at):
    """`at(i)`, the frame function of a loop that plateio or mathops runs, with the interrupt check before each frame."""
    stop = Stop()

    def frame(i):
        stop()
        return at(i)
    return frame


def frames_np(images: torch.Tensor):
    stop = Stop()
    for frame in images:
        stop()
        yield frame.float().cpu().numpy()


def to_image(frames) -> torch.Tensor:
    """Frames as an IMAGE batch: an array of frames is taken as it is, with no copy; a list of frames is stacked."""
    batch = frames if isinstance(frames, np.ndarray) else np.stack(frames)
    return torch.from_numpy(batch).to(device=mm.intermediate_device(), dtype=mm.intermediate_dtype())


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
                        "them with Color Space (OCIO).",
            search_aliases=["plate", "image sequence", "exr sequence", "load frames"],
            inputs=[
                io.String.Input("path", tooltip="A file, a folder of frames or a frame pattern (shot.####.exr) in ComfyUI's "
                                                "input folder. Start with 'output:' to read from the output folder."),
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
        files = plateio.find_sequence(full) if plateio.is_sequence(full) else [full]
        return f"{path}|{max_frames}|{pad_8n1}|{len(files)}|{max(os.path.getmtime(f) for f in files)}"

    @classmethod
    def execute(cls, path, max_frames, pad_8n1) -> io.NodeOutput:
        full = resolve(path)
        spec = plateio.probe_plate(full)
        if spec["kind"] == "video":  # our decoder: core's pictures, each frame into its place, the padding too
            bar = comfy.utils.ProgressBar(1)
            rgb, a, count = plateio.decode_video(full, max_frames, spec["fps"], pad_8n1)
            bar.update(1)
            images, extra = torch.from_numpy(rgb), rgb.shape[0] - count
            alpha = None if a is None else torch.from_numpy(a)
        else:  # an image sequence: the files decode in parallel, each into its place, the padding too
            files = spec["files"][:max_frames]
            bar, stop = comfy.utils.ProgressBar(len(files)), Stop()

            def each(i):
                stop()
                bar.update(1)
            rgb, a, count = plateio.decode_frames(files, pad_8n1, WORKERS, each)
            images, extra = torch.from_numpy(rgb), rgb.shape[0] - count
            alpha = None if a is None else torch.from_numpy(a)
        if alpha is None:  # an opaque plate: one frame of ones stands for every frame, and takes one frame of memory
            alpha = torch.ones((1, *images.shape[1:3]), dtype=images.dtype, device=images.device).expand(count + extra, -1, -1)
        spec.update(frames=count, color_space_guess=plateio.guess_color_space(spec))
        device, dtype = mm.intermediate_device(), mm.intermediate_dtype()
        return io.NodeOutput(images.to(device=device, dtype=dtype), alpha.to(device=device, dtype=dtype),
                             spec, float(spec["fps"]), count, plateio.spec_json(spec))


class ColorSpace(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_ColorSpace",
            display_name="Color Space (OCIO)",
            category=CATEGORY,
            description="Converts frames between two colour spaces of an OpenColorIO config, several frames at once. "
                        "@model is the sRGB-encoded Rec.709 the models see, entered with core's tone mapping of values "
                        "above 1.0, which 'peak' or 'peak_of' undoes on the way out; @linear is that space in linear "
                        "light. The second output is the peak of that tone mapping. Alpha is not converted.",
            search_aliases=["ocio", "opencolorio", "colour space", "color space", "aces"],
            inputs=[
                io.Image.Input("image"),
                io.String.Input("config", default=ocio.BUILTIN,
                                tooltip="$OCIO for the config the OCIO environment variable names, or a built-in config "
                                        "such as ocio://studio-config-latest."),
                io.String.Input("source", default="@model", tooltip="A colour space of the config (a name, an alias or a "
                                "role such as scene_linear), or @model or @linear."),
                io.String.Input("destination", default="@model", tooltip="The same, for the result."),
                io.Image.Input("peak_of", optional=True,
                               tooltip="The batch these frames are a part of. Into @model, the tone mapping takes that batch's "
                                       "peak: a frame converted alone has the values it has in the whole batch converted. "
                                       "Out of @model, the plate the frames were made from, in 'destination': the tone "
                                       "mapping of its peak is undone, so new content comes back at the plate's levels."),
                io.Float.Input("peak", optional=True, force_input=True,
                               tooltip="That peak as a number: the second output of the plate's own Color Space (OCIO). "
                                       "Used in place of 'peak_of', so the plate is read once."),
            ],
            outputs=[io.Image.Output(display_name="image"), io.Float.Output(display_name="peak")],
        )

    @classmethod
    def execute(cls, image, config, source, destination, peak_of=None, peak=None) -> io.NodeOutput:
        if source == destination:
            return io.NodeOutput(image, 1.0)
        if peak is None and peak_of is not None and ocio.MODEL in (source, destination):  # the plate's peak, in its own space
            peak = ocio.batch_peak(frames_np(peak_of), config, destination if source == ocio.MODEL else source)
        if source == ocio.MODEL and peak is not None and peak > ocio.TONE_ABOVE:
            logging.info("[Paint a plate] Color Space (OCIO): model space's tone mapping undone, peak %.2f.", peak)
        out, peak = ocio.convert_with_peak(frames_np(image), config, source, destination, peak)
        return io.NodeOutput(to_image(out), peak)


class SavePlate(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_SavePlate",
            display_name="Save Plate",
            category=CATEGORY,
            description="Writes frames in the plate's own format: same file type, bit depth, frame numbers, "
                        "colour tags, timecode and audio. For EXR, every other layer and header attribute "
                        "is kept, and the data window grows only to hold an edit outside it. The plate's own "
                        "alpha is kept as it is. Outside 'changed', the exact source pixels are written back.",
            is_output_node=True,
            inputs=[
                io.Image.Input("images", tooltip="Frames in the plate's colour space."),
                Plate.Input("plate"),
                io.String.Input("filename_prefix", default="paintaplate/shot",
                                tooltip="Folder under ComfyUI's output folder; the frames keep the plate's names."),
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
        out_dir = output_folder(filename_prefix)
        os.makedirs(out_dir, exist_ok=True)
        count = min(images.shape[0], spec["frames"])
        written, notes = [], []
        if spec["kind"] == "video":
            writer = plateio.VideoWriter(spec, os.path.join(out_dir, os.path.basename(spec["source"])),
                                         audio_source=spec["source"])
            bar = comfy.utils.ProgressBar(count)
            src = plateio.SourceFrames(spec["source"], writer.pix_fmt) if keep_untouched and changed is not None else None
            try:
                for i, frame in enumerate(frames_np(images[:count])):
                    keep = None if src is None else plateio.untouched(changed[min(i, changed.shape[0] - 1)].float().cpu().numpy())
                    writer.write(frame, keep=keep, source=None if src is None else src.next())
                    bar.update(1)
            except BaseException:  # stopped or failed: no half-written plate stays in the export folder
                try:
                    writer.close()
                finally:
                    if os.path.exists(writer.path):
                        os.remove(writer.path)
                raise
            finally:
                if src is not None:
                    src.close()
            writer.close()
            written, notes = [writer.path], writer.notes
        else:
            bar = comfy.utils.ProgressBar(count)
            for i, rgb in enumerate(frames_np(images[:count])):
                bar.update(1)
                a = alpha[i].float().cpu().numpy() if alpha is not None else None
                keep = None
                if keep_untouched and changed is not None:
                    keep = plateio.untouched(changed[min(i, changed.shape[0] - 1)].float().cpu().numpy())  # what the matte shows as 0
                written.append(plateio.write_still(spec, i, rgb, a, keep, out_dir))
            if spec["ext"] == ".exr" and plateio.OpenEXR is None:
                notes.append("Extra EXR layers not copied: OpenEXR is not installed.")
        lines = [f"Save Plate: {len(written)} {'file' if len(written) == 1 else 'files'} written to {out_dir}."] + notes
        if written:
            lines.append("First files: " + ", ".join(os.path.basename(p) for p in written[:3]) + ".")
        text = "\n  ".join(lines)
        # the files themselves, under a key ComfyUI's frontend ignores: the job index keeps the record while they exist,
        # and the page finds the render's folder from them
        sub = os.path.relpath(out_dir, folder_paths.get_output_directory()).replace(os.sep, "/")
        return io.NodeOutput(ui={"text": [text], "files": [{"filename": os.path.basename(p), "subfolder": sub, "type": "output"} for p in written]})


class FitToPlate(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_FitToPlate",
            display_name="Fit to Plate",
            category=CATEGORY,
            description="Prepares generated frames for compositing: resizes them to the plate, aligns them "
                        "to it, matches colour and grain at the edge of the edit, and returns the edit mask "
                        "at plate size, grown, softened and steady from frame to frame. Feed both outputs "
                        "to Image Composite Masked.",
            inputs=[
                io.Image.Input("plate", tooltip="The plate, in the same colour space as 'image'."),
                io.Image.Input("image", tooltip="Generated frames, any size."),
                io.Mask.Input("mask", optional=True, tooltip="The edited area, any size. Empty means no edit."),
                io.Boolean.Input("align", default=True,
                                 tooltip="Measure a small shift per frame, smooth it over time, remove it."),
                io.Float.Input("max_shift", default=8.0, min=0.0, max=64.0, step=0.5,
                               tooltip="Largest shift in pixels treated as misalignment."),
                io.Boolean.Input("match_color", default=True,
                                 tooltip="Match colour and exposure to the plate at the edge of the edit, "
                                         "spread smoothly inside it."),
                io.Float.Input("grain", default=1.0, min=0.0, max=2.0, step=0.05,
                               tooltip="Add grain up to the plate's level. 0 adds none."),
                io.Int.Input("grow", default=8, min=0, max=256, tooltip="Grow the mask, in plate pixels."),
                io.Int.Input("feather", default=12, min=0, max=256, tooltip="Soften the mask edge, in plate pixels."),
                io.Int.Input("steady", default=2, min=0, max=12, optional=True,
                             tooltip="Frames on each side over which the mask edge, the shift and the colour "
                                     "match are smoothed. 0 treats every frame on its own."),
            ],
            outputs=[io.Image.Output(display_name="image"), io.Mask.Output(display_name="mask")],
        )

    @classmethod
    def execute(cls, plate, image, align, max_shift, match_color, grain, grow, feather, mask=None,
                steady=2) -> io.NodeOutput:
        n, h, w = min(plate.shape[0], image.shape[0]), plate.shape[1], plate.shape[2]
        if mask is None or not bool(mask.any()):  # nothing to composite (a relight alone): the plate stands, nothing is fitted
            return io.NodeOutput(plate[:n], torch.zeros((n, h, w), dtype=torch.float32))
        image = image[:n]  # at its own size: Fit to Plate enlarges only the window around the matte, with a Lanczos-3
        masks = np.zeros((1, 8, 8), np.float32) if mask is None else mask[:n].float().cpu().numpy()
        bar = comfy.utils.ProgressBar(2 * n)
        images, out = mathops.fit_to_plate(
            n, h, w, stoppable(lambda i: plate[i].float().cpu().numpy()), lambda i: image[i].float().cpu().numpy(), masks,
            align=align, max_shift=max_shift, match_color=match_color, grain=grain, grow=grow, feather=feather,
            steady=steady, workers=WORKERS, progress=lambda: bar.update(1))
        return io.NodeOutput(to_image(images), to_image(out))


class CompositeFrames(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_CompositeFrames",
            display_name="Composite Frames",
            category=CATEGORY,
            description="The source inside the mask and the destination around it, at the size given, one frame at a "
                        "time. Each input is sized with a bilinear filter. The pictures are those of Image Scale then "
                        "Image Composite Masked, which hold the whole shot at that size nine times while they work. "
                        "This node holds the result once.",
            inputs=[
                io.Image.Input("destination", tooltip="The frames around the mask, any size."),
                io.Image.Input("source", tooltip="The frames inside the mask, any size."),
                io.Mask.Input("mask", tooltip="Where the source goes, any size: 1 is the source, 0 the destination."),
                io.Int.Input("width", default=1920, min=16, max=16384, tooltip="Width of the result."),
                io.Int.Input("height", default=1088, min=16, max=16384, tooltip="Height of the result."),
            ],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, destination, source, mask, width, height) -> io.NodeOutput:
        def sized(t):  # one frame (H, W, C) or one mask (H, W) at the result's size, as Image Scale's bilinear filter makes it
            x = (t[..., :3] if t.ndim == 3 else t.unsqueeze(-1)).float().movedim(-1, 0).unsqueeze(0)
            if x.shape[2:] != (height, width):
                x = comfy.utils.common_upscale(x, width, height, "bilinear", "disabled")
            x = x[0].movedim(0, -1).cpu().numpy()
            return x if t.ndim == 3 else x[..., 0]

        n, stop = destination.shape[0], Stop()
        bar = comfy.utils.ProgressBar(n)
        out = torch.empty((n, height, width, 3), dtype=torch.float32)
        for i in range(n):  # a shorter source or mask repeats, as in core's composite
            stop()
            out[i] = torch.from_numpy(mathops.composite(sized(destination[i]), sized(source[i % source.shape[0]]),
                                                        sized(mask[i % mask.shape[0]])))
            bar.update(1)
        return io.NodeOutput(out.to(device=mm.intermediate_device(), dtype=mm.intermediate_dtype()))


class RelightTransfer(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_RelightTransfer",
            display_name="Relight Transfer",
            category=CATEGORY,
            description="Moves the new light of a regenerated shot onto the plate. Light, shadows and "
                        "reflections come from the regeneration; texture, grain, sharpness and highlights "
                        "stay the plate's. Each input is linear light, or sRGB as 'plate_space' and 'shot_space' say.",
            inputs=[
                io.Image.Input("plate", tooltip="The plate in linear light, any size."),
                io.Image.Input("source", tooltip="The plate as the model saw it, in linear light. The light is "
                               "measured at this size: half the plate's size is plenty, light is smooth."),
                io.Image.Input("relit", tooltip="The regenerated shot, same size as 'source', in linear light."),
                io.Int.Input("radius", default=1, min=1, max=256,
                             tooltip="The change of light is smoothed over this many pixels of 'source', its colour over "
                                     "four times as many; finer detail stays the plate's. 1 at half the plate's size lets "
                                     "the shot's light through almost pixel for pixel."),
                io.Float.Input("strength", default=1.0, min=0.0, max=2.0, step=0.05),
                io.Boolean.Input("align", default=True, tooltip="Realign 'relit' first, by one shift for the whole shot: the median of every frame's."),
                io.Combo.Input("plate_space", options=["linear", "sRGB"], default="linear", optional=True,
                               tooltip="How 'plate' and the result are encoded. sRGB is decoded to linear light here, frame "
                                       "by frame in parallel, and the result encoded back: far cheaper than core colour "
                                       "conversions at full size."),
                io.Combo.Input("shot_space", options=["linear", "sRGB"], default="linear", optional=True,
                               tooltip="How 'source' and 'relit' are encoded: sRGB, as the model saw and made them, is "
                                       "decoded here."),
                io.Image.Input("light", optional=True,
                               tooltip="A light edit's painted light, in display values on black. Where it is strong, the "
                                       "result keeps at least the plate with that light added, as the brush showed it."),
                io.Image.Input("shade", optional=True,
                               tooltip="A light edit's shade strokes, white where the shadow is full: the result is darkened "
                                       "there, in linear light, by 'shade_density'. Klein ignores a painted shadow."),
                io.Float.Input("shade_density", default=0.7, min=0.0, max=1.0, step=0.05, optional=True,
                               tooltip="How much light the painted shade takes away where it is full."),
                io.Float.Input("peak", optional=True, force_input=True,
                               tooltip="The plate's peak, as Color Space (OCIO) gives it. With 'shot_space' sRGB, the tone "
                                       "mapping of that peak, which brought 'source' and 'relit' into the model space, is "
                                       "undone after the decode: their light is measured at the plate's levels."),
            ],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, plate, source, relit, radius, strength, align, plate_space="linear", shot_space="linear",
                light=None, shade=None, shade_density=0.7, peak=None) -> io.NodeOutput:
        n = min(plate.shape[0], source.shape[0], relit.shape[0])
        src, rel = list(frames_np(source[:n])), list(frames_np(relit[:n]))
        shift = (0.0, 0.0)
        if align:  # one shift for the whole shot: a shift measured frame by frame moves with the light
            width = int(plate.shape[2])
            with ThreadPoolExecutor(WORKERS) as pool:
                shift = mathops.shot_shift(list(pool.map(lambda sr: mathops.frame_shift(*sr, width, shot_space), zip(src, rel))))
            if shift != (0.0, 0.0):
                logging.info("[Paint a plate] Relight Transfer: shot realigned by x %+.2f px, y %+.2f px, over %d frames.", shift[1], shift[0], n)
        painted = list(frames_np(light[:1]))[0] if light is not None else None
        shaded = list(frames_np(shade[:1]))[0] if shade is not None else None
        peak = peak if peak is not None and shot_space == "sRGB" else 1.0
        untone = peak > ocio.TONE_ABOVE  # a plate above 1.0: 'source' and 'relit' go back to its levels, frame by frame
        if untone:
            logging.info("[Paint a plate] Relight Transfer: model space's tone mapping undone, peak %.2f.", peak)
        bar, stop = comfy.utils.ProgressBar(n), Stop()

        def one(args):
            stop()
            i, p = args
            s, r, space = src[i], rel[i], shot_space
            if untone:  # the shift above was measured on the frames as the model saw them, as for any plate
                s, r, space = ocio.out_of_model(s[..., :3], peak), ocio.out_of_model(r[..., :3], peak), "linear"
            out = mathops.relight_frame(p, s, r, radius, strength, shift, plate_space, space, painted)
            if shaded is not None:
                out = mathops.shade_frame(out, shaded, shade_density, plate_space)
            bar.update(1)
            return out

        with ThreadPoolExecutor(WORKERS) as pool:
            out = list(pool.map(one, enumerate(frames_np(plate[:n]))))
        return io.NodeOutput(to_image(out))



class FollowMatte(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_FollowMatte",
            display_name="Follow Matte",
            category=CATEGORY,
            description="One matte per frame from SAM 3.1's track, safe for the composite. It follows the object's own region "
                        "from the first-frame mask: objects SAM finds by itself elsewhere are left out; where the object is not "
                        "seen, the last matte holds (with no mask, the first-frame mask); with the plate the shot was made over, "
                        "the matte also takes the generated pixels connected to the object, so a generated element is never "
                        "dropped. A frame that differs from the plate everywhere adds nothing. An object that stands still in "
                        "the scene and passes behind something the plate holds leaves the matte while it is hidden, and comes "
                        "back into it where it comes out: what stands in front is left out. The summary ends with the "
                        "largest matte against the object's area, and its frame.",
            inputs=[
                io.Mask.Input("masks", tooltip="SAM 3.1's masks, one per frame it tracked. It may return fewer, or none."),
                io.Mask.Input("first", tooltip="The area on the first frame that SAM was asked to follow."),
                io.Image.Input("frames", tooltip="The frames SAM tracked: their count sets the matte's length. For paint, the shot. For an erase, the plate: Follow Matte asks it what passes in front of the object."),
                io.Image.Input("base", optional=True, tooltip="The plate the shot was made over, at the same size."),
                io.Mask.Input("element", optional=True,
                              tooltip="Where the edit changed the first frame: the object's region starts here instead of at first."),
                io.Float.Input("zone", default=0.0625, min=0.0, max=0.5, step=0.005,
                               tooltip="How far from the object's region SAM's mask may move and a change still joins, as a fraction of the width."),
                io.Float.Input("threshold", default=0.1, min=0.01, max=1.0, step=0.01,
                               tooltip="How much more a pixel must change than its frame changes around the object, from 0 to 1, to join the matte."),
            ],
            outputs=[io.Mask.Output(display_name="mask"), io.String.Output(display_name="summary")],
        )

    @classmethod
    def execute(cls, masks, first, frames, zone, threshold, base=None, element=None) -> io.NodeOutput:
        shot = frames[..., :3].float().cpu().numpy()
        plate = base[..., :3].float().cpu().numpy() if base is not None else None
        out, summary = mathops.follow_matte(masks.float().cpu().numpy(), len(shot), first.float().cpu().numpy(),
                                            shot if plate is not None else None, plate if plate is not None else shot,  # an erase: the tracked frames are the plate
                                            zone=zone, threshold=threshold, tick=Stop(),
                                            element=element.float().cpu().numpy() if element is not None else None)
        return io.NodeOutput(torch.from_numpy(out).to(device=mm.intermediate_device(), dtype=mm.intermediate_dtype()), summary)


class KeyframeVideo(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_KeyframeVideo",
            display_name="Keyframe Video",
            category=CATEGORY,
            description="Builds the control video of an IC-LoRA that reads painted keyframes, such as AInVFX's ainvfx-fluid: "
                        "black frames, with each keyframe image at its frame.",
            search_aliases=["keyframes", "control video", "ainvfx-fluid"],
            inputs=[
                io.Int.Input("width", default=960, min=64, max=8192),
                io.Int.Input("height", default=512, min=64, max=8192),
                io.Int.Input("frames", default=121, min=1, max=4096),
                io.String.Input("keys", default="[]", multiline=True,
                                tooltip='A JSON list of {"frame": n, "image": "folder/key.png"}, images in ComfyUI\'s input folder.'),
            ],
            outputs=[io.Image.Output(display_name="images")],
        )

    @classmethod
    def fingerprint_inputs(cls, width, height, frames, keys):
        stamps = []
        for key in json.loads(keys or "[]"):  # a keyframe image replaced under the same name runs again
            try:
                stamps.append(os.path.getmtime(resolve(key["image"])))
            except (OSError, ValueError, KeyError, TypeError):
                stamps.append(None)
        return f"{width}|{height}|{frames}|{keys}|{stamps}"

    @classmethod
    def execute(cls, width, height, frames, keys) -> io.NodeOutput:
        def read(name):
            with Image.open(resolve(name)) as im:
                im = im.convert("RGB")
                if im.size != (width, height):
                    im = im.resize((width, height), Image.NEAREST)  # flat colours stay flat
                return np.asarray(im, np.float32) / 255.0
        video = mathops.keyframe_video(json.loads(keys or "[]"), width, height, frames, read)
        return io.NodeOutput(torch.from_numpy(video).to(device=mm.intermediate_device(), dtype=mm.intermediate_dtype()))


LIVE = ThreadPoolExecutor(1)  # live previews are encoded off the sampling thread, one at a time
_TINY = {}  # tiny decoders by path, loaded once


class LivePreview(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_LivePreview",
            display_name="Live Preview",
            category=CATEGORY,
            description="Shows a shot while the video model samples it: from the first step, every few steps, a tiny decoder turns the predicted "
                        "frames into a small looping animation for the page. The model itself is unchanged. When it cannot make "
                        "a preview, it tells the page why, once, and the shot still renders.",
            inputs=[
                io.Model.Input("model"),
                io.String.Input("decoder", default="taeltx2_3.safetensors",
                                tooltip="A tiny video decoder in models/vae_approx. Without it there is no preview, and the shot "
                                        "still renders."),
                io.Int.Input("frames", default=121, min=1, max=4096,
                             tooltip="Frames of the shot. Latent frames after them are guide frames, never shown."),
                io.Float.Input("fps", default=24.0, min=1.0, max=120.0),
                io.Int.Input("every", default=0, min=0, max=100, tooltip="Steps between two previews. 0 turns the preview off."),
                io.Int.Input("size", default=320, min=64, max=1280, tooltip="Long side of the preview, in pixels."),
                io.Combo.Input("transfer", options=["sRGB", "ACEScct"], default="sRGB", optional=True,
                               tooltip="What the decoded values are: sRGB, or ACEScct codes (the SDR-to-HDR pass), shown tone-mapped."),
            ],
            outputs=[io.Model.Output(display_name="model")],
        )

    @classmethod
    def execute(cls, model, decoder, frames, fps, every, size, transfer="sRGB") -> io.NodeOutput:
        if every <= 0:
            return io.NodeOutput(model)
        server, context = PromptServer.instance, get_executing_context()
        running = context.prompt_id if context else server.last_prompt_id

        def off(reason, prompt_id=running):  # never silent: the page's log says once why this pass shows no preview
            logging.warning("[Paint a plate] Warning: Live Preview off for this shot: %s.", str(reason).rstrip("."))
            server.send_sync("paintaplate.live", {"prompt_id": prompt_id, "off": str(reason)}, server.client_id)

        path = folder_paths.get_full_path("vae_approx", decoder)
        if not path:
            off(f"decoder {decoder} not in models/vae_approx")
            return io.NodeOutput(model)
        try:
            if path not in _TINY:
                _TINY[path] = comfy.sd.VAE(sd=comfy.utils.load_torch_file(path))
        except Exception as exc:  # a preview never stops a shot
            off(f"decoder {decoder} did not load ({exc})")
            return io.NodeOutput(model)
        tiny = _TINY[path]
        latent_frames, state = (frames - 1) // 8 + 1, {"calls": 0, "busy": False}

        def where(args):  # this step and the pass's steps, from the sigmas CFGGuider puts in every model call's options
            try:
                sigmas = args["model_options"].get("transformer_options", {}).get("sample_sigmas")
                if sigmas is not None and len(sigmas) >= 2:
                    gap = (sigmas.float().cpu() - float(torch.as_tensor(args["sigma"]).flatten()[0])).abs()
                    return int(gap.argmin()) + 1, len(sigmas) - 1
            except Exception:  # a preview never stops a shot: below, the calls are counted instead
                pass
            state["calls"] += 1  # a sampler without them: the calls counted, the total unknown
            return state["calls"], 0

        def send(video, step, steps, prompt_id, client):  # a looping WebP in the temp folder, and a message telling the page where it is
            try:
                if transfer == "ACEScct":
                    video = mathops.acescct_preview(video)
                h, w = video.shape[1:3]
                k = size / max(h, w)
                images = [Image.fromarray(f).resize((max(2, round(w * k)), max(2, round(h * k))), Image.BILINEAR) for f in video]
                folder = os.path.join(folder_paths.get_temp_directory(), "paintaplate_live")
                os.makedirs(folder, exist_ok=True)
                name = f"{prompt_id}_{step:03d}.webp"
                images[0].save(os.path.join(folder, name), save_all=True, append_images=images[1:], duration=round(1000 / fps),
                               loop=0, quality=55, method=0)
                server.send_sync("paintaplate.live", {"prompt_id": prompt_id, "step": step, "steps": steps,
                                                      "image": {"filename": name, "subfolder": "paintaplate_live", "type": "temp"}}, client)
            except Exception as exc:  # a preview never stops a shot: it switches itself off, and says why
                state["off"] = True
                off(exc, prompt_id)
            finally:
                state["busy"] = False

        def post_cfg(args):  # called once per step with the frames the model predicts: decode them now, encode them aside
            denoised = args["denoised"]
            step, steps = where(args)
            if (step - 1) % every == 0 and not state["busy"] and not state.get("off"):  # the first at step 1, as early as it can
                try:
                    video = denoised.tensors[0] if getattr(denoised, "is_nested", False) else denoised
                    shapes = getattr(args["model"], "latent_shapes", None)  # LTX 2.5 samples video and audio packed in one latent
                    if shapes and video.ndim == 3:
                        video = comfy.utils.unpack_latents(video, shapes)[0]
                    video = video[:1, :, :latent_frames]
                    k = max(1, max(video.shape[-2:]) * 32 // (2 * size))  # LTX's 32 px grid: decode at about twice the preview's size
                    if k > 1:  # a full-size pass: the latent averaged first, so the tiny decoder costs what a preview pass costs
                        video = F.avg_pool3d(video.float(), (1, k, k), ceil_mode=True).to(video.dtype)
                    images = tiny.decode(video)
                    images = images.reshape(-1, *images.shape[-3:]).clamp(0, 1)
                    state["busy"] = True
                    context = get_executing_context()  # the prompt running now: ComfyUI may reuse this node's output in a later one
                    LIVE.submit(send, images.half().cpu().numpy() if transfer == "ACEScct" else (images * 255).to(torch.uint8).cpu().numpy(),
                                step, steps, context.prompt_id if context else server.last_prompt_id, server.client_id)
                except Exception as exc:  # a preview never stops a shot: it switches itself off
                    state["off"] = True
                    off(exc)
            return denoised

        patched = model.clone()
        patched.set_model_sampler_post_cfg_function(post_cfg)
        return io.NodeOutput(patched)


class LevelFill(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_LevelFill",
            display_name="Level Fill",
            category=CATEGORY,
            description="Levels an erase's fill with the background it continues. Where the fill is flat and a few levels "
                        "off the background around it, the difference goes, low frequencies only; edges, revealed objects "
                        "and textured fills stay as they are. Klein's pale imprint of a removed object, left in, becomes "
                        "smoke in the erase pass.",
            inputs=[
                io.Image.Input("image", tooltip="The edited frame: Klein's fill inside the mask."),
                io.Mask.Input("alpha", tooltip="Where the fill covers the frame: the edit's soft mask."),
                io.Image.Input("base", tooltip="The frame under the edit."),
                io.Mask.Input("paint", tooltip="Where the removed object was: the erase mask."),
                io.Boolean.Input("enabled", default=True, tooltip="Off passes the image through, as paint and light edits need."),
            ],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, image, alpha, base, paint, enabled) -> io.NodeOutput:
        if not enabled:
            return io.NodeOutput(image)
        h, w = image.shape[1:3]
        as_batch = lambda m: m if m.ndim == 3 else m[None]  # noqa: E731
        a = resize(as_batch(alpha), h, w).float().cpu().numpy()
        p = resize(as_batch(paint), h, w).float().cpu().numpy()
        out = []
        for i, (fill, under) in enumerate(zip(frames_np(image), frames_np(resize(base[..., :3], h, w)))):
            levelled, moved = mathops.level_fill(fill, a[min(i, len(a) - 1)], under, p[min(i, len(p) - 1)])
            logging.info("[Paint a plate] Level Fill: fill moved by %.1f levels on average.", moved)
            out.append(levelled)
        return io.NodeOutput(to_image(out))


class SaveFrames(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_SaveFrames",
            display_name="Save Frames",
            category=CATEGORY,
            description="Saves a batch as numbered frames, named as core Save Image names them, several frames at once: "
                        "8-bit PNG, as core saves them, or half-float EXR with lossless PIZ compression, values above 1.0 "
                        "kept. Core writes one frame after another: 35 s for 121 PNG frames at 1920 x 1088, where this node "
                        "takes about a second on a pod with 16 cores.",
            inputs=[
                io.Image.Input("images"),
                io.String.Input("filename_prefix", default="paintaplate/frames/f",
                                tooltip="As in Save Image: a folder under the output folder, then the file name."),
                io.Combo.Input("format", options=["png", "png16", "exr"], default="png", optional=True,
                               tooltip="png: 8 bits, as core Save Image. png16: 16 bits, for a plate deeper than 8 bits. "
                                       "exr: half float, every value as it is."),
                io.Float.Input("fps", default=0.0, min=0.0, max=240.0, optional=True,
                               tooltip="exr only: the shot's frame rate, written in each frame's header (framesPerSecond), "
                                       "so the frames keep their rate when they open as a plate. 0 writes none."),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, images, filename_prefix, format="png", fps=0.0) -> io.NodeOutput:
        n, h, w = images.shape[0], images.shape[1], images.shape[2]
        folder, name, counter, sub, _ = folder_paths.get_save_image_path(filename_prefix, folder_paths.get_output_directory(), w, h)
        names = [f"{name}_{counter + i:05}_.{'png' if format == 'png16' else format}" for i in range(n)]
        paths, bar = [os.path.join(folder, f) for f in names], comfy.utils.ProgressBar(n)
        if format == "exr":
            plateio.write_exrs(stoppable(lambda i: images[i].float().cpu().numpy()), paths, workers=WORKERS, tick=lambda: bar.update(1), fps=fps)
            return io.NodeOutput(ui={"images": [{"filename": f, "subfolder": sub, "type": "output"} for f in names]})

        def frame(i):  # as core Save Image: scaled by 255 and clipped, not rounded, so every pixel matches what it wrote
            if format == "png16":  # new content at a deep plate's depth: 65536 levels, rounded
                return np.round(np.clip(images[i].float().cpu().numpy(), 0, 1) * 65535.0).astype(np.uint16)
            return plateio.core_uint8(images[i].float().cpu().numpy())
        plateio.write_pngs(stoppable(frame), paths, workers=WORKERS, tick=lambda: bar.update(1))
        return io.NodeOutput(ui={"images": [{"filename": f, "subfolder": sub, "type": "output"} for f in names]})


class SaveMovie(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_SaveMovie",
            display_name="Save Movie",
            category=CATEGORY,
            description="Saves a batch as an H.264 movie for the page, as core Save Video makes it (crf 18, BT.709, "
                        "limited range), with the frames converted several at once and x264 at preset veryfast: core "
                        "took 8.3 s for 121 frames at 1920 x 1088. With 'destination' or 'largest_size', each frame is "
                        "converted and sized as it is saved: no second batch of the frames is held in memory.",
            inputs=[
                io.Image.Input("images"),
                io.Float.Input("fps", default=24.0, min=1.0, max=240.0),
                io.String.Input("filename_prefix", default="paintaplate/movie",
                                tooltip="As in Save Video: a folder under the output folder, then the file name."),
                io.Int.Input("crf", default=18, min=0, max=51, optional=True,
                             tooltip="x264's quality: 18 as core Save Video, lower is closer to the frames. The playback "
                                     "proxy and the review use 12."),
                io.Int.Input("width", default=0, min=0, max=8192, optional=True,
                             tooltip="The movie's width: 0 keeps the frames' size. Scaled with Lanczos while it converts."),
                io.Int.Input("height", default=0, min=0, max=8192, optional=True, tooltip="The movie's height: 0 keeps the frames' size."),
                io.Int.Input("frames", default=0, min=0, max=4096, optional=True,
                             tooltip="The frames to save, from the first: 0 saves them all. Load Plate's 'frames' leaves its "
                                     "8k+1 padding out."),
                io.String.Input("config", default=ocio.BUILTIN, optional=True,
                                tooltip="The OpenColorIO config of 'source' and 'destination', as in Color Space (OCIO)."),
                io.String.Input("source", default="@model", optional=True, tooltip="The frames' colour space."),
                io.String.Input("destination", default="@model", optional=True,
                                tooltip="The movie's colour space. Each frame is converted as it is saved, to the values "
                                        "Color Space (OCIO) gives the whole batch."),
                io.Int.Input("largest_size", default=0, min=0, max=8192, optional=True,
                             tooltip="The frames' longer side before the movie is made, by area averaging as core's Scale "
                                     "Image to Max Dimension: 0 keeps their size. Each frame is sized as it is saved."),
            ],
            is_output_node=True,
        )

    @classmethod
    def execute(cls, images, fps, filename_prefix, crf=18, width=0, height=0, frames=0, config=ocio.BUILTIN, source="@model",
                destination="@model", largest_size=0) -> io.NodeOutput:
        n = min(frames, images.shape[0]) if frames else images.shape[0]
        w, h = plateio.largest_side(images.shape[2], images.shape[1], largest_size)
        converts = source != destination
        peak = ocio.batch_peak(frames_np(images[:n]), config, source) if converts and destination == ocio.MODEL else None
        folder, name, counter, sub, _ = folder_paths.get_save_image_path(filename_prefix, folder_paths.get_output_directory(), w, h)
        file = f"{name}_{counter:05}_.mp4"
        bar = comfy.utils.ProgressBar(n)

        def frame(i):  # one frame at a time, so no second batch is made: converted, sized with area, then as core Save Video
            x = images[i:i + 1]
            if converts:
                x = to_image(ocio.convert([x[0].float().cpu().numpy()], config, source, destination, peak))
            if x.shape[1:3] != (h, w):
                x = comfy.utils.common_upscale(x.movedim(-1, 1), w, h, "area", "disabled").movedim(1, -1)
            return plateio.core_uint8(x[0].float().cpu().numpy())  # scaled by 255 and clipped, not rounded

        plateio.write_movie(stoppable(frame), n, os.path.join(folder, file), fps, workers=WORKERS, crf=crf, tick=lambda: bar.update(1),
                            size=(width, height))
        return io.NodeOutput(ui={"images": [{"filename": file, "subfolder": sub, "type": "output"}], "animated": [True]})


class HDRMatch(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_HDRMatch",
            display_name="HDR Match",
            category=CATEGORY,
            description="Sets an HDR shot's level to the plate it is composited onto. SDR to HDR picks its own exposure and "
                        "white balance, while the plate's untouched pixels hold the scene's real values: one gain per "
                        "channel, measured on the untouched mid-tones over the whole shot (no flicker), scales every pixel. "
                        "A gain keeps every ratio, so the range SDR to HDR made above the plate's white stays for grading. "
                        "Without an HDR shot the image passes through; without a matte the HDR shot does.",
            inputs=[
                io.Image.Input("image", tooltip="The shot in the plate's colour space as the SDR pass made it: the output without an HDR shot."),
                io.Image.Input("plate", tooltip="The plate's own values, in its colour space."),
                io.Float.Input("grow", default=24.0, min=0.0, max=512.0,
                               tooltip="Plate pixels the matte grows by before what is left counts as untouched: the composite's grow and feather."),
                io.Mask.Input("mask", optional=True, tooltip="Where the edits changed the shot: the composite's matte."),
                io.Image.Input("hdr", optional=True, tooltip="The HDR shot, in the plate's colour space."),
            ],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, image, plate, grow, mask=None, hdr=None) -> io.NodeOutput:
        if hdr is None:
            return io.NodeOutput(image)
        if mask is None:
            logging.info("[Paint a plate] HDR Match: HDR shot kept as made.\n  No matte: no untouched pixels to measure.")
            return io.NodeOutput(hdr)
        m = (mask if mask.ndim == 3 else mask[None]).float().cpu().numpy()
        n, k = hdr.shape[0], plate.shape[0]
        frames, report = mathops.hdr_match(n, stoppable(lambda i: hdr[i].float().cpu().numpy()), lambda i: plate[min(i, k - 1)].float().cpu().numpy(),
                                           lambda i: m[min(i, len(m) - 1)], grow=grow, workers=WORKERS)
        logging.info("[Paint a plate] HDR Match: %s", report["text"])
        return io.NodeOutput(to_image(frames))


class VAEFloat32(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_VAEFloat32",
            display_name="Load VAE (float32)",
            category=CATEGORY,
            description="Loads a VAE in float32 from the start, as SDR to HDR's float32 encode and decode need. Core's VAE "
                        "Loader builds it in bf16, and LTXVVAEForceFloat32 then casts it in place: under ComfyUI's dynamic "
                        "VRAM, its default without --highvram, the buffers stay sized for bf16 and the HDR pass failed on a "
                        "32 GB card with « Buffer too small » (2 Nov 2026).",
            inputs=[io.Combo.Input("vae_name", options=folder_paths.get_filename_list("vae"))],
            outputs=[io.Vae.Output(display_name="VAE")],
        )

    @classmethod
    def execute(cls, vae_name) -> io.NodeOutput:  # as core's VAE Loader for a VAE file, with its dtype set at load
        sd, metadata = comfy.utils.load_torch_file(folder_paths.get_full_path_or_raise("vae", vae_name), return_metadata=True)
        vae = comfy.sd.VAE(sd=sd, metadata=metadata, dtype=torch.float32)
        vae.throw_exception_if_invalid()
        return io.NodeOutput(vae)


class KeepBlack(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="PaintAPlate_KeepBlack",
            display_name="Keep Black",
            category=CATEGORY,
            description="Where the SDR shot is black, its own black instead of SDR to HDR's noise (mathops.keep_black): below "
                        "`low` of luminance the SDR values, above `high` the HDR ones, a smooth step between, and no value "
                        "below 0. In ACEScg: each frame of the SDR shot is converted from 'source' as it is used, so no "
                        "converted copy of the shot is held.",
            inputs=[io.Image.Input("hdr", tooltip="SDR to HDR's frames, ACEScg scene-linear."),
                    io.Image.Input("sdr", tooltip="The SDR shot they were made from, in 'source'."),
                    io.String.Input("config", default=ocio.BUILTIN,
                                    tooltip="$OCIO for the config the OCIO environment variable names, or a built-in config "
                                            "such as ocio://studio-config-latest."),
                    io.String.Input("source", default="@model",
                                    tooltip="The SDR shot's colour space: a colour space of the config, or @model."),
                    io.Float.Input("low", default=0.001, min=0.0, max=1.0, step=0.0001),
                    io.Float.Input("high", default=0.01, min=0.0, max=1.0, step=0.0001)],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, hdr, sdr, config, source, low, high) -> io.NodeOutput:
        n = min(hdr.shape[0], sdr.shape[0])
        out = np.empty((n, *hdr.shape[1:]), np.float32)

        def frame(i):
            black = ocio.convert([sdr[i].float().cpu().numpy()], config, source, "ACEScg")[0]
            out[i] = mathops.keep_black(hdr[i].float().cpu().numpy(), black, low, high)

        with ThreadPoolExecutor(WORKERS) as pool:
            list(pool.map(stoppable(frame), range(n)))
        return io.NodeOutput(to_image(out))


NODES = [LoadPlate, SavePlate, ColorSpace, SaveFrames, SaveMovie, FitToPlate, CompositeFrames, RelightTransfer, FollowMatte, LevelFill, LivePreview,
         KeyframeVideo, HDRMatch, VAEFloat32, KeepBlack]
