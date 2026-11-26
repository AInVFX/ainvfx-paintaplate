"""Write the Paint a plate workflows to web/workflows/*.json.

Each file is a plain ComfyUI workflow in API format, so ComfyUI opens it with Open or by drag
and drop. The page fills some inputs before it posts a workflow: each node lists them in
`_meta.slots` as {input name: slot name}, the outputs the page reads carry `_meta.output`, and
the node whose progress stands for the whole workflow carries `_meta.progress`.
Every node is a core node, a ComfyUI-LTXVideo node or one of the Paint a plate nodes (nodes.py).

    python tools/build_workflows.py
"""
import json
import os

OUT = os.environ.get("PAINTAPLATE_WORKFLOWS_OUT") or os.path.join(os.path.dirname(__file__), "..", "web", "workflows")
NAMES = ("ingest", "prompt", "edit", "snap", "clean", "cleanup", "shot", "matte", "comp", "review", "export", "warm", "fluid", "hdr", "hdr_comp", "upscale", "upscale_export")
OCIO_CONFIG = "ocio://studio-config-latest"  # the page fills the config in use: $OCIO when it is set, as in RV

KLEIN = "flux3-image-klein-int8-convrot.safetensors"
LTX = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
GEMMA = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
UPSAMPLER = "qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors"
NAMING_SYSTEM = "You name things in images for a segmentation model. Answer with the words only, in lowercase."
KEPT_REQUEST = ("List the people, animals and vehicles in this image, each in one or two words, separated by commas. If there are "
                "none, answer: none.")
INOUTPAINT = "ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors"
SAM = "sam3.1_multiplex_fp16.safetensors"
# The memory profile's slots (logic.memoryProfile on the page): `tile`, the tile size of every LTX decode, WHOLE for the
# whole frame in one piece; `encode_tile`, the tile size of the encode in the full-size clean plate pass (cleanup), WHOLE in the same
# way; and `guide_tiled`, the IC-LoRA guide encoded in tiles. Their defaults are a large GPU's.
WHOLE = 4096  # a tile larger than any working frame: VAE Decode (Tiled) decodes the whole frame in one piece
TINY = "taeltx2_3.safetensors"  # the tiny LTX 2.5 decoder of the live preview (models/vae_approx)
FLUID = "ainvfx-fluid.safetensors"  # AInVFX's IC-LoRA: painted keyframes become a fluid: smoke, fire, water and more (models/loras)
KLEIN_TEXT = "qwen3vl_4b_int8_convrot.safetensors"  # FLUX 3 Image Klein's text encoder (models/text_encoders)
KLEIN_VAE = "flux2-vae.safetensors"  # its VAE (models/vae)
LTX_VAE = "ltx-2.5-video-vae-conv-bf16.safetensors"  # LTX 2.5's video VAE (models/vae)
LTX_AUDIO_VAE = "ltx-2.5-audio-vae-bf16.safetensors"  # its audio VAE (models/vae)
RIPPLE_LORA = "LTX25_Ripple_v11.safetensors"  # WepeNerd's Ripple IC-LoRA, which carries paint and light (models/loras)
HDR_LORA = "ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors"  # Lightricks' SDR-to-HDR IC-LoRA (models/loras, gated)
HDR_SCENE = "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors"  # its fixed scene embeddings: the prompt it takes (models/embeddings)
SEEDVR2 = "seedvr2_7b_fp16.safetensors"  # SeedVR2 7B, a one-step video restoration model: Upscale (models/diffusion_models)
SEEDVR2_VAE = "seedvr2_ema_vae_fp16.safetensors"  # its VAE (models/vae)
UPSCALE_CHUNK = 21  # a window's frames when the caller names none (Slot count), and the frames SeedVR2 samples at once (Slot chunk_frames)
HDR_SPACE = "ACES2065-1"  # the SDR-to-HDR frames are saved in it: the colour space the config's file rules give an EXR
FLUID_NEGATIVE = "blurry, low quality, distorted, watermark"  # the negative prompt of its model card's samples
SNAP_POINTS = 5  # stroke points SAM looks at one by one
# Lightricks' distilled schedule from the official LTX 2.5 inpaint workflow (stage 1, euler_ancestral)
INPAINT_SIGMAS = "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"
REFINE_SIGMAS = "0.725, 0.421875, 0.0"  # the high-resolution stage of Lightricks' two-stage LTX 2.5 workflows: 2 steps
EDIT_PREFIX = "paintaplate/edits/edit"  # an edit's outputs are saved, so the job index finds them after a restart
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
# no words for an erase: no search by name; not a relight: no light transfer on the edited frame;
# an erase matte: no plate under a shot to compare with, and no changed pixels to start from; a video plate's review:
# no EXR frames, its movie is the plate's own quality; no SDR-to-HDR shot: the SDR shot goes on as it is; SDR to HDR with
# no plate size (a shot): its HDR frames go on as they are; no movie
# asked of a matte, an export's matte or a fluid shot's control video (the Render panel's rows and the X-ray show them; the ComfyUI
# graph of the Export dialog leaves them out).
OPTIONAL = {"fit_keep": ("paint_matte",), "fit_mask": ("matte_a", "matte_b"), "named": ("words",), "relit_frame": ("relight",),
            "follow_element": ("seed",), "follow_base": ("base",), "follow_named": ("name_request",), "follow_removed": ("removed_request",), "review_frames": ("frames_prefix",), "review_view": ("view_prefix",), "hdr_shot": ("hdr",), "plate_level": ("plate_width", "plate_height"),
            "matte_movie": ("video_prefix",), "export_matte_movie": ("matte_video_prefix",), "fluid_control": ("control_prefix",),
            "export_layer": ("layer_prefix",),
            "export_shot": ("shot_prefix",), "export_clean": ("clean_prefix",), "upscale_comp": ("comp_prefix",), "upscale_matte": ("matte_prefix",)}


def drop_link(prompt, slots, link, sources, extra=()):
    """Remove the input `link` names, the nodes its `sources` slots sit on, every node fed only by them, then every node
    that only fed what went (an output node always stays): no node is left that feeds nothing."""
    fed = set()  # what fed the cut input and the nodes that go
    for nid, key in slots.get(link, []):
        v = prompt.get(nid, {}).get("inputs", {}).pop(key, None)
        if isinstance(v, list):
            fed.add(str(v[0]))
    gone = {nid for source in sources for nid, _ in slots.get(source, [])} | set(extra)
    grew = True
    while grew:
        grew = False
        for nid, node in prompt.items():
            if nid not in gone and any(isinstance(v, list) and str(v[0]) in gone for v in node["inputs"].values()):
                gone.add(nid)
                grew = True
    fed |= {str(v[0]) for nid in gone for v in prompt.get(nid, {}).get("inputs", {}).values() if isinstance(v, list)}
    for nid in gone:
        prompt.pop(nid, None)
    grew = True
    while grew:
        grew = False
        used = {str(v[0]) for node in prompt.values() for v in node["inputs"].values() if isinstance(v, list)}
        for nid in sorted(fed):
            node = prompt.get(nid)
            if node is None or nid in used or "output" in node.get("_meta", {}):
                continue
            fed |= {str(v[0]) for v in node["inputs"].values() if isinstance(v, list)}
            prompt.pop(nid)
            grew = True


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


def colour(g, image, source, destination, title=None, peak_of=None, peak=None):
    """Colour Space (OCIO) in the config the page names (Slot config). Into @model, `peak_of` is the batch `image` is a
    part of: the tone mapping takes that batch's peak. Out of @model, it is the plate in `destination`: the tone mapping of
    its peak is undone, so new content matches the plate's levels. `peak` is that peak as a number: the second
    output of the plate's own conversion, which read it."""
    part = {k: v for k, v in (("peak_of", peak_of), ("peak", peak)) if v is not None}
    return g("PaintAPlate_ColorSpace", _title=title, image=image, config=Slot("config", OCIO_CONFIG), source=source,
             destination=destination, **part)


