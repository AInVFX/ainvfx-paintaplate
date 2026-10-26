"""Write the PaintAPlate workflows to web/workflows/*.json.

Each file is a plain ComfyUI workflow in API format, so ComfyUI opens it with Open or by drag
and drop. The page fills some inputs before it posts a workflow: each node lists them in
`_meta.slots` as {input name: slot name}, the outputs the page reads carry `_meta.output`, and
the node whose progress stands for the whole workflow carries `_meta.progress`.
Every node is a core node, a ComfyUI-LTXVideo node or one of the five PaintAPlate nodes.

    python tools/build_workflows.py
"""
import json
import os

OUT = os.environ.get("PAINTAPLATE_WORKFLOWS_OUT") or os.path.join(os.path.dirname(__file__), "..", "web", "workflows")
NAMES = ("ingest", "edit", "snap", "shot", "matte", "comp", "export")

KLEIN = "flux3-image-klein-int8-convrot.safetensors"
LTX = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
GEMMA = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
RIPPLE_PROMPT = ("Use the reference video for motion, timing, camera movement, framing and lighting changes; "
                 "follow the edited first frame for every change of content, light and style.")
NEGATIVE = "blurry, low resolution, ugly, garbled mess, compression artifacts, glitch, flicker, still image"


class Slot:
    def __init__(self, name, default):
        self.name, self.default = name, default


class Ref:
    def __init__(self, nid):
        self.nid = nid

    def __getitem__(self, i):
        return [self.nid, i]


class Graph:
    def __init__(self):
        self.prompt = {}

    def __call__(self, cls, _title=None, _output=None, _progress=False, **inputs):
        nid = str(len(self.prompt) + 1)
        node = {"class_type": cls, "inputs": {}}
        meta, slots = {}, {}
        for key, value in inputs.items():
            key = key.replace("__", ".")  # images__image0 -> images.image0 (dynamic inputs)
            if isinstance(value, Slot):
                slots[key] = value.name
                value = value.default
            node["inputs"][key] = [value.nid, 0] if isinstance(value, Ref) else value
        if _title:
            meta["title"] = _title
        if slots:
            meta["slots"] = slots
        if _output:
            meta["output"] = _output
        if _progress:
            meta["progress"] = True
        if meta:
            node["_meta"] = meta
        self.prompt[nid] = node
        return Ref(nid)

    def link_slot(self, ref, key, name):
        """A link the page may remove, named like a slot (the page drops the mask link when there is no matte)."""
        self.prompt[ref.nid].setdefault("_meta", {}).setdefault("slots", {})[key] = name

    def save(self, name, out=None):
        out = out or OUT
        os.makedirs(out, exist_ok=True)
        with open(os.path.join(out, f"{name}.json"), "w") as f:
            json.dump(self.prompt, f, indent=1)


def slots_of(prompt):
    """{slot name: [[node id, input], ...]} from the `_meta.slots` of every node."""
    slots = {}
    for nid, node in prompt.items():
        for key, name in node.get("_meta", {}).get("slots", {}).items():
            slots.setdefault(name, []).append([nid, key])
    return slots


def progress_of(prompt):
    """The ids of the nodes marked `_meta.progress`: the page shows their progress only."""
    return [nid for nid, node in prompt.items() if node.get("_meta", {}).get("progress")]


def outputs_of(prompt):
    """{output name: node id} from `_meta.output`."""
    return {node["_meta"]["output"]: nid for nid, node in prompt.items() if node.get("_meta", {}).get("output")}


def load(name, folder=None):
    """(prompt, slots, outputs) of one saved workflow."""
    with open(os.path.join(folder or OUT, f"{name}.json")) as f:
        prompt = json.load(f)
    return prompt, slots_of(prompt), outputs_of(prompt)


# Optional links: when every source slot is left empty, the link goes, with every node that fed it
# (no erase: nothing to fill before LTX; a relight alone: no matte to composite with or to save).
OPTIONAL = {"hole_mask": ("hole",), "fit_mask": ("matte_a", "matte_b")}


