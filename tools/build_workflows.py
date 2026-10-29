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
NAMES = ("ingest", "prompt", "edit", "snap", "clean", "cleanup", "shot", "matte", "comp", "review", "export", "warm", "fluid", "hdr")
OCIO_CONFIG = "ocio://studio-config-latest"  # the page fills the config in use: $OCIO when it is set, as in RV

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
HDR_LORA = "ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors"  # Lightricks' SDR-to-HDR IC-LoRA (models/loras, gated)
HDR_SCENE = "ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors"  # its fixed scene embeddings: the prompt it takes (models/embeddings)
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
# no words for an erase: no search by name; not a relight: no light transfer on the edited frame;
# an erase matte: no plate under a shot to compare with, and no changed pixels to start from; a video plate's review:
# no EXR frames, its movie is the plate's own quality; no SDR-to-HDR shot: the SDR shot goes on as it is.
OPTIONAL = {"fit_mask": ("matte_a", "matte_b"), "named": ("words",), "relit_frame": ("relight",), "follow_base": ("base",),
            "follow_element": ("seed",), "review_frames": ("frames_prefix",), "hdr_shot": ("hdr",)}


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


def colour(g, image, source, destination, title=None):
    """Color Space (OCIO) in the config the page names (Slot config)."""
    return g("PaintAPlate_ColorSpace", _title=title, image=image, config=Slot("config", OCIO_CONFIG), source=source,
             destination=destination)


def plate(g, pad, path="path", progress=False):
    """The plate in the model space: Load Plate, then Color Space (OCIO) from the plate's file colour space to @model.

    Every workflow converts the same whole plate: the tone mapping of values above 1.0 shares one peak per batch, as
    core's did, so a different batch could change the exposure of an HDR plate between steps.
    """
    load = g("PaintAPlate_LoadPlate", _title="Plate", _progress=progress, path=Slot(path, ""),
             max_frames=Slot("max_frames", 121), pad_8n1=pad)
    return load, colour(g, load[0], Slot("color_space", "@model"), "@model", "Plate in the model space")


def ingest():
    """The first frame at working size in the model space, a playback proxy of the real frames, and the plate spec.

    The proxy keeps a video plate's own values, which the viewer converts with OCIO as it does the plate (the page sets
    `proxy_space` to the plate's colour space and `proxy_size` to the working size). An image sequence's proxy is in the
    model space, at 960: the viewer reads its frames at full precision as they arrive.
    """
    g = Graph()
    load, model = plate(g, pad=True, progress=True)  # same inputs as every other Load Plate: decoded once, then cached
    first = g("ImageFromBatch", image=model, batch_index=0, length=1)
    hero = g("ImageScaleToMaxDimension", image=first, upscale_method="lanczos", largest_size=1920)
    g("SaveImage", _title="First frame", _output="hero", images=hero,
      filename_prefix=Slot("prefix", "paintaplate/plate/hero"))
    real = g("ImageFromBatch", _title="Real frames (no padding)", image=load[0], batch_index=0, length=load[4])
    shown = colour(g, real, Slot("color_space", "@model"), Slot("proxy_space", "@model"), "Proxy values")
    proxy = g("ImageScaleToMaxDimension", image=shown, upscale_method="area", largest_size=Slot("proxy_size", 960))
    g("PaintAPlate_SaveMovie", _title="Playback proxy", _output="proxy", filename_prefix=Slot("video_prefix", "paintaplate/plate/proxy"),
      images=proxy, fps=load[3], crf=12)
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
    relit = g("PaintAPlate_RelightTransfer", plate=base, source=half(g, base), relit=half(g, result), radius=8,
              strength=Slot("relight", 0.0), align=True, plate_space="sRGB", shot_space="sRGB")
    g.link_slot(relit, "plate", "relit_frame")
    g("SaveImage", _title="Relit frame", _output="relit", images=relit, filename_prefix=Slot("prefix", EDIT_PREFIX))
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


def live(g, model, size, load, transfer="sRGB"):
    """The page's live preview while LTX samples: off (0 steps) unless the page sets `live`."""
    return g("PaintAPlate_LivePreview", _title="Live preview", model=model, decoder=Slot("tiny", TINY), frames=size[2], fps=load[3], **({"transfer": transfer} if transfer != "sRGB" else {}),
             every=Slot("live", 0), size=320)