def plate(g, pad, path="path", progress=False, first=False):
    """The plate in the model space: Load Plate, then Colour Space (OCIO) from the plate's file colour space to @model.

    The tone mapping of values above 1.0 shares one peak per batch, as core's does, so a different batch could change the
    exposure of an HDR plate between steps: every workflow converts the same whole plate. With `first`, the first frame
    alone is converted, with the whole plate's peak: it has the values it has in the whole plate converted, and no second
    copy of the plate is made. The conversion's second output is that peak: composite() hands it on, so the plate is read
    once.
    """
    load = g("PaintAPlate_LoadPlate", _title="Plate", _progress=progress, path=Slot(path, ""),
             max_frames=Slot("max_frames", 121), pad_8n1=pad)
    if not first:
        return load, colour(g, load[0], Slot("color_space", "@model"), "@model", "Plate in the model space")
    frame = g("ImageFromBatch", _title="First frame of the plate", image=load[0], batch_index=0, length=1)
    return load, colour(g, frame, Slot("color_space", "@model"), "@model", "First frame in the model space", peak_of=load[0])


def ingest():
    """The first frame at working size in the model space, a playback proxy of the real frames, and the plate spec.

    The plate is held once: the first frame alone is converted, and Save Movie leaves the 8k+1 padding out, then converts
    and sizes the proxy's frames one at a time. No node makes a second batch of the plate.

    The proxy keeps a video plate's own values, which the viewer converts with OCIO as it does the plate (the page sets
    `proxy_space` to the plate's colour space and `proxy_size` to the working size). An image sequence's proxy is in the
    log values (ACEScct, as the page sets `proxy_space`) at 960: they show what its full-precision frames show, which the
    viewer reads as they arrive.
    """
    g = Graph()
    load, model = plate(g, pad=True, progress=True, first=True)  # same inputs as every other Load Plate: decoded once, then cached
    hero = g("ImageScaleToMaxDimension", image=model, upscale_method="lanczos", largest_size=1920)
    g("SaveImage", _title="First frame", _output="hero", images=hero,
      filename_prefix=Slot("prefix", "paintaplate/plate/hero"))
    g("PaintAPlate_SaveMovie", _title="Playback proxy", _output="proxy", images=load[0], frames=load[4], fps=load[3], crf=12,
      config=Slot("config", OCIO_CONFIG), source=Slot("color_space", "@model"), destination=Slot("proxy_space", "@model"),
      largest_size=Slot("proxy_size", 960), width=Slot("movie_width", 0), height=Slot("movie_height", 0),
      filename_prefix=Slot("video_prefix", "paintaplate/plate/proxy"))
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
    """One FLUX 3 Image Klein edit inside a mask: the edited frame, and the edit alone as an RGBA patch.

    For an erase (`level` on), Level Fill evens Klein's fill with the background around it first. The outputs are saved
    to the output folder rather than shown as previews, so a later session on the same machine finds them again.
    """
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
    # an erase's fill, levelled with the background it continues (Level Fill); paint and light pass through
    filled = g("PaintAPlate_LevelFill", _title="Fill levelled with the background (erase only)", image=decoded, alpha=soft,
               base=base, paint=mask, enabled=Slot("level", False))
    result = g("ImageCompositeMasked", destination=base, source=filled, x=0, y=0, resize_source=False, mask=soft)
    g("SaveImage", _title="Edited frame", _output="result", images=result, filename_prefix=Slot("prefix", EDIT_PREFIX))
    # Join Image with Alpha stores 1 - mask as alpha: the inverted soft mask gives alpha = soft mask
    patch = g("JoinImageWithAlpha", image=filled, alpha=g("InvertMask", mask=soft))
    g("SaveImage", _title="Edit patch (RGBA)", _output="patch", images=patch, filename_prefix=Slot("prefix", EDIT_PREFIX))
    # a relight: the frame as the export will make it, light from Klein, detail from the plate (dropped otherwise).
    # Relight Transfer decodes the sRGB frames to linear light and encodes its result back itself
    relit = g("PaintAPlate_RelightTransfer", plate=base, source=half(g, base), relit=half(g, result), radius=1,
              strength=Slot("relight", 0.0), align=True, plate_space="sRGB", shot_space="sRGB")
    g.link_slot(relit, "plate", "relit_frame")
    g("SaveImage", _title="Relit frame", _output="relit", images=relit, filename_prefix=Slot("prefix", EDIT_PREFIX))
    g.save("edit")


def snap():
    """SAM 3.1 finds the whole object under an erase stroke: from each stroke point, and by name when there are words."""
    g = Graph()
    sam = g("CheckpointLoaderSimple", ckpt_name=Slot("sam", SAM))
    image = g("LoadImage", _title="First frame", image=Slot("image", ""))
    for k in range(SNAP_POINTS):  # one prompt per point: given together, the points ask SAM for one region that holds them all
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


def live(g, model, size, load, transfer="sRGB"):
    """The page's live preview while LTX samples: off (0 steps) unless the page sets `live`."""
    return g("PaintAPlate_LivePreview", _title="Live preview", model=model, decoder=Slot("tiny", TINY), frames=size[2], fps=load[3], **({"transfer": transfer} if transfer != "sRGB" else {}),
             every=Slot("live", 0), size=320)


def erased_grid(g, matte):
    """The erase matte as blocks of LTX's 32 px grid, grown by one block: (the grid as a mask, the grid as an image).
    `matte` is at the size LTX works at.

    Blocks hide the object's outline: shown its own outline moving, LTX draws an object back where it was. They keep the
    background around the object in view, so LTX continues it. One grown box per frame also hides the outline, but around a
    truss, a crane or a door it covers the whole backdrop, and LTX animates a faint fill there into smoke.
    """
    cells = g("GrowMask", _title="One block more on every side", expand=Slot("grid_grow", 1), tapered_corners=False,
              mask=g("ThresholdMask", _title="Every block the matte touches", value=0.02,
                     mask=g("ImageToMask", channel="red", image=g("ImageScaleBy", _title="Clean matte on LTX's 32 px grid", image=matte,
                                                                upscale_method="area", scale_by=1 / 32))))
    return cells, g("MaskToImage", mask=cells)


def erased_blocks(g, matte, size):
    """The blocks of `erased_grid` at `size`, where LTX's reference is painted green: (the blocks at `size`, the grid of blocks)."""
    _, grid = erased_grid(g, matte)
    blocks = g("ImageToMask", channel="red", image=g("ImageScale", image=grid, upscale_method="nearest-exact", width=size[0],
                                                     height=size[1], crop="disabled"))
    return blocks, grid