def drop_link(prompt, slots, link, sources, extra=()):
    """Remove the input `link` names, the nodes its `sources` slots sit on, and every node fed only by them."""
    for nid, key in slots.get(link, []):
        prompt[nid]["inputs"].pop(key, None)
    gone = {nid for source in sources for nid, _ in slots.get(source, [])} | set(extra)
    grew = True
    while grew:
        grew = False
        for nid, node in prompt.items():
            if nid not in gone and any(isinstance(v, list) and str(v[0]) in gone for v in node["inputs"].values()):
                gone.add(nid)
                grew = True
    for nid in gone:
        prompt.pop(nid, None)


def fill(name, values, folder=None):
    """The prompt of a saved workflow with its slots set and its unused optional links dropped, as the page posts it."""
    prompt, slots, outputs = load(name, folder)
    for slot, value in values.items():
        for nid, key in slots.get(slot, []):
            prompt[nid]["inputs"][key] = value
    for link, sources in OPTIONAL.items():
        if link in slots and not any(values.get(source) for source in sources):
            drop_link(prompt, slots, link, sources, [outputs["matte"]] if link == "fit_mask" and "matte" in outputs else [])
    return prompt


def plate(g, pad, path="path", progress=False):
    """The plate as display-referred sRGB frames: Load Plate, then core colour conversion.

    Every workflow converts the same whole plate: core tone-maps SDR output with one peak per
    batch, so a different batch could change the exposure of an HDR plate between steps.
    """
    load = g("PaintAPlate_LoadPlate", _title="Plate", _progress=progress, path=Slot(path, ""),
             max_frames=Slot("max_frames", 121), pad_8n1=pad)
    srgb = g("ImageColorSpace", _title="Plate in sRGB", image=load[0], source=Slot("color_space", "sRGB"),
             destination="sRGB")
    return load, srgb


def ingest():
    """The first frame at working size, a playback proxy of the real frames, and the plate spec."""
    g = Graph()
    load, srgb = plate(g, pad=True, progress=True)  # same inputs as every other Load Plate: decoded once, then cached
    first = g("ImageFromBatch", image=srgb, batch_index=0, length=1)
    hero = g("ImageScaleToMaxDimension", image=first, upscale_method="lanczos", largest_size=1920)
    g("SaveImage", _title="First frame", _output="hero", images=hero,
      filename_prefix=Slot("prefix", "paintaplate/plate/hero"))
    real = g("ImageFromBatch", _title="Real frames (no padding)", image=srgb, batch_index=0, length=load[4])
    proxy = g("ImageScaleToMaxDimension", image=real, upscale_method="area", largest_size=Slot("proxy_size", 960))
    video = g("CreateVideo", images=proxy, fps=load[3], bit_depth=8, color_space="sRGB", codec="none")
    g("SaveVideo", _title="Playback proxy", _output="proxy", video=video,
      filename_prefix=Slot("video_prefix", "paintaplate/plate/proxy"), format="auto", format__codec="auto")
    g("PreviewAny", _title="Plate spec", _output="spec", source=load[5])
    g.save("ingest")