def erased_blocks(g, matte, size):
    """The erase matte as blocks of LTX's 32 px grid, grown by one block: (the blocks at `size`, the grid of blocks).

    Blocks hide the object's outline: shown its own outline moving, LTX drew a car back where the van had been. They keep the
    background around the object in view, so LTX continues it. One grown box per frame also hid the outline, but around a
    truss, a crane and a door it covered the whole backdrop, and LTX animated a faint fill there into smoke (28 Oct).
    """
    cells = g("GrowMask", _title="One block more on every side", expand=Slot("grid_grow", 1), tapered_corners=False,
              mask=g("ThresholdMask", _title="Every block the matte touches", value=0.02,
                     mask=g("ImageToMask", channel="red", image=g("ImageScaleBy", _title="Erase matte on LTX's 32 px grid", image=matte,
                                                                upscale_method="area", scale_by=1 / 32))))
    grid = g("MaskToImage", mask=cells)
    blocks = g("ImageToMask", channel="red", image=g("ImageScale", image=grid, upscale_method="nearest-exact", width=size[0],
                                                     height=size[1], crop="disabled"))
    return blocks, grid


def clean():
    """The erase pass: LTX 2.5 with Lightricks' in-outpainting IC-LoRA regenerates every erased area of the shot.

    The reference is the plate with each erased area painted the green the LoRA was trained on, as blocks of LTX's grid
    (`erased_blocks`). The erased first frame starts the shot at strength 0.7 (the official workflow's start image). The
    prompt describes the scene as it stays, in the prompt writer's own words for what it kept (`erasePrompt` on the page);
    it never names the erased object: named, an object came back. At full size this pass is the first stage, at half the
    working size, and `cleanup` the second.
    """
    g = Graph()
    load, model = plate(g, pad=True)
    frames = g("ImageScale", image=model, upscale_method="lanczos", width=Slot("width", 960), height=Slot("height", 544), crop="disabled")
    size = g("GetImageSize", image=frames)
    matte = g("ImageScale", image=g("PaintAPlate_LoadPlate", _title="Erase matte", path=Slot("hole", ""), max_frames=1024, pad_8n1=False),
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
    g("PaintAPlate_SaveFrames", _title="Clean frames", _output="frames", images=decoded, filename_prefix=Slot("prefix", "paintaplate/plate/clean/f"))
    g("PaintAPlate_SaveMovie", _title="Clean shot (erased areas regenerated)", _output="video", filename_prefix=Slot("video_prefix", "paintaplate/plate/clean"), images=decoded, fps=load[3])
    g.save("clean")


def cleanup():
    """The erase pass at full size: the high-resolution stage of Lightricks' two-stage LTX 2.5 inpainting workflow.

    The first stage is the erase pass at half the working size (`clean`). Its frames, enlarged, go inside the erased blocks
    over the plate at full size, and LTX refines them in 2 steps from sigma 0.725, with the IC-LoRA and without the reference
    video, as the official workflow does. The erased first frame is kept as it is (strength 1). 8 steps at full size took
    181 s on a 1080p plate, this stage 82.8 s, 30.1 s of it saving the frames (28 Oct).
    """
    g = Graph()
    load, model = plate(g, pad=True)
    frames = g("ImageScale", _title="Plate at full size", image=model, upscale_method="bilinear", width=Slot("width", 1920),
               height=Slot("height", 1088), crop="disabled")
    size = g("GetImageSize", image=frames)
    matte = g("ImageScale", image=g("PaintAPlate_LoadPlate", _title="Erase matte", path=Slot("hole", ""), max_frames=1024, pad_8n1=False),
              upscale_method="area", width=size[0], height=size[1], crop="disabled")
    _, grid = erased_blocks(g, matte, size)
    soft = g("ImageToMask", channel="red", image=g("ImageScale", _title="The blocks with a soft edge", image=grid, upscale_method="bilinear",
                                                   width=size[0], height=size[1], crop="disabled"))
    low = g("ImageScale", _title="Stage 1 at full size", upscale_method="bilinear", width=size[0], height=size[1], crop="disabled",
            image=g("PaintAPlate_LoadPlate", _title="Erase pass at half size", path=Slot("low", ""), max_frames=1024, pad_8n1=False))
    start = g("ImageCompositeMasked", _title="Stage 1 inside the blocks, the plate around them", destination=frames, source=low, x=0, y=0,
              resize_source=False, mask=soft)
    model = g("LoraLoaderModelOnly", _title="In-outpainting IC-LoRA", model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"),
              lora_name=Slot("inoutpaint", INOUTPAINT), strength_model=1.0)
    clip = g("CLIPLoader", clip_name=Slot("gemma", GEMMA), type="ltxv", device="default")
    vae = g("VAELoader", vae_name=Slot("video_vae", LTX_VAE))
    audio_vae = g("VAELoader", vae_name=LTX_AUDIO_VAE)
    cond = g("LTXVConditioning", positive=g("CLIPTextEncode", _title="The scene as it stays", text=Slot("prompt", ""), clip=clip),
             negative=g("CLIPTextEncode", text=NEGATIVE, clip=clip), frame_rate=load[3])
    first = g("ImageScale", image=g("LoadImage", _title="Erased first frame", image=Slot("hero", "")), upscale_method="lanczos",
              width=size[0], height=size[1], crop="disabled")
    latent = g("LTXVImgToVideoInplace", vae=vae, image=first, strength=1.0, bypass=False,
               latent=g("VAEEncodeTiled", pixels=start, vae=vae, tile_size=512, overlap=64, temporal_size=500, temporal_overlap=64))
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=load[3], batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=Slot("seed", 0)),
                guider=g("CFGGuider", model=live(g, model, size, load), positive=cond[0], negative=cond[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler"), sigmas=g("ManualSigmas", sigmas=REFINE_SIGMAS),
                latent_image=g("LTXVConcatAVLatent", video_latent=latent, audio_latent=audio))
    decoded = g("VAEDecode", vae=vae, samples=g("LTXVSeparateAVLatent", av_latent=sampled[0])[0])
    g("PaintAPlate_SaveFrames", _title="Clean frames", _output="frames", images=decoded, filename_prefix=Slot("prefix", "paintaplate/plate/full/clean/f"))
    g("PaintAPlate_SaveMovie", _title="Clean shot at full size", _output="video", filename_prefix=Slot("video_prefix", "paintaplate/plate/full/clean"), images=decoded, fps=load[3])
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
    g("PaintAPlate_SaveFrames", _title="Shot frames", _output="frames", images=decoded,
      filename_prefix=Slot("prefix", "paintaplate/plate/shot/f"))
    g("PaintAPlate_SaveMovie", _title="Shot video (whole frame regenerated)", _output="video", filename_prefix=Slot("video_prefix", "paintaplate/plate/shot"), images=decoded, fps=load[3])
    g.save("shot")


def matte():
    """SAM 3.1 follows a painted or erased area through the frames from the first frame, then Follow Matte makes the
    track safe: one matte per frame even when SAM returns none, the last matte where SAM loses the object, and for
    paint every pixel the shot changed near the matte, compared with the plate the shot was made over (`base`)."""
    g = Graph()
    _, model = plate(g, pad=True)
    frames = g("ImageScale", image=model, upscale_method="area", width=Slot("width", 960),
               height=Slot("height", 544), crop="disabled")
    sam = g("CheckpointLoaderSimple", ckpt_name=Slot("sam", SAM))
    first = g("LoadImageMask", _title="Area on the first frame", image=Slot("mask", ""), channel="red")
    track = g("SAM3_VideoTrack", _progress=True, images=frames, model=sam, initial_mask=first,
              detection_threshold=0.5, max_objects=4, detect_interval=1)
    masks = g("SAM3_TrackToMask", track_data=track, object_indices="")
    under = g("PaintAPlate_LoadPlate", _title="Plate under the shot", path=Slot("base", ""), max_frames=Slot("max_frames", 121),
              pad_8n1=True)
    under = g("ImageScale", image=colour(g, under, Slot("base_color_space", "@model"), "@model"),
              upscale_method="area", width=Slot("width", 960), height=Slot("height", 544), crop="disabled")
    element = g("LoadImageMask", _title="Where the edit changed the first frame", image=Slot("seed", ""), channel="red")
    follow = g("PaintAPlate_FollowMatte", masks=masks, first=first, frames=frames, base=under, element=element,
               zone=Slot("zone", 0.0625), threshold=Slot("threshold", 0.1))
    g.link_slot(follow, "base", "follow_base")  # dropped for an erase matte: no shot to compare
    g.link_slot(follow, "element", "follow_element")  # dropped for an erase matte: the object is the first-frame mask
    g("PaintAPlate_SaveFrames", _title="Matte frames", _output="frames", images=g("MaskToImage", mask=follow[0]),
      filename_prefix=Slot("prefix", "paintaplate/plate/matte/m"))
    g("PreviewAny", _title="How the matte followed", _output="follow", source=follow[1])
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
    load, model = plate(g, pad=True)
    small = g("ImageScale", image=model, upscale_method="area", width=Slot("width", 960), height=Slot("height", 544),
              crop="disabled")
    gen = g("PaintAPlate_LoadPlate", _title="Generated shot", path=Slot("shot", ""), max_frames=1024, pad_8n1=False)
    union = mattes(g)
    relit = g("PaintAPlate_RelightTransfer", plate=small, source=half(g, small), relit=half(g, gen),
              plate_space="sRGB", shot_space="sRGB", radius=Slot("radius", 4), strength=Slot("strength", 1.0), align=True)
    base = g("ComfySwitchNode", switch=Slot("relight", False), on_false=small, on_true=relit)
    _, final = fitted(g, base, gen, union)
    real = g("ImageFromBatch", image=final, batch_index=0, length=load[4])
    g("PaintAPlate_SaveMovie", _title="Composite preview", _output="video", filename_prefix=Slot("video_prefix", "paintaplate/plate/comp"), images=real, fps=load[3])
    g.save("comp")


def composite(g):
    """The full-size composite in the plate's own colour space, which review and export share: the shot fitted onto the
    plate, relit when the light changed, and everywhere else the plate's own pixels."""
    load, model = plate(g, pad=True)
    gen = g("PaintAPlate_LoadPlate", _title="Generated shot", path=Slot("shot", ""), max_frames=1024, pad_8n1=False)
    union = mattes(g)
    gen_plate = colour(g, gen, "@model", Slot("color_space", "@model"), "Shot in the plate's colour space")
    # Relight: the light from the regenerated shot, the detail from the plate, in linear light. The plate as the model saw
    # it is the conversion every workflow makes, so ComfyUI has it cached.
    size = g("GetImageSize", image=gen)
    source = g("ImageScale", image=model, upscale_method="area", width=size[0], height=size[1], crop="disabled")
    relit = g("PaintAPlate_RelightTransfer", plate=colour(g, load[0], Slot("color_space", "@model"), "@linear"),
              source=half(g, source), relit=half(g, gen), plate_space="linear", shot_space="sRGB",
              radius=Slot("radius", 8), strength=Slot("strength", 1.0), align=True)
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
    fit, final = fitted(g, base, shot, union)
    return load, fit, final


def review():
    """What the viewer plays once the shot is made, at the plate's quality: the full-size composite as a movie (a video
    plate's own values, an image sequence in the model space) and, for an image sequence, as half-float EXR frames in the
    plate's own colour space, which the viewer reads at full precision. It runs right after the full-size passes;
    nothing here is written for compositing software (that is export, when Export is pressed)."""
    g = Graph()
    load, _, final = composite(g)
    real = g("ImageFromBatch", image=final, batch_index=0, length=load[4])
    movie = g("ImageScaleToMaxDimension", upscale_method="lanczos", largest_size=1920,
              image=colour(g, real, Slot("color_space", "@model"), Slot("movie_space", "@model"), "Movie values"))
    g("PaintAPlate_SaveMovie", _title="Review movie (full quality, H.264)", _output="review", images=movie, fps=load[3], crf=12,
      filename_prefix=Slot("review_prefix", "paintaplate/plate/review"))
    frames = g("PaintAPlate_SaveFrames", _title="Review frames (half-float EXR, image sequences only)", _output="frames",
               images=real, format="exr", filename_prefix=Slot("frames_prefix", ""))
    g.link_slot(frames, "images", "review_frames")  # dropped for a video plate
    g.save("review")


def export():
    """For compositing software, when Export is pressed: the composite the review shows, written by Save Plate in the
    plate's own format (file type, bit depth, frame numbers, colour tags, timecode, audio, EXR layers, the untouched
    pixels exactly the source's), with the matte of where the plate changed."""
    g = Graph()
    load, fit, final = composite(g)
    g("PaintAPlate_SavePlate", _title="Export", _output="export", images=final, plate=load[2],
      filename_prefix=Slot("prefix", "paintaplate/plate/export"), keep_untouched=Slot("keep_untouched", True),
      changed=fit[1])
    matte_frames = g("ImageFromBatch", image=g("MaskToImage", mask=fit[1]), batch_index=0, length=load[4])
    g("PaintAPlate_SaveFrames", _title="Matte: where the plate changed", _output="matte", images=matte_frames,
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
    load, model = plate(g, pad=True)
    size = g("GetImageSize", image=model)
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



def hdr():
    """SDR to HDR: a full-size shot made again in scene-linear values by Lightricks' LTX 2.5 SDR-to-HDR IC-LoRA, saved as
    half-float EXR frames in ACES2065-1 (HDR_SPACE).

    As Lightricks' official workflow (example_workflows/2.5/HDR_workflows/LTX-2.5_ICLoRA_SDR_to_HDR_Distilled.json in the
    pinned ComfyUI-LTXVideo): core Convert Image Color Space maps the shot from sRGB to ACEScct, the IC-LoRA's guide (not the
    creative SDR-to-HDR expand); fixed scene embeddings stand for the prompt, positive and negative, at CFG 1; the 8 distilled
    sigmas with euler; the video VAE in float32 encodes the guide and decodes the result, tiled; LTXVHDRDecodePostprocess
    returns ACEScg scene-linear values (its own EXR writer stays off: Save Frames writes them). The conditioning frame rate is
    at most 30, as there. The page gives it shots at the working size, already a multiple of 32.
    """
    g = Graph()
    load = g("PaintAPlate_LoadPlate", _title="Shot (SDR)", path=Slot("path", ""), max_frames=Slot("max_frames", 121), pad_8n1=True)
    guide = g("ImageColorSpace", _title="Guide: the shot from sRGB to ACEScct", image=load[0], source="sRGB", destination="HDR ACEScct")
    size = g("GetImageSize", image=guide)
    lora = g("LTXICLoRALoaderModelOnly", _title="SDR-to-HDR IC-LoRA (reads its downscale factor)",
             model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"), lora_name=Slot("hdr_lora", HDR_LORA),
             strength_model=1.0)
    vae = g("LTXVVAEForceFloat32", _title="Video VAE in float32", vae=g("VAELoader", vae_name=Slot("video_vae", LTX_VAE)))
    audio_vae = g("VAELoader", vae_name=LTX_AUDIO_VAE)
    scene = g("LTXVLoadConditioning", _title="Scene embeddings: the fixed prompt", file_name=Slot("hdr_scene", HDR_SCENE), device="cpu")
    cond = g("LTXVConditioning", positive=scene, negative=scene, frame_rate=Slot("cond_fps", 24.0))
    empty = g("EmptyLTXVLatentVideo", width=size[0], height=size[1], length=size[2], batch_size=1)
    guided = g("LTXAddVideoICLoRAGuide", positive=cond[0], negative=cond[1], vae=vae, latent=empty, image=guide, frame_idx=0,
               strength=1.0, latent_downscale_factor=lora[1], crop="disabled", use_tiled_encode=False, tile_size=256,
               tile_overlap=64, use_streaming=False, tile_frames=97)
    audio = g("LTXVEmptyLatentAudio", audio_vae=audio_vae, frames_number=size[2], frame_rate=Slot("fps", 24), batch_size=1)
    sampled = g("SamplerCustomAdvanced", _progress=True, noise=g("RandomNoise", noise_seed=42),
                guider=g("CFGGuider", model=live(g, lora, size, load, "ACEScct"), positive=guided[0], negative=guided[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler"), sigmas=g("ManualSigmas", sigmas=INPAINT_SIGMAS),
                latent_image=g("LTXVConcatAVLatent", video_latent=guided[2], audio_latent=audio))
    video = g("LTXVCropGuides", positive=guided[0], negative=guided[1], latent=g("LTXVSeparateAVLatent", av_latent=sampled[0])[0])
    decoded = g("VAEDecodeTiled", samples=video[2], vae=vae, tile_size=512, overlap=64, temporal_size=64, temporal_overlap=8)
    linear = g("LTXVHDRDecodePostprocess", _title="ACEScct to ACEScg scene-linear", image=decoded, transfer="acescct", exposure=0.0,
               save_exr=False, exr_color_space="acescg", output_dir="paintaplate/hdr_unused", filename_prefix="frame",
               half_precision=True)
    g("PaintAPlate_SaveFrames", _title="HDR frames (half-float EXR, ACES2065-1)", _output="hdr", format="exr",
      images=colour(g, linear[1], "ACEScg", HDR_SPACE, "ACEScg to ACES2065-1"), filename_prefix=Slot("prefix", "paintaplate/plate/hdr/f"))
    g.save("hdr")

if __name__ == "__main__":
    for build in (ingest, prompt, edit, snap, clean, cleanup, shot, matte, comp, review, export, warm, fluid, hdr):
        build()
    print("wrote", sorted(os.listdir(OUT)))