def clean():
    """The erase pass: LTX 2.5 with Lightricks' in-outpainting IC-LoRA regenerates every erased area of the shot.

    The reference is the plate with each erased area painted the green the LoRA was trained on, as blocks of LTX's grid
    (`erased_blocks`). The erased first frame starts the shot at strength 0.7 (the official workflow's start image). The
    prompt describes the scene as it stays, in the prompt writer's own words for what it kept (`erasePrompt` on the page);
    it never names the erased object: named, the object comes back. At full size this pass is the first stage, at half the
    working size, and `cleanup` the second.
    """
    g = Graph()
    load, model = plate(g, pad=True)
    frames = g("ImageScale", image=model, upscale_method="lanczos", width=Slot("width", 960), height=Slot("height", 544), crop="disabled")
    size = g("GetImageSize", image=frames)
    matte = g("ImageScale", image=g("PaintAPlate_LoadPlate", _title="Clean matte", path=Slot("hole", ""), max_frames=1024, pad_8n1=False),
              upscale_method="area", width=size[0], height=size[1], crop="disabled")
    blocks, _ = erased_blocks(g, matte, size)
    reference = g("LTXVInpaintPreprocess", _title="Reference: erased areas in green", images=frames, mask=blocks)
    model = live(g, g("LoraLoaderModelOnly", _title="In-outpainting IC-LoRA",
                      model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"),
                      lora_name=Slot("inoutpaint", INOUTPAINT), strength_model=1.0), size, load)
    clip = g("CLIPLoader", clip_name=Slot("gemma", GEMMA), type="ltxv", device="default")
    vae = g("VAELoader", vae_name=Slot("video_vae", LTX_VAE))
    audio_vae = g("VAELoader", vae_name=LTX_AUDIO_VAE)
    cond = g("LTXVConditioning", positive=g("CLIPTextEncode", _title="The scene as it stays", text=Slot("prompt", ""), clip=clip),
             negative=g("CLIPTextEncode", text=NEGATIVE, clip=clip), frame_rate=load[3])
    first = g("ImageScale", image=g("LoadImage", _title="Cleaned first frame", image=Slot("hero", "")), upscale_method="lanczos",
              width=size[0], height=size[1], crop="disabled")
    latent = g("LTXVImgToVideoInplace", vae=vae, image=first, latent=g("EmptyLTXVLatentVideo", width=size[0], height=size[1],
                                                                       length=size[2], batch_size=1), strength=0.7, bypass=False)
    guide = g("LTXAddVideoICLoRAGuide", positive=cond[0], negative=cond[1], vae=vae, latent=latent, image=reference, frame_idx=0,
              strength=1.0, latent_downscale_factor=1.0, crop="disabled", use_tiled_encode=Slot("guide_tiled", False), tile_size=256, tile_overlap=64,
              use_streaming=False, tile_frames=97)
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=load[3], batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=Slot("seed", 0)),
                guider=g("CFGGuider", model=model, positive=guide[0], negative=guide[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler_ancestral"), sigmas=g("ManualSigmas", sigmas=INPAINT_SIGMAS),
                latent_image=g("LTXVConcatAVLatent", video_latent=guide[2], audio_latent=audio))
    decoded = g("VAEDecode", vae=vae, samples=g("LTXVCropGuides", positive=guide[0], negative=guide[1],
                                                 latent=g("LTXVSeparateAVLatent", av_latent=sampled[0])[0])[2])
    g("PaintAPlate_SaveFrames", _title="Clean frames", _output="frames", images=decoded, format=Slot("frames_format", "png"),
      filename_prefix=Slot("prefix", "paintaplate/plate/clean/f"))
    g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Clean shot (erased areas regenerated)", _output="video", filename_prefix=Slot("video_prefix", "paintaplate/plate/clean"), images=decoded, fps=load[3])
    g.save("clean")


def cleanup():
    """The erase pass at full size: the high-resolution stage of Lightricks' two-stage LTX 2.5 inpainting workflow.

    The first stage is the erase pass at half the working size (`clean`). Its frames, enlarged, go inside the erased blocks
    over the plate at full size, and LTX refines them in 2 steps from sigma 0.725, with the IC-LoRA and without the reference
    video, as the official workflow does. The erased first frame is kept as it is (strength 1). 8 steps at full size took
    181 s on a 1080p plate, this stage 82.8 s, 30.1 s of it saving the frames.

    Composite Frames makes that start one frame at a time and holds it once: 2.8 GB for 121 frames at 1920 x 1088. Image
    Scale and Image Composite Masked make the same pictures from the whole shot: the plate, the first stage and the blocks
    at full size (9.4 GB), then core's composite, which holds four copies of the shot and two of its mask at its peak:
    13.2 GB. That is 16.5 GB above the 32.0 GB that ComfyUI holds after the first stage, more than a 16 GB GPU with 52 GB of
    RAM has. With Composite Frames, this stage holds 28.5 GB when posted, 31.8 GB before LTX loads, and 38.3 GB at its peak,
    on a 16 GB GPU under a cap of 52 GB.
    """
    g = Graph()
    load, model = plate(g, pad=True)
    matte = g("ImageScale", image=g("PaintAPlate_LoadPlate", _title="Clean matte", path=Slot("hole", ""), max_frames=1024, pad_8n1=False),
              upscale_method="area", width=Slot("width", 1920), height=Slot("height", 1088), crop="disabled")
    cells, _ = erased_grid(g, matte)
    start = g("PaintAPlate_CompositeFrames", _title="Stage 1 inside the blocks, the plate around them", destination=model,
              source=g("PaintAPlate_LoadPlate", _title="Clean plate pass at half size", path=Slot("low", ""), max_frames=1024, pad_8n1=False),
              mask=cells, width=Slot("width", 1920), height=Slot("height", 1088))
    size = g("GetImageSize", image=start)
    model = g("LoraLoaderModelOnly", _title="In-outpainting IC-LoRA", model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"),
              lora_name=Slot("inoutpaint", INOUTPAINT), strength_model=1.0)
    clip = g("CLIPLoader", clip_name=Slot("gemma", GEMMA), type="ltxv", device="default")
    vae = g("VAELoader", vae_name=Slot("video_vae", LTX_VAE))
    audio_vae = g("VAELoader", vae_name=LTX_AUDIO_VAE)
    cond = g("LTXVConditioning", positive=g("CLIPTextEncode", _title="The scene as it stays", text=Slot("prompt", ""), clip=clip),
             negative=g("CLIPTextEncode", text=NEGATIVE, clip=clip), frame_rate=load[3])
    first = g("ImageScale", image=g("LoadImage", _title="Cleaned first frame", image=Slot("hero", "")), upscale_method="lanczos",
              width=size[0], height=size[1], crop="disabled")
    latent = g("LTXVImgToVideoInplace", vae=vae, image=first, strength=1.0, bypass=False,
               latent=g("VAEEncodeTiled", pixels=start, vae=vae, tile_size=Slot("encode_tile", WHOLE), overlap=64, temporal_size=500, temporal_overlap=64))
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=load[3], batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=Slot("seed", 0)),
                guider=g("CFGGuider", model=live(g, model, size, load), positive=cond[0], negative=cond[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler"), sigmas=g("ManualSigmas", sigmas=REFINE_SIGMAS),
                latent_image=g("LTXVConcatAVLatent", video_latent=latent, audio_latent=audio))
    # the whole frame in one piece by default, in 128-frame temporal tiles, as the hdr workflow decodes (hdr())
    decoded = g("VAEDecodeTiled", tile_size=Slot("tile", WHOLE), overlap=64, temporal_size=128, temporal_overlap=32, vae=vae, samples=g("LTXVSeparateAVLatent", av_latent=sampled[0])[0])
    g("PaintAPlate_SaveFrames", _title="Clean frames", _output="frames", images=decoded, format=Slot("frames_format", "png"),
      filename_prefix=Slot("prefix", "paintaplate/plate/full/clean/f"))
    g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Clean shot at full size", _output="video", filename_prefix=Slot("video_prefix", "paintaplate/plate/full/clean"), images=decoded, fps=load[3])
    g.save("cleanup")


def shot():
    """LTX 2.5 with the Ripple IC-LoRA: the edited first frame carries through the whole shot.

    When an edit erases, the page gives this workflow the erase pass's result as its plate, so nothing is filled here.
    """
    g = Graph()
    load, model = plate(g, pad=True)
    scaled = g("ImageScale", image=model, upscale_method="lanczos", width=Slot("width", 960),
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
              use_tiled_encode=Slot("guide_tiled", False), tile_size=256, tile_overlap=64, use_streaming=False, tile_frames=97)
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=load[3], batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=Slot("seed", 0)),
                guider=g("CFGGuider", model=model, positive=guide[0], negative=guide[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler"),
                sigmas=g("BasicScheduler", model=model, scheduler="simple", steps=Slot("steps", 8), denoise=1.0),
                latent_image=g("LTXVConcatAVLatent", video_latent=guide[2], audio_latent=audio))
    video_latent = g("LTXVSeparateAVLatent", av_latent=sampled[0])
    cropped = g("LTXVCropGuides", positive=guide[0], negative=guide[1], latent=video_latent[0])
    # the whole frame in one piece by default, in 128-frame temporal tiles, as the hdr workflow decodes (hdr())
    decoded = g("VAEDecodeTiled", tile_size=Slot("tile", WHOLE), overlap=64, temporal_size=128, temporal_overlap=32, samples=cropped[2], vae=vae)
    g("PaintAPlate_SaveFrames", _title="Shot frames", _output="frames", images=decoded, format=Slot("frames_format", "png"),
      filename_prefix=Slot("prefix", "paintaplate/plate/shot/f"))
    g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Shot video (whole frame regenerated)", _output="video", filename_prefix=Slot("video_prefix", "paintaplate/plate/shot"), images=decoded, fps=load[3])
    g.save("shot")


def matte():
    """SAM 3.1 follows the edit through the frames, asked several questions, then Follow Matte judges its answers by how
    much the shot changed (mathops.follow_votes; a Clean: mathops.clean_votes). FLUX 3 Image Klein's prompt upsampler,
    as in prompt(), names the edit's object from the first frame (`name_request`; a Clean: `removed_request`, the thing it
    removes) and the plate's main person, animal or vehicle, and SAM Words keeps the words SAM searches for. SAM follows
    the shot from the edit's prompt mask with the object's name (`prompt`: the element; a Clean: the plate from the zone),
    the shot from the name alone, the plate from the element (the object the edit replaces) and the plate from the kept
    thing's name. The page drops the name's tracks when the edit has no text prompt, and the plate's element track for
    a Clean. With the plate's first frame number (`first_frame`), the summary names the plate's own frames; the
    strategy (`strategy`, mathops.MATTE_STRATEGIES) sets how much of the shot the composite takes."""
    g = Graph()
    load, model = plate(g, pad=True)
    frames = g("ImageScale", image=model, upscale_method="area", width=Slot("width", 960),
               height=Slot("height", 544), crop="disabled")
    sam = g("CheckpointLoaderSimple", ckpt_name=Slot("sam", SAM))
    first = g("LoadImageMask", _title="Area on the first frame", image=Slot("mask", ""), channel="red")
    prompt_mask = g("LoadImageMask", _title="SAM's prompt on the first frame", image=Slot("prompt", ""), channel="red")
    element = g("LoadImageMask", _title="Where the edit changed the first frame", image=Slot("seed", ""), channel="red")
    under = g("PaintAPlate_LoadPlate", _title="Plate under the shot", path=Slot("base", ""), max_frames=Slot("max_frames", 121),
              pad_8n1=True)
    under = g("ImageScale", image=colour(g, under, Slot("base_color_space", "@model"), "@model"),
              upscale_method="area", width=Slot("width", 960), height=Slot("height", 544), crop="disabled")
    upsampler = g("CLIPLoader", clip_name=Slot("upsampler", UPSAMPLER), type="flux3", device="default")
    system = g("PrimitiveString", _title="Naming", value=NAMING_SYSTEM)  # one line: a multiline text reads as a note in the scene's graph

    def named(image, request, kind, title):  # the upsampler's answer about one frame, as the words SAM searches for
        text = g("TextGenerate", _title=title, clip=upsampler, prompt=request, image=g("ImageFromBatch", image=image, batch_index=0, length=1),
                 max_length=64, sampling_mode="off", thinking=False, use_default_template=True, mtp="auto", system_prompt=system)
        return g("CLIPTextEncode", text=g("PaintAPlate_SamWords", text=text, kind=kind), clip=sam[1])

    def track(images, title, progress=False, **prompts):  # the first track carries the step's progress
        return g("SAM3_VideoTrack", _title=title, _progress=progress, images=images, model=sam, detection_threshold=0.5, max_objects=4,
                 detect_interval=1, **prompts)

    name = named(frames, Slot("name_request", ""), "thing", "The edit's object, named")
    removed = named(frames, Slot("removed_request", ""), "thing", "The removed thing, named")
    kept = named(under, KEPT_REQUEST, "kept", "What the plate keeps, named")
    asked = track(frames, "SAM 3.1: the prompt mask and the name", progress=True, initial_mask=prompt_mask, conditioning=name)
    g.link_slot(asked, "conditioning", "follow_named")
    by_name = track(frames, "SAM 3.1: the name", conditioning=name)
    by_removed = track(frames, "SAM 3.1: the removed thing's name", conditioning=removed)
    by_plate = track(under, "SAM 3.1: the plate from the element", initial_mask=element)
    by_kept = track(under, "SAM 3.1: what the plate keeps", conditioning=kept)
    follow = g("PaintAPlate_FollowMatte", masks=g("SAM3_TrackToMask", track_data=asked, object_indices=""), first=first, frames=frames,
               base=under, element=element, word_masks=g("SAM3_TrackToMask", track_data=by_name, object_indices=""), named=by_removed,
               plate_masks=g("SAM3_TrackToMask", track_data=by_plate, object_indices=""), kept=by_kept,
               zone=Slot("zone", 0.0625), threshold=Slot("threshold", 0.1), first_frame=Slot("first_frame", 1),
               strategy=Slot("strategy", "Auto"))
    g.link_slot(follow, "word_masks", "follow_named")
    g.link_slot(follow, "named", "follow_removed")
    g.link_slot(follow, "element", "follow_element")  # a Clean has no element: its matte follows the zone
    g.link_slot(follow, "plate_masks", "follow_element")
    g.link_slot(follow, "base", "follow_base")  # the plate under the matte: a paint's, or a Clean's own plate
    g.link_slot(follow, "kept", "follow_base")  # what the plate keeps is found on it
    grey = g("MaskToImage", mask=follow[0])
    g("PaintAPlate_SaveFrames", _title="Matte frames", _output="frames", images=grey, filename_prefix=Slot("prefix", "paintaplate/plate/matte/m"))
    movie = g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Matte movie (grey): its row in the Render panel shows it", _output="movie", images=grey,
              fps=load[3], crf=18, filename_prefix=Slot("video_prefix", ""))
    g.link_slot(movie, "images", "matte_movie")
    g("PreviewAny", _title="How the matte followed", _output="follow", source=follow[1])
    g.save("matte")