def edit():
    """One FLUX 3 Image Klein edit inside a mask: the edited frame, and the edit alone as an RGBA patch."""
    g = Graph()
    model = g("UNETLoader", unet_name=Slot("klein", KLEIN), weight_dtype="default")
    clip = g("CLIPLoader", clip_name="qwen3vl_4b_int8_convrot.safetensors", type="flux3", device="default")
    vae = g("VAELoader", vae_name=Slot("vae", "flux2-vae.safetensors"))
    base = g("LoadImage", _title="Frame before the edit", image=Slot("base", ""))
    reference = g("LoadImage", _title="Reference: the strokes", image=Slot("reference", ""))
    start = g("LoadImage", _title="Start image", image=Slot("start", ""))
    mask = g("LoadImageMask", _title="Edit mask", image=Slot("mask", ""), channel="red")
    positive = g("CLIPTextEncode", _title="Caption", text=Slot("caption", ""), clip=clip)
    negative = g("ConditioningZeroOut", conditioning=positive)
    ref = g("ReferenceMultiLatent", positive=positive, negative=negative, vae=vae,
            resolution="keep resolution", images__image0=reference)
    grown = g("GrowMask", mask=mask, expand=Slot("grow", 16), tapered_corners=True)
    latent = g("SetLatentNoiseMask", samples=g("VAEEncode", pixels=start, vae=vae), mask=grown)
    sampled = g("KSampler", _progress=True, model=model, seed=Slot("seed", 0), steps=Slot("steps", 8), cfg=1.0,
                sampler_name="euler", scheduler="simple", positive=ref[0], negative=ref[1],
                latent_image=latent, denoise=Slot("denoise", 1.0))
    decoded = g("VAEDecode", samples=sampled, vae=vae)
    soft = g("ImageToMask", channel="red", image=g("ImageBlur", image=g("MaskToImage", mask=grown),
                                                    blur_radius=Slot("feather", 12), sigma=Slot("sigma", 6.0)))
    result = g("ImageCompositeMasked", destination=base, source=decoded, x=0, y=0, resize_source=False, mask=soft)
    g("PreviewImage", _title="Edited frame", _output="result", images=result)
    # Join Image with Alpha stores 1 - mask as alpha: the inverted soft mask gives alpha = soft mask
    patch = g("JoinImageWithAlpha", image=decoded, alpha=g("InvertMask", mask=soft))
    g("PreviewImage", _title="Edit patch (RGBA)", _output="patch", images=patch)
    g.save("edit")


def snap():
    """SAM 3.1 grows an erase stroke to the whole object under it, on the first frame."""
    g = Graph()
    sam = g("CheckpointLoaderSimple", ckpt_name=Slot("sam", "sam3.1_multiplex_fp16.safetensors"))
    found = g("SAM3_Detect", model=sam, image=g("LoadImage", _title="First frame", image=Slot("image", "")),
              positive_coords=Slot("points", "[]"), threshold=0.5, refine_iterations=2, individual_masks=False)
    g("PreviewImage", _title="Object mask", _output="mask", images=g("MaskToImage", mask=found))
    g.save("snap")


