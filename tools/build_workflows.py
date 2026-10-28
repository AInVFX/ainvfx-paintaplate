"""Write the PaintAPlate workflows to web/workflows/*.json.

Each file is a plain ComfyUI workflow in API format, so ComfyUI opens it with Open or by drag
and drop. The page fills some inputs before it posts a workflow: each node lists them in
`_meta.slots` as {input name: slot name}, the outputs the page reads carry `_meta.output`, and
the node whose progress stands for the whole workflow carries `_meta.progress`.
Every node is a core node, a ComfyUI-LTXVideo node or one of the PaintAPlate nodes (nodes.py).

    python tools/build_workflows.py
"""
import json
import os

OUT = os.environ.get("PAINTAPLATE_WORKFLOWS_OUT") or os.path.join(os.path.dirname(__file__), "..", "web", "workflows")
NAMES = ("ingest", "prompt", "edit", "snap", "clean", "shot", "matte", "comp", "export", "warm", "fluid")

KLEIN = "flux3-image-klein-int8-convrot.safetensors"
LTX = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
GEMMA = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
UPSAMPLER = "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors"
INOUTPAINT = "ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors"
SAM = "sam3.1_multiplex_fp16.safetensors"
TINY = "taeltx2_3.safetensors"  # the tiny LTX 2.5 decoder of the live preview (models/vae_approx)
FLUID = "ainvfx-fluid.safetensors"  # AInVFX's IC-LoRA: painted keyframes become smoke, steam or fire (models/loras)
KLEIN_TEXT = "qwen3vl_4b_int8_convrot.safetensors"  # FLUX 3 Image Klein's text encoder (models/text_encoders)
KLEIN_VAE = "flux2-vae.safetensors"  # its VAE (models/vae)
LTX_VAE = "ltx-2.5-video-vae-conv-bf16.safetensors"  # LTX 2.5's video VAE (models/vae)
LTX_AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"  # its audio VAE (models/vae)
RIPPLE_LORA = "LTX25_Ripple_v11.safetensors"  # WepeNerd's Ripple IC-LoRA, which carries paint and light (models/loras)
FLUID_NEGATIVE = "blurry, low quality, distorted, watermark"  # the negative prompt of its model card's samples
SNAP_POINTS = 5  # stroke points SAM looks at one by one
# Lightricks' distilled schedule from the official LTX 2.5 inpaint workflow (stage 1, euler_ancestral)
INPAINT_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
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
# (a relight alone: no matte to composite with or to save).
# no words for an erase: no search by name; not a relight: no light transfer on the edited frame.
OPTIONAL = {"fit_mask": ("matte_a", "matte_b"), "named": ("words",), "relit_frame": ("relight",)}


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


def prompt():
    """FLUX 3 Image Klein's own prompt upsampler: the frame and a short request in, the caption Klein was trained on out.

    Black Forest Labs' card: do not use the model without it. Greedy decoding, so a caption is reproducible; the
    multi-token-prediction head drafts tokens (measured 8 s against 15 s without it, on an RTX PRO 6000).
    """
    g = Graph()
    text = g("TextGenerate", _progress=True, clip=g("CLIPLoader", clip_name=Slot("upsampler", UPSAMPLER), type="flux3", device="default"),
             prompt=Slot("request", ""), image=g("LoadImage", _title="Reference", image=Slot("image", "")),
             max_length=Slot("max_length", 1024), sampling_mode="off", thinking=False, use_default_template=True, mtp="auto",
             system_prompt=g("PrimitiveStringMultiline", _title="System prompt", value=Slot("system", "")))
    g("PreviewAny", _title="Caption", _output="text", source=text)
    g.save("prompt")