def mattes(g):
    """The erase and paint mattes as one mask, at the paint matte's size. A missing matte is the other one again (the page
    sets both). The erase is tracked smaller (ERASE_TRACK_SIDE in app.mjs: 576 x 320 for a 1080p plate, the paint at
    960 x 544), and Combine Masks crops its source to its destination instead of scaling it: with the smaller erase matte as its
    destination, the paint matte would keep only its top-left corner, and a painted object could leave the composite."""
    erase = g("PaintAPlate_LoadPlate", _title="Clean matte", path=Slot("matte_a", ""), max_frames=1024, pad_8n1=False)
    add = g("PaintAPlate_LoadPlate", _title="Paint matte", path=Slot("matte_b", ""), max_frames=1024, pad_8n1=False)
    size = g("GetImageSize", image=add)
    erase = g("ImageScale", _title="Clean matte at the paint matte's size", image=erase, upscale_method="bilinear",
              width=size[0], height=size[1], crop="disabled")
    paint = g("ImageToMask", image=add, channel="red")  # the paint matte alone too: a painted object keeps its colours
    return g("MaskComposite", destination=g("ImageToMask", image=erase, channel="red"), source=paint, x=0, y=0, operation="add"), paint


def fitted(g, base, gen, union, paint=None):
    """Fit to Plate, then the composite: the edit over `base`, everything else untouched. `paint`, the paint matte: the
    colour match leaves a painted object as the shot made it, and fixes the edge the composite adds around it."""
    fit = g("PaintAPlate_FitToPlate", _progress=True, plate=base, image=gen, mask=union, align=True, max_shift=8.0,
            match_color=True, grain=Slot("grain", 1.0), grow=Slot("grow", 8), feather=Slot("feather", 12),
            steady=Slot("steady", 2), **({"keep": paint} if paint is not None else {}))
    g.link_slot(fit, "mask", "fit_mask")  # the page drops this link when there is no matte
    if paint is not None:
        g.link_slot(fit, "keep", "fit_keep")  # and this one when there is no paint matte (a Clean alone)
    # One frame at a time: core's Image Composite Masked holds four copies of the shot and two of its mask on a whole
    # batch. Fit to Plate always gives a mask (zeros without a matte), and Load Plate gives the plate's alpha apart: RGB here
    size = g("GetImageSize", image=base)
    final = g("PaintAPlate_CompositeFrames", _title="Composite", destination=base, source=fit[0], mask=fit[1],
              width=size[0], height=size[1])
    return fit, final


def half(g, image):
    """Half size: the light ratio is smooth, so what feeds only the ratio converts to linear light at a quarter of the cost."""
    return g("ImageScaleBy", image=image, upscale_method="area", scale_by=0.5)


def xray_matte(g, fit, load):
    """The matte the composite blends the shot in with (Fit to Plate's, aligned to the plate), as a grey movie: the X-ray
    shows it, so its tint covers what the composite changes."""
    g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Matte movie (grey): the X-ray shows it",
      _output="matte_movie", images=g("MaskToImage", mask=fit[1]), frames=load[4], fps=load[3], crf=18, filename_prefix=Slot("matte_video_prefix", ""))