def shot():
    """LTX 2.5 with the Ripple IC-LoRA: the edited first frame carries through the whole shot."""
    g = Graph()
    load, srgb = plate(g, pad=True)
    scaled = g("ImageScale", image=srgb, upscale_method="lanczos", width=Slot("width", 960),
               height=Slot("height", 544), crop="disabled")
    # what an erase takes away, filled in the frames LTX follows: shown the object, LTX kept its shape
    hole = g("PaintAPlate_LoadPlate", _title="Erase matte", path=Slot("hole", ""), max_frames=1024, pad_8n1=False)
    frames = g("PaintAPlate_FillMatte", _title="Erased objects filled", images=scaled,
               mask=g("ImageToMask", image=hole, channel="red"), grow=Slot("hole_grow", 60), feather=Slot("hole_feather", 60))
    g.link_slot(frames, "mask", "hole_mask")  # the page drops this link when no edit erases
    size = g("GetImageSize", image=frames)
    hero = g("ImageScale", image=g("LoadImage", _title="Edited first frame", image=Slot("hero", "")),
             upscale_method="lanczos", width=size[0], height=size[1], crop="disabled")
    rest = g("ImageFromBatch", image=frames, batch_index=1, length=4096)
    reference = g("BatchImagesNode", _title="Reference: first frame replaced", images__image0=hero,
                  images__image1=rest)
    model = g("LoraLoaderModelOnly", _title="Ripple IC-LoRA",
              model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"),
              lora_name=Slot("ripple", "LTX25_Ripple_v11.safetensors"), strength_model=Slot("strength", 1.35))
    clip = g("CLIPLoader", clip_name=Slot("gemma", GEMMA), type="ltxv", device="default")
    vae = g("VAELoader", vae_name=Slot("video_vae", "ltx-2.5-video-vae-conv-bf16.safetensors"))
    audio_vae = g("VAELoader", vae_name="ltx-2.5-audio-vae-bf16.safetensors")
    cond = g("LTXVConditioning", positive=g("CLIPTextEncode", text=Slot("prompt", RIPPLE_PROMPT), clip=clip),
             negative=g("CLIPTextEncode", text=NEGATIVE, clip=clip), frame_rate=load[3])
    empty = g("EmptyLTXVLatentVideo", width=size[0], height=size[1], length=size[2], batch_size=1)
    guide = g("LTXAddVideoICLoRAGuide", positive=cond[0], negative=cond[1], vae=vae, latent=empty,
              image=reference, frame_idx=0, strength=1.0, latent_downscale_factor=1.0, crop="disabled",
              use_tiled_encode=False, tile_size=256, tile_overlap=64, use_streaming=False, tile_frames=97)
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=load[3], batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=Slot("seed", 0)),
                guider=g("CFGGuider", model=model, positive=guide[0], negative=guide[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler"),
                sigmas=g("BasicScheduler", model=model, scheduler="simple", steps=Slot("steps", 8), denoise=1.0),
                latent_image=g("LTXVConcatAVLatent", video_latent=guide[2], audio_latent=audio))
    video_latent = g("LTXVSeparateAVLatent", av_latent=sampled[0])
    cropped = g("LTXVCropGuides", positive=guide[0], negative=guide[1], latent=video_latent[0])
    decoded = g("VAEDecode", samples=cropped[2], vae=vae)
    g("SaveImage", _title="Shot frames", _output="frames", images=decoded,
      filename_prefix=Slot("prefix", "paintaplate/plate/shot/f"))
    video = g("CreateVideo", images=decoded, fps=load[3], bit_depth=8, color_space="sRGB", codec="none")
    g("SaveVideo", _title="Shot video (whole frame regenerated)", _output="video", video=video,
      filename_prefix=Slot("video_prefix", "paintaplate/plate/shot"), format="auto", format__codec="auto")
    g.save("shot")


def matte():
    """SAM 3.1 follows a painted area through the shot, from the first frame."""
    g = Graph()
    _, srgb = plate(g, pad=True)
    frames = g("ImageScale", image=srgb, upscale_method="area", width=Slot("width", 960),
               height=Slot("height", 544), crop="disabled")
    sam = g("CheckpointLoaderSimple", ckpt_name=Slot("sam", "sam3.1_multiplex_fp16.safetensors"))
    track = g("SAM3_VideoTrack", _progress=True, images=frames, model=sam,
              initial_mask=g("LoadImageMask", _title="Area on the first frame", image=Slot("mask", ""),
                             channel="red"),
              detection_threshold=0.5, max_objects=4, detect_interval=1)
    masks = g("SAM3_TrackToMask", track_data=track, object_indices="")
    g("SaveImage", _title="Matte frames", _output="frames", images=g("MaskToImage", mask=masks),
      filename_prefix=Slot("prefix", "paintaplate/plate/matte/m"))
    g.save("matte")


def mattes(g):
    """The erase and paint mattes as one mask. A missing matte is the other one again (the page sets both)."""
    erase = g("PaintAPlate_LoadPlate", _title="Erase matte", path=Slot("matte_a", ""), max_frames=1024, pad_8n1=False)
    add = g("PaintAPlate_LoadPlate", _title="Paint matte", path=Slot("matte_b", ""), max_frames=1024, pad_8n1=False)
    return g("MaskComposite", destination=g("ImageToMask", image=erase, channel="red"),
             source=g("ImageToMask", image=add, channel="red"), x=0, y=0, operation="add")


def fitted(g, base, gen, union):
    """Fit to Plate, then the composite: the edit over `base`, everything else untouched."""
    fit = g("PaintAPlate_FitToPlate", _progress=True, plate=base, image=gen, mask=union, align=True, max_shift=8.0,
            match_color=True, grain=Slot("grain", 1.0), grow=Slot("grow", 8), feather=Slot("feather", 12),
            steady=Slot("steady", 2))
    g.link_slot(fit, "mask", "fit_mask")  # the page drops this link when there is no matte
    final = g("ImageCompositeMasked", _title="Composite", destination=base, source=fit[0], x=0, y=0,
              resize_source=False, mask=fit[1])
    return fit, final


def comp():
    """The composite at preview size, as an MP4 to play in the page: what the export will look like."""
    g = Graph()
    load, srgb = plate(g, pad=True)
    small = g("ImageScale", image=srgb, upscale_method="area", width=Slot("width", 960), height=Slot("height", 544),
              crop="disabled")
    gen = g("PaintAPlate_LoadPlate", _title="Generated shot", path=Slot("shot", ""), max_frames=1024, pad_8n1=False)
    union = mattes(g)
    small_lin = g("ImageColorSpace", image=small, source="sRGB", destination="linear")
    relit = g("PaintAPlate_RelightTransfer", plate=small_lin, source=small_lin,
              relit=g("ImageColorSpace", image=gen, source="sRGB", destination="linear"),
              radius=Slot("radius", 8), strength=Slot("strength", 1.0), align=True)
    back = g("ImageColorSpace", image=relit, source="linear", destination="sRGB")
    base = g("ComfySwitchNode", switch=Slot("relight", False), on_false=small, on_true=back)
    _, final = fitted(g, base, gen, union)
    real = g("ImageFromBatch", image=final, batch_index=0, length=load[4])
    video = g("CreateVideo", images=real, fps=load[3], bit_depth=8, color_space="sRGB", codec="none")
    g("SaveVideo", _title="Composite preview", _output="video", video=video,
      filename_prefix=Slot("video_prefix", "paintaplate/plate/comp"), format="auto", format__codec="auto")
    g.save("comp")


def export():
    """Full quality: the shot fitted onto the plate, relight optional, saved in the plate's format, plus its matte."""
    g = Graph()
    load = g("PaintAPlate_LoadPlate", _title="Plate", path=Slot("path", ""), max_frames=Slot("max_frames", 121),
             pad_8n1=True)
    gen = g("PaintAPlate_LoadPlate", _title="Generated shot", path=Slot("shot", ""), max_frames=1024, pad_8n1=False)
    union = mattes(g)
    gen_plate = g("ImageColorSpace", image=gen, source="sRGB", destination=Slot("color_space", "sRGB"))
    # Relight: light from the regenerated shot, detail from the plate, all in linear light.
    size = g("GetImageSize", image=gen)
    source = g("ImageScale", image=g("ImageColorSpace", image=load, source=Slot("color_space", "sRGB"),
                                     destination="sRGB"),
               upscale_method="area", width=size[0], height=size[1], crop="disabled")
    relit = g("PaintAPlate_RelightTransfer",
              plate=g("ImageColorSpace", image=load, source=Slot("color_space", "sRGB"), destination="linear"),
              source=g("ImageColorSpace", image=source, source="sRGB", destination="linear"),
              relit=g("ImageColorSpace", image=gen, source="sRGB", destination="linear"),
              radius=Slot("radius", 16), strength=Slot("strength", 1.0), align=True)
    back = g("ImageColorSpace", image=relit, source="linear", destination=Slot("color_space", "sRGB"))
    base = g("ComfySwitchNode", switch=Slot("relight", False), on_false=load, on_true=back)
    # the new pixels are matched to the plate they are composited onto: relit when the light changed
    fit, final = fitted(g, base, gen_plate, union)
    g("PaintAPlate_SavePlate", _title="Export", _output="export", images=final, plate=load[2],
      filename_prefix=Slot("prefix", "paintaplate/plate/export"), keep_untouched=Slot("keep_untouched", True),
      changed=fit[1])
    matte_frames = g("ImageFromBatch", image=g("MaskToImage", mask=fit[1]), batch_index=0, length=load[4])
    g("SaveImage", _title="Matte: where the plate changed", _output="matte", images=matte_frames,
      filename_prefix=Slot("matte_prefix", "paintaplate/plate/matte/matte"))
    g.save("export")


if __name__ == "__main__":
    for build in (ingest, edit, snap, shot, matte, comp, export):
        build()
    print("wrote", sorted(os.listdir(OUT)))