def edit():
    """One FLUX 3 Image Klein edit inside a mask: the edited frame, and the edit alone as an RGBA patch."""
    g = Graph()
    model = g("UNETLoader", unet_name=Slot("klein", KLEIN), weight_dtype="default")
    clip = g("CLIPLoader", clip_name=KLEIN_TEXT, type="flux3", device="default")
    vae = g("VAELoader", vae_name=Slot("vae", KLEIN_VAE))
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
    # a relight: the frame as the export will make it, light from Klein, detail from the plate (dropped otherwise)
    base_lin = g("ImageColorSpace", image=base, source="sRGB", destination="linear")
    relit = g("PaintAPlate_RelightTransfer", plate=base_lin, source=half(g, base_lin),
              relit=g("ImageColorSpace", image=half(g, result), source="sRGB", destination="linear"),
              radius=8, strength=Slot("relight", 0.0), align=True)
    g.link_slot(relit, "plate", "relit_frame")
    g("PreviewImage", _title="Relit frame", _output="relit", images=g("ImageColorSpace", image=relit, source="linear", destination="sRGB"))
    g.save("edit")


def snap():
    """SAM 3.1 finds the whole object under an erase stroke: from each stroke point, and by name when there are words."""
    g = Graph()
    sam = g("CheckpointLoaderSimple", ckpt_name=Slot("sam", SAM))
    image = g("LoadImage", _title="First frame", image=Slot("image", ""))
    for k in range(SNAP_POINTS):  # one prompt per point: given together, the points asked SAM for one region holding them all
        found = g("SAM3_Detect", model=sam, image=image, positive_coords=Slot(f"point_{k}", "[]"), threshold=0.5,
                  refine_iterations=2, individual_masks=False)
        g("PreviewImage", _title=f"Object at point {k + 1}", _output=f"point_{k}", images=g("MaskToImage", mask=found))
    named = g("SAM3_Detect", model=sam, image=image, conditioning=g("CLIPTextEncode", text=Slot("words", ""), clip=sam[1]),
              threshold=0.4, refine_iterations=2, individual_masks=True)
    g.link_slot(named, "conditioning", "named")  # dropped when the erase has no words
    # a blank frame first: when nothing has that name, Preview Image would get an empty batch and fail the whole prompt
    size = g("GetImageSize", image=image)
    blank = g("EmptyImage", width=size[0], height=size[1], batch_size=1, color=0)
    g("PreviewImage", _title="Objects with that name", _output="named",
      images=g("BatchImagesNode", images__image0=blank, images__image1=g("MaskToImage", mask=named)))
    g.save("snap")


def live(g, model, size, load):
    """The page's live preview while LTX samples: off (0 steps) unless the page sets `live`."""
    return g("PaintAPlate_LivePreview", _title="Live preview", model=model, decoder=Slot("tiny", TINY), frames=size[2], fps=load[3],
             every=Slot("live", 0), size=320)