def comp():
    """The composite at preview size, as an MP4 to play in the page: what the export will look like."""
    g = Graph()
    load, model = plate(g, pad=True)
    small = g("ImageScale", image=model, upscale_method="area", width=Slot("width", 960), height=Slot("height", 544),
              crop="disabled")
    gen = g("PaintAPlate_LoadPlate", _title="Generated shot", path=Slot("shot", ""), max_frames=1024, pad_8n1=False)
    union, paint = mattes(g)
    relit = g("PaintAPlate_RelightTransfer", plate=small, source=half(g, small), relit=half(g, gen),
              plate_space="sRGB", shot_space="sRGB", radius=Slot("radius", 1), strength=Slot("strength", 1.0), align=True)
    base = g("ComfySwitchNode", switch=Slot("relight", False), on_false=small, on_true=relit)
    fit, final = fitted(g, base, gen, union, paint)
    xray_matte(g, fit, load)
    # the writer takes the composite as it is and saves the plate's own frames (`frames`): no second batch of the shot
    g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Composite preview", _output="video", filename_prefix=Slot("video_prefix", "paintaplate/plate/comp"), images=final, frames=load[4], fps=load[3])
    g.save("comp")


def composite(g):
    """The full-size composite in the plate's own colour space, which review and export share: the shot fitted onto the
    plate, relit when the light changed, and everywhere else the plate's own pixels."""
    load, model = plate(g, pad=True)
    gen = g("PaintAPlate_LoadPlate", _title="Generated shot", path=Slot("shot", ""), max_frames=1024, pad_8n1=False)
    union, paint = mattes(g)
    # The shot matches the plate's levels: the tone mapping of the plate's peak, which the models saw, is undone.
    # The peak is the number the plate's conversion into the model space read (its second output): the plate is read once.
    gen_plate = colour(g, gen, "@model", Slot("color_space", "@model"), "Shot in the plate's colour space", peak=model[1])
    # Relight: the light from the regenerated shot, the detail from the plate, in linear light. The plate as the model saw
    # it is the conversion every workflow makes, so ComfyUI has it cached. Relight Transfer undoes the tone mapping of the
    # plate's peak on the shot's two inputs, so it measures the light at the plate's levels.
    size = g("GetImageSize", image=gen)
    source = g("ImageScale", image=model, upscale_method="area", width=size[0], height=size[1], crop="disabled")
    linear = colour(g, load[0], Slot("color_space", "@model"), "@linear")
    relit = g("PaintAPlate_RelightTransfer", plate=linear, source=half(g, source), relit=half(g, gen),
              plate_space="linear", shot_space="sRGB", radius=Slot("radius", 1), strength=Slot("strength", 1.0),
              align=True, peak=model[1])
    back = colour(g, relit, "@linear", Slot("color_space", "@model"))
    base = g("ComfySwitchNode", switch=Slot("relight", False), on_false=load[0], on_true=back)
    # SDR to HDR: where the hdr workflow made the shot again in scene-linear values, those values, fitted to the plate's own
    # on the untouched pixels. Without them (the hdr_shot link dropped) HDR Match passes the SDR shot through.
    hdr = colour(g, g("PaintAPlate_LoadPlate", _title="HDR shot", path=Slot("hdr", ""), max_frames=1024, pad_8n1=False),
                 HDR_SPACE, Slot("color_space", "@model"), "HDR shot in the plate's colour space")
    shot = g("PaintAPlate_HDRMatch", _title="HDR Match: the HDR shot fitted to the plate", image=gen_plate, plate=load[0], mask=union,
             hdr=hdr, grow=Slot("hdr_grow", 24.0))
    g.link_slot(shot, "hdr", "hdr_shot")
    g.link_slot(shot, "mask", "fit_mask")  # no matte: the link goes, as Fit to Plate's does
    # the new pixels are matched to the plate they are composited onto: relit when the light changed
    fit, final = fitted(g, base, shot, union, paint)
    return load, fit, final, gen_plate, model  # with the shot in the plate's colour space, and the plate as the models see it


def review():
    """What the viewer plays once the shot is made, at the plate's quality: the full-size composite as a movie (a video
    plate's own values, an image sequence in the model space) and, for an image sequence, as half-float EXR frames in the
    plate's own colour space, which the viewer reads at full precision. It runs right after the full-size passes;
    nothing here is written for compositing software (that is export, when Export is pressed)."""
    g = Graph()
    load, fit, final, _, _ = composite(g)
    xray_matte(g, fit, load)
    # Each writer takes the composite as it is: it saves the plate's own frames (`frames`, without Load Plate's padding) and
    # converts each frame as it saves it, so no second batch of the shot is held
    g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Review movie (full-size composite, H.264)", _output="review", images=final, frames=load[4],
      config=Slot("config", OCIO_CONFIG), source=Slot("color_space", "@model"), destination=Slot("movie_space", "@model"), fps=load[3], crf=12,
      filename_prefix=Slot("review_prefix", "paintaplate/plate/review"))
    frames = g("PaintAPlate_SaveFrames", _title="Review frames (half-float EXR, image sequences only)", _output="frames",
               images=final, frames=load[4], format="exr", fps=load[3], filename_prefix=Slot("frames_prefix", ""))
    g.link_slot(frames, "images", "review_frames")  # dropped for a video plate
    # What the viewer plays for an image sequence: log values (ACEScct, `view_space`), so the 8-bit movie shows what its EXR
    # frames show at full precision. The review movie above stays in the model space, for the zip. Dropped for a video plate.
    view = g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Viewer movie (image sequences: log values, the look of the EXR frames)", _output="view",
             images=final, frames=load[4], config=Slot("config", OCIO_CONFIG), source=Slot("color_space", "@model"), destination=Slot("view_space", "ACEScct"),
             fps=load[3], crf=12, filename_prefix=Slot("view_prefix", ""))
    g.link_slot(view, "images", "review_view")
    g.save("review")


def export():
    """For compositing software, when Export is pressed: the composite the review shows, written by Save Plate (a
    sequence in the plate's own format, its EXR layers and untouched pixels exactly the source's; a movie as ProRes 4444
    XQ, its untouched pixels the source's own samples), with the matte of where the plate changed as 16-bit PNG frames
    and, for an edit that keeps the plate's untouched pixels, the layer the composite blends in:
    result = plate x (1 - matte) + layer x matte."""
    g = Graph()
    load, fit, final, shot_plate, model = composite(g)
    g("PaintAPlate_SavePlate", _title="Export", _output="export", images=final, plate=load[2],
                  filename_prefix=Slot("prefix", "paintaplate/plate/export"), keep_untouched=Slot("keep_untouched", True),
                  changed=fit[1])
    # Each writer takes its batch as it is and saves the plate's own frames (`frames`, without Load Plate's padding): no
    # second batch of the shot is held
    # The layer: the shot as the composite blends it. Composite Frames sizes its source to the plate with the bilinear
    # filter of Image Scale, so this is the picture it blends. Written as the result is: by Save Plate with no
    # source pixel kept. A relight leaves it out (Slot layer_prefix empty): every pixel of its result may change, so the
    # result is the only layer.
    size = g("GetImageSize", image=load[0])
    layer = g("ImageScale", _title="Layer: the shot as the composite blends it", image=fit[0], upscale_method="bilinear",
              width=size[0], height=size[1], crop="disabled")
    layer_plate = g("PaintAPlate_SavePlate", _title="Layer", _output="layer", images=layer, plate=load[2],
                    filename_prefix=Slot("layer_prefix", ""), keep_untouched=False)
    g.link_slot(layer_plate, "images", "export_layer")
    # The shot as the model made it, and a Clean's pass when a paint rides on it: in the plate's colour space, written as every
    # element is, by Save Plate in the export's format, at their own size, with none of the source's pixels. The page fills
    # shot_prefix, and clean_pass with clean_prefix, when Export takes them (logic's OPTIONAL: export_shot, export_clean).
    shot_out = g("PaintAPlate_SavePlate", _title="Shot: the frames the model made", _output="shot", images=shot_plate, plate=load[2],
                 filename_prefix=Slot("shot_prefix", ""), keep_untouched=False)
    g.link_slot(shot_out, "images", "export_shot")
    clean = colour(g, g("PaintAPlate_LoadPlate", _title="Clean plate pass", path=Slot("clean_pass", ""), max_frames=1024, pad_8n1=False),
                   "@model", Slot("color_space", "@model"), "Clean plate pass in the plate's colour space", peak=model[1])
    clean_out = g("PaintAPlate_SavePlate", _title="Clean plate pass", _output="clean", images=clean, plate=load[2],
                  filename_prefix=Slot("clean_prefix", ""), keep_untouched=False)
    g.link_slot(clean_out, "images", "export_clean")
    matte_frames = g("MaskToImage", mask=fit[1])
    g("PaintAPlate_SaveFrames", _title="Matte: where the plate changed (16-bit PNG)", _output="matte", images=matte_frames, frames=load[4],
      format="png16", filename_prefix=Slot("matte_prefix", "paintaplate/plate/matte/matte"))
    movie = g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Matte movie (grey): the X-ray shows it", _output="matte_movie", images=matte_frames,
              frames=load[4], fps=load[3], crf=18, filename_prefix=Slot("matte_video_prefix", ""))
    g.link_slot(movie, "images", "export_matte_movie")
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
    control video). The blank plate gives the frame rate and the length, and the size unless `width` and `height` ask for
    the shot preview's. Save Plate writes the shot as ProRes 4444 XQ, as every movie of the export, and Save Image writes its
    first frame, as `ingest` writes a plate's first frame.
    """
    g = Graph()
    load, model = plate(g, pad=True)
    scaled = g("ImageScale", image=model, upscale_method="lanczos", width=Slot("width", 0), height=Slot("height", 0), crop="disabled")
    size = g("GetImageSize", image=scaled)
    control = g("PaintAPlate_KeyframeVideo", _title="Control video: the keyframes on black", width=size[0], height=size[1],
                frames=size[2], keys=Slot("keys", "[]"))
    shown = g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Control video as a movie: the keyframes on black", _output="control",
              images=control, fps=load[3], crf=18, filename_prefix=Slot("control_prefix", ""))
    g.link_slot(shown, "images", "fluid_control")
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
              strength=1.0, latent_downscale_factor=lora[1], crop="disabled", use_tiled_encode=Slot("guide_tiled", False), tile_size=256,
              tile_overlap=64, use_streaming=False, tile_frames=97)
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=load[3], batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=Slot("seed", 42)),
                guider=g("CFGGuider", model=model, positive=guide[0], negative=guide[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler_ancestral"), sigmas=g("ManualSigmas", sigmas=INPAINT_SIGMAS),
                latent_image=g("LTXVConcatAVLatent", video_latent=guide[2], audio_latent=audio))
    # the whole frame in one piece by default, in 128-frame temporal tiles, as the hdr workflow decodes (hdr())
    decoded = g("VAEDecodeTiled", tile_size=Slot("tile", WHOLE), overlap=64, temporal_size=128, temporal_overlap=32, vae=vae, samples=g("LTXVCropGuides", positive=guide[0], negative=guide[1],
                                                 latent=g("LTXVSeparateAVLatent", av_latent=sampled[0])[0])[2])
    g("PaintAPlate_SavePlate", _title="The fluid shot, as ProRes 4444 XQ", _output="plate", images=decoded,
      plate=load[2], filename_prefix=Slot("prefix", "paintaplate/fluid/plate"), keep_untouched=False)
    g("SaveVideo", _title="Fluid shot preview", _output="video", format="auto", format__codec="auto",
      video=g("CreateVideo", images=decoded, fps=load[3], bit_depth=8, color_space="sRGB", codec="none"),
      filename_prefix=Slot("video_prefix", "paintaplate/fluid/preview"))
    g("SaveImage", _title="First frame", _output="first", images=g("ImageFromBatch", image=decoded, batch_index=0, length=1),
      filename_prefix=Slot("first_prefix", "paintaplate/fluid/first"))
    g.save("fluid")



def hdr():
    """SDR to HDR: a full-size shot made again in scene-linear values by Lightricks' LTX 2.5 SDR-to-HDR IC-LoRA, saved as
    half-float EXR frames in ACES2065-1 (HDR_SPACE).

    As Lightricks' official workflow (example_workflows/2.5/HDR_workflows/LTX-2.5_ICLoRA_SDR_to_HDR_Distilled.json in the
    pinned ComfyUI-LTXVideo): core Convert Image Color Space maps the shot from sRGB to ACEScct, the IC-LoRA's guide (not the
    creative SDR-to-HDR expand); fixed scene embeddings stand for the prompt, positive and negative, at CFG 1; the 8 distilled
    sigmas with euler; the video VAE in float32 encodes the guide and decodes the result, tiled (128-frame temporal tiles, as
    Lightricks' Tiled Fusion graph); Colour Space (OCIO) turns the decoded ACEScct codes into ACEScg scene-linear values with
    the config's own conversion, the curve of Lightricks' LTXVHDRDecodePostprocess, frame by frame into one array and with
    no tone-mapped copy; Save Frames writes them. The conditioning frame rate is at most 30, as there.

    The page gives it a shot at the working size, already a multiple of 32, or a plate with no edit, which is its own SDR
    shot: the slots color_space, width and height bring the plate into the model space at the working size, and
    plate_width and plate_height bring the HDR frames back to the plate's size, where HDR Match sets them to the plate's
    level as an edit's composite does, with an empty matte: nothing changed, so the whole plate's mid-tones decide. Save
    Frames and Save Movie keep Load Plate's frame count, so the 8n+1 padding that LTX needs stays out of the result.
    """
    g = Graph()
    load = g("PaintAPlate_LoadPlate", _title="Shot (SDR)", path=Slot("path", ""), max_frames=Slot("max_frames", 121), pad_8n1=True)
    # a plate with no edit: Colour Space (OCIO) from its file's colour space (Slot color_space) into the model space, then the
    # working size (Slots width and height). A shot is in the model space at the working size already: both pass it on as
    # it is, with no copy (source equal to destination, and 0 x 0 in core's Upscale Image)
    sdr = colour(g, load[0], Slot("color_space", "@model"), "@model", "SDR shot in the model space")
    sdr = g("ImageScale", _title="SDR shot at the working size", image=sdr, upscale_method="lanczos", width=Slot("width", 0),
            height=Slot("height", 0), crop="disabled")
    guide = g("ImageColorSpace", _title="Guide: the shot from sRGB to ACEScct", image=sdr, source="sRGB", destination="HDR ACEScct")
    size = g("GetImageSize", image=guide)
    lora = g("LTXICLoRALoaderModelOnly", _title="SDR-to-HDR IC-LoRA (reads its downscale factor)",
             model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"), lora_name=Slot("hdr_lora", HDR_LORA),
             strength_model=1.0)
    # the encode and the decode compute in float32 through core's VAE Compute Dtype, under dynamic VRAM too: on a 16 GB
    # budget, 121 frames at 1920 x 1088 come out the same, value for value, as with a VAE loaded in float32
    vae = g("VAEComputeDtype", _title="Video VAE, computed in float32", vae=g("VAELoader", vae_name=Slot("video_vae", LTX_VAE)), dtype="fp32")
    audio_vae = g("VAELoader", vae_name=LTX_AUDIO_VAE)
    scene = g("LTXVLoadConditioning", _title="Scene embeddings: the fixed prompt", file_name=Slot("hdr_scene", HDR_SCENE), device="cpu")
    cond = g("LTXVConditioning", positive=scene, negative=scene, frame_rate=Slot("cond_fps", 24.0))
    empty = g("EmptyLTXVLatentVideo", width=size[0], height=size[1], length=size[2], batch_size=1)
    guided = g("LTXAddVideoICLoRAGuide", positive=cond[0], negative=cond[1], vae=vae, latent=empty, image=guide, frame_idx=0,
               strength=1.0, latent_downscale_factor=lora[1], crop="disabled", use_tiled_encode=Slot("guide_tiled", False), tile_size=256,
               tile_overlap=64, use_streaming=False, tile_frames=97)
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=Slot("fps", 24), batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=42),
                guider=g("CFGGuider", model=live(g, lora, size, load, "ACEScct"), positive=guided[0], negative=guided[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler"), sigmas=g("ManualSigmas", sigmas=INPAINT_SIGMAS),
                latent_image=g("LTXVConcatAVLatent", video_latent=guided[2], audio_latent=audio))
    video = g("LTXVCropGuides", positive=guided[0], negative=guided[1], latent=g("LTXVSeparateAVLatent", av_latent=sampled[0])[0])
    # The whole frame in one piece by default (Slot tile, WHOLE): a tile larger than the frame takes core's single-tile path,
    # with no blend. Each 256 px or 512 px tile comes out brighter near its edges, and the blend of two tiles leaves a band
    # of 0.1 to 0.2 stops where they overlap. 121 frames at 1920 x 1088 in float32 decode whole in 13 s at a peak of 10.3 GiB,
    # against 45 to 99 s in tiles of 256 to 1024 px (RTX PRO 6000); the page sends 256 px tiles under 16 GB of VRAM only
    # (logic.WHOLE_FROM). VAE Decode (Tiled) has no retry after an out-of-memory error, so core's default tiles never take
    # over. 128-frame temporal tiles with 32 frames of overlap, as Lightricks' Tiled Fusion SDR-to-HDR graph: with the distilled
    # graph's 64 and 8, the HDR frames of a 121-frame fluid shot jump 0.32 stops at frame 56, where the second tile
    # starts; with 128 and 32 the largest step is 0.07 stops, the SDR shot's own (RTX PRO 6000).
    decoded = g("VAEDecodeTiled", samples=video[2], vae=vae, tile_size=Slot("tile", WHOLE), overlap=64, temporal_size=128, temporal_overlap=32)
    linear = colour(g, decoded, "ACEScct", "ACEScg", "ACEScct to ACEScg scene-linear")
    # where the SDR shot is black, its own black: the IC-LoRA's frames are noisy there (mathops.keep_black). Keep Black
    # converts each frame of the SDR shot as it uses it, so no converted copy of the shot waits through the sampling
    linear = g("PaintAPlate_KeepBlack", hdr=linear, sdr=sdr, config=Slot("config", OCIO_CONFIG), source="@model",
               low=0.001, high=0.01)
    # a plate with no edit: the HDR frames at its size (Slots plate_width and plate_height; bilinear, so no value overshoots
    # a highlight or falls below 0), set to its level by HDR Match as an edit's composite is, with nothing changed anywhere
    # (an empty matte): one gain per channel from the whole plate's mid-tones, in ACEScg. For a shot no plate size is
    # given, so the plate_level link goes with those three inputs, and HDR Match passes the frames on as they are: the
    # review fits a shot's HDR frames to the plate inside the composite.
    plate_size = g("GetImageSize", image=load[0])
    matched = g("PaintAPlate_HDRMatch", _title="HDR Match: the HDR frames at the plate's level", image=linear, grow=0.0,
                plate=colour(g, load[0], Slot("color_space", "@model"), "ACEScg", "Plate in ACEScg, for HDR Match"),
                mask=g("SolidMask", _title="Nothing changed: an empty matte", value=0.0, width=plate_size[0], height=plate_size[1]),
                hdr=g("ImageScale", _title="HDR frames at the plate's size", image=linear, upscale_method="bilinear",
                      width=Slot("plate_width", 0), height=Slot("plate_height", 0), crop="disabled"))
    for key in ("plate", "mask", "hdr"):
        g.link_slot(matched, key, "plate_level")
    linear = matched
    # each frame says the shot's frame rate, the one the page sends for the movie below, so a 16-bit fluid shot's frames
    # open as a plate at that rate
    g("PaintAPlate_SaveFrames", _title="HDR frames (half-float EXR, ACES2065-1)", _output="hdr", format="exr", fps=Slot("movie_fps", 24.0), chromaticities="AP0", frames=load[4],
      images=colour(g, linear, "ACEScg", HDR_SPACE, "ACEScg to ACES2065-1"), filename_prefix=Slot("prefix", "paintaplate/plate/hdr/f"))
    # the same frames as an 8-bit movie for the viewer, in log values (ACEScct, `view_space`): the look of the EXR frames
    g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="HDR movie (log values: the look of the EXR frames)", _output="movie", fps=Slot("movie_fps", 24.0),
      crf=12, frames=load[4], images=colour(g, linear, "ACEScg", Slot("view_space", "ACEScct"), "HDR movie values"),
      filename_prefix=Slot("video_prefix", "paintaplate/plate/hdr_movie"))
    g.save("hdr")


def hdr_comp():
    """« Composite, HDR »: the HDR set's composite, made again from its elements, as Upscale's is. The plate through SDR to
    HDR (Slot plate) around the export's matte (Slot matte: 16-bit PNG frames, never generated), the layer through SDR to HDR
    (Slot layer) inside it, through Composite Frames: comp = plate x (1 - matte) + layer x matte, in scene-linear values. The
    plate and the layer are half-float EXR frames in ACES2065-1 at the plate's size, each made by the hdr workflow on its
    element as on a plate with no edit, so each sits at its own SDR level, and the export's layer already matches the plate.

    It writes the set beside the layer, which SDR to HDR wrote there: the composite (Slot comp_prefix), the plate (Slot
    plate_prefix: SDR to HDR on the plate runs once per plate, and each render's set holds its copy) and the matte (Slot
    matte_prefix), so the set's own plate, layer and matte rebuild its composite. The viewer movie is in log values (ACEScct,
    Slot view_space): the look of the EXR frames, as SDR to HDR's own movie.
    """
    g = Graph()
    plate = g("PaintAPlate_LoadPlate", _title="Plate, HDR", path=Slot("plate", ""), max_frames=Slot("max_frames", 121), pad_8n1=False)
    layer = g("PaintAPlate_LoadPlate", _title="Layer, HDR", path=Slot("layer", ""), max_frames=Slot("max_frames", 121), pad_8n1=False)
    matte = g("PaintAPlate_LoadPlate", _title="Matte", path=Slot("matte", ""), max_frames=Slot("max_frames", 121), pad_8n1=False)
    size = g("GetImageSize", image=plate[0])
    comp = g("PaintAPlate_CompositeFrames", _title="Composite, HDR: the plate around the matte, the layer inside it", destination=plate[0],
             source=layer[0], mask=g("ImageToMask", image=matte[0], channel="red"), width=size[0], height=size[1])
    for title, output, images, fmt, prefix in (("Composite, HDR (half-float EXR, ACES2065-1)", "comp", comp, "exr", "comp_prefix"),
                                               ("Plate, HDR, in the set", "plate", plate[0], "exr", "plate_prefix"),
                                               ("Matte, in the set (16-bit PNG)", "matte", matte[0], "png16", "matte_prefix")):
        g("PaintAPlate_SaveFrames", _title=title, _output=output, images=images, frames=plate[4], format=fmt, fps=Slot("movie_fps", 24.0),
          **({"chromaticities": "AP0"} if fmt == "exr" else {}), filename_prefix=Slot(prefix, ""))
    g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Composite, HDR movie (log values: the look of the EXR frames)",
      _output="movie", fps=Slot("movie_fps", 24.0), crf=12, frames=plate[4], images=colour(g, comp, HDR_SPACE, Slot("view_space", "ACEScct"), "Composite, HDR movie values"),
      filename_prefix=Slot("video_prefix", ""))
    g.save("hdr_comp")


def upscale():
    """Upscale: one window of the result, frames `first` to `first + count - 1` (Slots first and count), made sharp
    at the size the page sends (Slots width and height) by SeedVR2 7B, with core's SeedVR2 nodes wired as core's blueprint
    wires them.

    SeedVR2 restores from at most half the target: a result larger than that first comes down to it (Slots source_width
    and source_height; 0 x 0 keeps the window's size). A plate already at the target's size is then restored at its own.

    The page sends the export (Slot shot), in the plate's colour space (Slot color_space), and as many frames per job as
    the machine's RAM holds: the whole shot where it can, else windows. 121 frames at 3840 x 2160 in one job reach 52 GB
    of RAM on a 96 GB GPU; on a 16 GB GPU the model's 15.7 GB stay in RAM as well, and a window of 42 frames goes past a
    52 GB cap. Each window saves into a folder of its own (Slot prefix). Windows share no frames: on a 96 GB GPU, the frames
    of windows of 21 frames change across a window's edge no more than within a window. The window goes into the model space with the whole shot's peak (peak_of), so
    an HDR shot keeps one exposure from one window to the next, and comes back with that peak.

    Lanczos brings the window to the target size. SeedVR2 restores it in one sampling step, in chunks of Slot chunk_frames
    frames (UPSCALE_CHUNK by default), two neighbouring chunks sharing Slot chunk_overlap latent frames (one by default),
    which core's merge crossfades; a chunk as long as the window is one pass. Core runs SeedVR2's MLP 8192 tokens at a time,
    so what bounds a pass is the sampler's activations, which grow with the latent frames and the pixels; core's automatic
    chunk size measures them on the 3B model, from the VRAM free before the model loads, so the caller chooses the chunk. The post-processing matches the colours to the Lanczos frames (Slot color_fix: lab, the node's default,
    or none). Save Frames writes the window: 16-bit PNG, or half-float EXR for a float plate (Slot format).

    Two optional parts make the upscaled set of an edit that keeps the plate's untouched pixels, where this window is the
    export's layer. The upscaled result (Slot comp_prefix): the same window of the upscaled plate (Slot under, saved by an earlier job
    of this workflow on the plate, in its colour space, Slot under_space) around the matte, the restored layer
    inside it, through Composite Frames. The matte (Slot matte, the export's, at the plate's size) is cut to the window
    and sized as Composite Frames sizes it, with a bilinear filter: never generated. The upscaled matte (Slot matte_prefix):
    that same picture as 16-bit PNG frames, so the upscaled result, plate, layer and matte add up to one code value. Every
    window saves its matte into one folder, numbered on from the frames already there.
    """
    g = Graph()
    load = g("PaintAPlate_LoadPlate", _title="Result", path=Slot("shot", ""), max_frames=Slot("max_frames", 121), pad_8n1=False)
    window = g("ImageFromBatch", _title="The window", image=load[0], batch_index=Slot("first", 0), length=Slot("count", UPSCALE_CHUNK))
    model = colour(g, window, Slot("color_space", "@model"), "@model", "The window in the model space", peak_of=load[0])
    source = g("ImageScale", _title="The window at the size SeedVR2 restores from", image=model, upscale_method="lanczos",
               width=Slot("source_width", 0), height=Slot("source_height", 0), crop="disabled")
    resized = g("ImageScale", _title="The window at the target size (Lanczos)", image=source, upscale_method="lanczos",
                width=Slot("width", 3840), height=Slot("height", 2160), crop="disabled")
    vae = g("VAELoader", vae_name=SEEDVR2_VAE)
    unet = g("UNETLoader", unet_name=SEEDVR2, weight_dtype="default")
    latent = g("VAEEncodeTiled", pixels=g("SeedVR2Preprocess", resized_images=resized), vae=vae, tile_size=512, overlap=128,
               temporal_size=64, temporal_overlap=8)
    chunks = g("SeedVR2TemporalChunk", latent=latent, temporal_overlap=Slot("chunk_overlap", 1), chunking_mode="manual",
               chunking_mode__frames_per_chunk=Slot("chunk_frames", UPSCALE_CHUNK))
    cond = g("SeedVR2Conditioning", model=unet, vae_conditioning=chunks[0])
    sampled = g("KSampler", _progress=True, model=unet, seed=Slot("seed", 42), steps=1, cfg=1.0, sampler_name="euler",
                scheduler="simple", positive=cond[0], negative=cond[1], latent_image=chunks[0], denoise=1.0)
    decoded = g("VAEDecodeTiled", samples=g("SeedVR2TemporalMerge", latents=sampled, temporal_overlap=chunks[1]), vae=vae,
                tile_size=512, overlap=128, temporal_size=64, temporal_overlap=8)
    sharp = g("SeedVR2PostProcessing", images=decoded, original_resized_images=resized, color_correction_method=Slot("color_fix", "lab"))
    back = colour(g, sharp, "@model", Slot("color_space", "@model"), "The window in the plate's colour space", peak=model[1])
    g("PaintAPlate_SaveFrames", _title="Upscaled frames", _output="frames", images=back, fps=load[3], format=Slot("format", "png16"),
      filename_prefix=Slot("prefix", "paintaplate/plate/upscale/f"))
    size = g("GetImageSize", image=back)
    matte = g("ImageFromBatch", _title="The window of the matte", batch_index=Slot("first", 0), length=Slot("count", UPSCALE_CHUNK),
              image=g("PaintAPlate_LoadPlate", _title="Matte", path=Slot("matte", ""), max_frames=Slot("max_frames", 121), pad_8n1=False))
    under = g("PaintAPlate_LoadPlate", _title="The window of the upscaled plate", path=Slot("under", ""), max_frames=Slot("count", UPSCALE_CHUNK), pad_8n1=False)
    under = colour(g, under, Slot("under_space", "@model"), Slot("color_space", "@model"), "The window of the upscaled plate in the layer's colour space")
    comp = g("PaintAPlate_CompositeFrames", _title="Upscaled result: the plate's window around the matte, the layer inside it", destination=under,
             source=back, mask=g("ImageToMask", image=matte, channel="red"), width=size[0], height=size[1])
    saved = g("PaintAPlate_SaveFrames", _title="Upscaled result frames", _output="comp", images=comp, fps=load[3], format=Slot("format", "png16"),
              filename_prefix=Slot("comp_prefix", ""))
    g.link_slot(saved, "images", "upscale_comp")
    big = g("ImageScale", _title="The matte at the target size (bilinear, as Composite Frames sizes it)", image=matte, upscale_method="bilinear",
            width=size[0], height=size[1], crop="disabled")
    saved = g("PaintAPlate_SaveFrames", _title="Upscaled matte", _output="matte", images=big, format="png16", filename_prefix=Slot("matte_prefix", ""))
    g.link_slot(saved, "images", "upscale_matte")
    g.save("upscale")


def upscale_export():
    """Upscale's export, after the last window. Join Windows reads the windows' folders under one parent folder
    (Slot frames), in order, each window its last frames (Slot count) and the last window what is left of the shot's
    frames (Slot max_frames), so a window job that runs again counts once; a shot made in one job is one window. Save Plate writes the joined frames at their own size, as it writes the export at the plate's size (Slot
    shot), which Load Plate reads for its spec: a sequence in its own file type and bit depth, a movie as ProRes 4444 XQ,
    with the frame numbers, colour tags, timecode and audio. The frames are in the plate's colour space already, so nothing converts them. Save Movie writes the part's viewer
    movie at its own size when the page names it (Slot video_prefix): its row in the Render panel plays it."""
    g = Graph()
    shot = g("PaintAPlate_LoadPlate", _title="Result: its format", path=Slot("shot", ""), max_frames=Slot("max_frames", 121), pad_8n1=False)
    frames = g("PaintAPlate_JoinWindows", _title="Upscaled windows, joined", folder=Slot("frames", ""),
               count=Slot("count", 0), max_frames=Slot("max_frames", 121), counts=Slot("counts", ""), share=Slot("share", 0))
    g("PaintAPlate_SavePlate", _title="Upscaled export", _output="export", images=frames, plate=shot[2],
      filename_prefix=Slot("prefix", "paintaplate/plate/upscaled"), keep_untouched=False)
    g("PaintAPlate_SaveMovie", width=Slot("movie_width", 0), height=Slot("movie_height", 0), _title="Viewer movie of the upscaled part, at its own size", _output="video",
      images=frames, frames=shot[4], config=Slot("config", OCIO_CONFIG), source=Slot("color_space", "@model"), destination=Slot("movie_space", "@model"),
      fps=shot[3], crf=12, filename_prefix=Slot("video_prefix", ""))
    g.save("upscale_export")


if __name__ == "__main__":
    for build in (ingest, prompt, edit, snap, clean, cleanup, shot, matte, comp, review, export, warm, fluid, hdr, hdr_comp, upscale, upscale_export):
        build()
    print("wrote", sorted(os.listdir(OUT)))