def clean():
    """The erase pass: LTX 2.5 with Lightricks' in-outpainting IC-LoRA regenerates every erased area of the shot.

    The reference is the plate with each erased area painted the green the LoRA was trained on, as a grown box: shown
    the object's own outline moving, LTX drew a car back where the van had been; a box hides that shape. The erased
    first frame starts the shot at strength 0.7 (the official workflow's start image). The prompt stays empty: the card
    says prompts describe the scene, never the edit, and a named object came back.
    """
    g = Graph()
    load, srgb = plate(g, pad=True)
    frames = g("ImageScale", image=srgb, upscale_method="lanczos", width=Slot("width", 960), height=Slot("height", 544), crop="disabled")
    size = g("GetImageSize", image=frames)
    hole = g("ImageToMask", channel="red", image=g("ImageScale", image=g("PaintAPlate_LoadPlate", _title="Erase matte", path=Slot("hole", ""),
                                                                          max_frames=1024, pad_8n1=False),
                                                  upscale_method="area", width=size[0], height=size[1], crop="disabled"))
    boxes = g("PaintAPlate_BoxMatte", mask=hole, grow=Slot("box_grow", 0.35))
    reference = g("LTXVInpaintPreprocess", _title="Reference: erased areas in green", images=frames, mask=boxes)
    model = live(g, g("LoraLoaderModelOnly", _title="In-outpainting IC-LoRA",
                      model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"),
                      lora_name=Slot("inoutpaint", INOUTPAINT), strength_model=1.0), size, load)
    clip = g("CLIPLoader", clip_name=Slot("gemma", GEMMA), type="ltxv", device="default")
    vae = g("VAELoader", vae_name=Slot("video_vae", LTX_VAE))
    audio_vae = g("VAELoader", vae_name=LTX_AUDIO_VAE)
    cond = g("LTXVConditioning", positive=g("CLIPTextEncode", text="", clip=clip),
             negative=g("CLIPTextEncode", text=NEGATIVE, clip=clip), frame_rate=load[3])
    first = g("ImageScale", image=g("LoadImage", _title="Erased first frame", image=Slot("hero", "")), upscale_method="lanczos",
              width=size[0], height=size[1], crop="disabled")
    latent = g("LTXVImgToVideoInplace", vae=vae, image=first, latent=g("EmptyLTXVLatentVideo", width=size[0], height=size[1],
                                                                       length=size[2], batch_size=1), strength=0.7, bypass=False)
    guide = g("LTXAddVideoICLoRAGuide", positive=cond[0], negative=cond[1], vae=vae, latent=latent, image=reference, frame_idx=0,
              strength=1.0, latent_downscale_factor=1.0, crop="disabled", use_tiled_encode=False, tile_size=256, tile_overlap=64,
              use_streaming=False, tile_frames=97)
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=load[3], batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=Slot("seed", 0)),
                guider=g("CFGGuider", model=model, positive=guide[0], negative=guide[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler_ancestral"), sigmas=g("ManualSigmas", sigmas=INPAINT_SIGMAS),
                latent_image=g("LTXVConcatAVLatent", video_latent=guide[2], audio_latent=audio))
    decoded = g("VAEDecode", vae=vae, samples=g("LTXVCropGuides", positive=guide[0], negative=guide[1],
                                                 latent=g("LTXVSeparateAVLatent", av_latent=sampled[0])[0])[2])
    g("SaveImage", _title="Clean frames", _output="frames", images=decoded, filename_prefix=Slot("prefix", "paintaplate/plate/clean/f"))
    video = g("CreateVideo", images=decoded, fps=load[3], bit_depth=8, color_space="sRGB", codec="none")
    g("SaveVideo", _title="Clean shot (erased areas regenerated)", _output="video", video=video,
      filename_prefix=Slot("video_prefix", "paintaplate/plate/clean"), format="auto", format__codec="auto")
    g.save("clean")


def shot():
    """LTX 2.5 with the Ripple IC-LoRA: the edited first frame carries through the whole shot.

    When an edit erases, the page gives this workflow the erase pass's result as its plate, so nothing is filled here.
    """
    g = Graph()
    load, srgb = plate(g, pad=True)
    scaled = g("ImageScale", image=srgb, upscale_method="lanczos", width=Slot("width", 960),
               height=Slot("height", 544), crop="disabled")
    size = g("GetImageSize", image=scaled)
    hero = g("ImageScale", image=g("LoadImage", _title="Edited first frame", image=Slot("hero", "")),
             upscale_method="lanczos", width=size[0], height=size[1], crop="disabled")
    rest = g("ImageFromBatch", image=scaled, batch_index=1, length=4096)
    reference = g("BatchImagesNode", _title="Reference: first frame replaced", images__image0=hero,
                  images__image1=rest)
    model = live(g, g("LoraLoaderModelOnly", _title="Ripple IC-LoRA",
                      model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"),
                      lora_name=Slot("ripple", RIPPLE_LORA), strength_model=Slot("strength", 1.35)), size, load)
    clip = g("CLIPLoader", clip_name=Slot("gemma", GEMMA), type="ltxv", device="default")
    vae = g("VAELoader", vae_name=Slot("video_vae", LTX_VAE))
    audio_vae = g("VAELoader", vae_name=LTX_AUDIO_VAE)
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
    sam = g("CheckpointLoaderSimple", ckpt_name=Slot("sam", SAM))
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


def half(g, image):
    """Half size: the light ratio is smooth, so what feeds only the ratio converts to linear light at a quarter of the cost."""
    return g("ImageScaleBy", image=image, upscale_method="area", scale_by=0.5)


def comp():
    """The composite at preview size, as an MP4 to play in the page: what the export will look like."""
    g = Graph()
    load, srgb = plate(g, pad=True)
    small = g("ImageScale", image=srgb, upscale_method="area", width=Slot("width", 960), height=Slot("height", 544),
              crop="disabled")
    gen = g("PaintAPlate_LoadPlate", _title="Generated shot", path=Slot("shot", ""), max_frames=1024, pad_8n1=False)
    union = mattes(g)
    small_lin = g("ImageColorSpace", image=small, source="sRGB", destination="linear")
    relit = g("PaintAPlate_RelightTransfer", plate=small_lin, source=half(g, small_lin),
              relit=g("ImageColorSpace", image=half(g, gen), source="sRGB", destination="linear"),
              radius=Slot("radius", 4), strength=Slot("strength", 1.0), align=True)
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
    # Relight: light from the regenerated shot, detail from the plate, all in linear light. The plate as the
    # model saw it is the same sRGB conversion every other workflow makes, so ComfyUI has it cached.
    size = g("GetImageSize", image=gen)
    source = g("ImageScale", image=g("ImageColorSpace", image=load, source=Slot("color_space", "sRGB"),
                                     destination="sRGB"),
               upscale_method="area", width=size[0], height=size[1], crop="disabled")
    relit = g("PaintAPlate_RelightTransfer",
              plate=g("ImageColorSpace", image=load, source=Slot("color_space", "sRGB"), destination="linear"),
              source=g("ImageColorSpace", image=half(g, source), source="sRGB", destination="linear"),
              relit=g("ImageColorSpace", image=half(g, gen), source="sRGB", destination="linear"),
              radius=Slot("radius", 8), strength=Slot("strength", 1.0), align=True)
    back = g("ImageColorSpace", image=relit, source="linear", destination=Slot("color_space", "sRGB"))
    base = g("ComfySwitchNode", switch=Slot("relight", False), on_false=load, on_true=back)
    # the new pixels are matched to the plate they are composited onto: relit when the light changed
    fit, final = fitted(g, base, gen_plate, union)
    g("PaintAPlate_SavePlate", _title="Export", _output="export", images=final, plate=load[2],
      filename_prefix=Slot("prefix", "paintaplate/plate/export"), keep_untouched=Slot("keep_untouched", True),
      changed=fit[1])
    review = g("ImageScaleToMaxDimension", upscale_method="lanczos", largest_size=1920,
               image=g("ImageFromBatch", batch_index=0, length=load[4],
                       image=g("ImageColorSpace", image=final, source=Slot("color_space", "sRGB"), destination="sRGB")))
    g("SaveVideo", _title="Review movie (full size, H.264)", _output="review", format="auto", format__codec="auto",
      video=g("CreateVideo", images=review, fps=load[3], bit_depth=8, color_space="sRGB", codec="none"),
      filename_prefix=Slot("review_prefix", "paintaplate/plate/review"))
    matte_frames = g("ImageFromBatch", image=g("MaskToImage", mask=fit[1]), batch_index=0, length=load[4])
    g("SaveImage", _title="Matte: where the plate changed", _output="matte", images=matte_frames,
      filename_prefix=Slot("matte_prefix", "paintaplate/plate/matte/matte"))
    g.save("export")


def warm():
    """LTX 2.5, Gemma and both VAEs loaded with one step on a tiny latent, while the person looks at the page."""
    g = Graph()
    clip = g("CLIPLoader", clip_name=Slot("gemma", GEMMA), type="ltxv", device="default")
    vae = g("VAELoader", vae_name=Slot("video_vae", LTX_VAE))
    audio_vae = g("VAELoader", vae_name=LTX_AUDIO_VAE)
    model = g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default")
    cond = g("LTXVConditioning", positive=g("CLIPTextEncode", text="warm up", clip=clip),
             negative=g("CLIPTextEncode", text="", clip=clip), frame_rate=24.0)
    latent = g("LTXVConcatAVLatent", video_latent=g("EmptyLTXVLatentVideo", width=64, height=64, length=9, batch_size=1),
               audio_latent=g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=9, frame_rate=24, batch_size=1))
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=0),
                guider=g("CFGGuider", model=model, positive=cond[0], negative=cond[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler"), sigmas=g("ManualSigmas", sigmas="1.0, 0.0"), latent_image=latent)
    decoded = g("VAEDecode", vae=vae, samples=g("LTXVSeparateAVLatent", av_latent=sampled[0])[0])
    g("PreviewImage", _title="One warm frame", _output="frame", images=g("ImageFromBatch", image=decoded, batch_index=0, length=1))
    g.save("warm")


def fluid():
    """A fluid shot from painted keyframes: LTX 2.5 with AInVFX's ainvfx-fluid IC-LoRA, one distilled pass.

    As its model card and example workflow: the IC-LoRA loader reads the reference downscale factor (2) from the file
    and hands it to the guide; the control video is black with the keyframes at their frames, at the size and length
    of the shot; euler_ancestral, the 8 distilled sigmas, CFG 1, no first-frame image (the LoRA reads frame 0 from the
    control video). The blank plate gives the size, frame rate and length, and Save Plate writes the shot in its format
    (ProRes 4444), so it opens as the next plate.
    """
    g = Graph()
    load, srgb = plate(g, pad=True)
    size = g("GetImageSize", image=srgb)
    control = g("PaintAPlate_KeyframeVideo", _title="Control video: the keyframes on black", width=size[0], height=size[1],
                frames=size[2], keys=Slot("keys", "[]"))
    lora = g("LTXICLoRALoaderModelOnly", _title="ainvfx-fluid IC-LoRA (reads its downscale factor)",
             model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"), lora_name=Slot("fluid", FLUID),
             strength_model=Slot("strength", 1.0))
    model = live(g, lora, size, load)
    clip = g("CLIPLoader", clip_name=Slot("gemma", GEMMA), type="ltxv", device="default")
    vae = g("VAELoader", vae_name=Slot("video_vae", LTX_VAE))
    audio_vae = g("VAELoader", vae_name=LTX_AUDIO_VAE)
    cond = g("LTXVConditioning", positive=g("CLIPTextEncode", text=Slot("prompt", "ainvfxfluid, smoke plume"), clip=clip),
             negative=g("CLIPTextEncode", text=FLUID_NEGATIVE, clip=clip), frame_rate=load[3])
    empty = g("EmptyLTXVLatentVideo", width=size[0], height=size[1], length=size[2], batch_size=1)
    guide = g("LTXAddVideoICLoRAGuide", positive=cond[0], negative=cond[1], vae=vae, latent=empty, image=control, frame_idx=0,
              strength=1.0, latent_downscale_factor=lora[1], crop="disabled", use_tiled_encode=False, tile_size=256,
              tile_overlap=64, use_streaming=False, tile_frames=97)
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=load[3], batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=Slot("seed", 42)),
                guider=g("CFGGuider", model=model, positive=guide[0], negative=guide[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler_ancestral"), sigmas=g("ManualSigmas", sigmas=INPAINT_SIGMAS),
                latent_image=g("LTXVConcatAVLatent", video_latent=guide[2], audio_latent=audio))
    decoded = g("VAEDecode", vae=vae, samples=g("LTXVCropGuides", positive=guide[0], negative=guide[1],
                                                 latent=g("LTXVSeparateAVLatent", av_latent=sampled[0])[0])[2])
    g("PaintAPlate_SavePlate", _title="The fluid plate, in the blank plate's format", _output="plate", images=decoded,
      plate=load[2], filename_prefix=Slot("prefix", "paintaplate/fluid/plate"), keep_untouched=False)
    g("SaveVideo", _title="Fluid shot preview", _output="video", format="auto", format__codec="auto",
      video=g("CreateVideo", images=decoded, fps=load[3], bit_depth=8, color_space="sRGB", codec="none"),
      filename_prefix=Slot("video_prefix", "paintaplate/fluid/preview"))
    g.save("fluid")


if __name__ == "__main__":
    for build in (ingest, prompt, edit, snap, clean, shot, matte, comp, export, warm, fluid):
        build()
    print("wrote", sorted(os.listdir(OUT)))
