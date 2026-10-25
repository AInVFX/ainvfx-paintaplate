"""Write the five PaintAPlate workflows to web/workflows/*.json (API format).

Each file holds {"prompt": <API workflow>, "slots": {name: [[node_id, input], ...]}}.
The page fills the slots and posts the prompt to ComfyUI. Every node is a core
node, a ComfyUI-LTXVideo node or one of the four PaintAPlate nodes, so each
graph also opens as a normal workflow in ComfyUI.

    python tools/build_workflows.py
"""
import json
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "web", "workflows")

KLEIN = "flux3-image-klein-int8-convrot.safetensors"
LTX = "ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors"
GEMMA = "gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors"
RIPPLE_PROMPT = ("Use the reference video for motion, timing, camera movement, framing and lighting changes; "
                 "follow the edited first frame for every change of content, light and style.")
NEGATIVE = "blurry, low resolution, ugly, garbled mess, compression artifacts, glitch, flicker, still image"


class Slot:
    def __init__(self, name, default):
        self.name, self.default = name, default


class Graph:
    def __init__(self):
        self.prompt, self.slots = {}, {}

    def __call__(self, cls, **inputs):
        nid = str(len(self.prompt) + 1)
        node = {"class_type": cls, "inputs": {}}
        for key, value in inputs.items():
            key = key.replace("__", ".")  # images__image0 -> images.image0 (dynamic inputs)
            if isinstance(value, Slot):
                self.slots.setdefault(value.name, []).append([nid, key])
                value = value.default
            node["inputs"][key] = [value.nid, 0] if isinstance(value, Ref) else value
        self.prompt[nid] = node
        return Ref(nid)

    def save(self, name):
        os.makedirs(OUT, exist_ok=True)
        with open(os.path.join(OUT, f"{name}.json"), "w") as f:
            json.dump({"prompt": self.prompt, "slots": self.slots}, f, indent=1)


class Ref:
    def __init__(self, nid):
        self.nid = nid

    def __getitem__(self, i):
        return [self.nid, i]


def plate(g, pad, path="path"):
    """The plate as display-referred sRGB frames: Load Plate, then core colour conversion."""
    load = g("PaintAPlate_LoadPlate", path=Slot(path, ""), max_frames=Slot("max_frames", 121), pad_8n1=pad)
    srgb = g("ImageColorSpace", image=load[0], source=Slot("color_space", "sRGB"), destination="sRGB")
    return load, srgb


def ingest():
    """Hero frame at working size, a playback proxy and the plate spec."""
    g = Graph()
    load, srgb = plate(g, pad=True)  # same inputs as every other Load Plate of the plate: decoded once, then cached
    first = g("ImageFromBatch", image=srgb, batch_index=0, length=1)
    hero = g("ImageScaleToMaxDimension", image=first, upscale_method="lanczos", largest_size=1920)
    g("SaveImage", images=hero, filename_prefix=Slot("prefix", "paintaplate/plate/hero"))
    proxy = g("ImageScaleToMaxDimension", image=srgb, upscale_method="area", largest_size=960)
    video = g("CreateVideo", images=proxy, fps=load[3], bit_depth=8, color_space="sRGB", codec="none")
    g("SaveVideo", video=video, filename_prefix=Slot("video_prefix", "paintaplate/plate/proxy"),
      format="auto", format__codec="auto")
    g("PreviewAny", source=load[5])
    g.save("ingest")


def edit():
    """One FLUX 3 Image Klein edit inside a mask, composited back over the untouched frame."""
    g = Graph()
    model = g("UNETLoader", unet_name=Slot("klein", KLEIN), weight_dtype="default")
    clip = g("CLIPLoader", clip_name="qwen3vl_4b_int8_convrot.safetensors", type="flux3", device="default")
    vae = g("VAELoader", vae_name=Slot("vae", "flux2-vae.safetensors"))
    base = g("LoadImage", image=Slot("base", ""))
    reference = g("LoadImage", image=Slot("reference", ""))
    start = g("LoadImage", image=Slot("start", ""))
    mask = g("LoadImageMask", image=Slot("mask", ""), channel="red")
    positive = g("CLIPTextEncode", text=Slot("caption", ""), clip=clip)
    negative = g("ConditioningZeroOut", conditioning=positive)
    ref = g("ReferenceMultiLatent", positive=positive, negative=negative, vae=vae,
            resolution="keep resolution", images__image0=reference)
    grown = g("GrowMask", mask=mask, expand=Slot("grow", 16), tapered_corners=True)
    latent = g("SetLatentNoiseMask", samples=g("VAEEncode", pixels=start, vae=vae), mask=grown)
    sampled = g("KSampler", model=model, seed=Slot("seed", 0), steps=Slot("steps", 8), cfg=1.0,
                sampler_name="euler", scheduler="simple", positive=ref[0], negative=ref[1],
                latent_image=latent, denoise=Slot("denoise", 1.0))
    decoded = g("VAEDecode", samples=sampled, vae=vae)
    soft = g("ImageToMask", channel="red", image=g("ImageBlur", image=g("MaskToImage", mask=grown),
                                                    blur_radius=Slot("feather", 12), sigma=Slot("sigma", 6.0)))
    result = g("ImageCompositeMasked", destination=base, source=decoded, x=0, y=0, resize_source=False, mask=soft)
    g("PreviewImage", images=result)
    g.save("edit")


def shot():
    """LTX 2.5 with the Ripple IC-LoRA: the edited first frame carries through the whole shot."""
    g = Graph()
    load, srgb = plate(g, pad=True)
    frames = g("ImageScale", image=srgb, upscale_method="lanczos", width=Slot("width", 960),
               height=Slot("height", 544), crop="disabled")
    size = g("GetImageSize", image=frames)
    hero = g("ImageScale", image=g("LoadImage", image=Slot("hero", "")), upscale_method="lanczos",
             width=size[0], height=size[1], crop="disabled")
    rest = g("ImageFromBatch", image=frames, batch_index=1, length=4096)
    reference = g("BatchImagesNode", images__image0=hero, images__image1=rest)  # frame 0 replaced
    model = g("LoraLoaderModelOnly", model=g("UNETLoader", unet_name=Slot("ltx", LTX), weight_dtype="default"),
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
    sampled = g("SamplerCustomAdvanced", noise=g("RandomNoise", noise_seed=Slot("seed", 0)),
                guider=g("CFGGuider", model=model, positive=guide[0], negative=guide[1], cfg=1.0),
                sampler=g("KSamplerSelect", sampler_name="euler"),
                sigmas=g("BasicScheduler", model=model, scheduler="simple", steps=Slot("steps", 8), denoise=1.0),
                latent_image=g("LTXVConcatAVLatent", video_latent=guide[2], audio_latent=audio))
    video_latent = g("LTXVSeparateAVLatent", av_latent=sampled[0])
    cropped = g("LTXVCropGuides", positive=guide[0], negative=guide[1], latent=video_latent[0])
    decoded = g("VAEDecode", samples=cropped[2], vae=vae)
    g("SaveImage", images=decoded, filename_prefix=Slot("prefix", "paintaplate/plate/shot/f"))
    video = g("CreateVideo", images=decoded, fps=load[3], bit_depth=8, color_space="sRGB", codec="none")
    g("SaveVideo", video=video, filename_prefix=Slot("video_prefix", "paintaplate/plate/shot"),
      format="auto", format__codec="auto")
    g.save("shot")


def matte():
    """SAM 3.1 follows a painted area through the shot, from the first frame."""
    g = Graph()
    _, srgb = plate(g, pad=True)
    frames = g("ImageScale", image=srgb, upscale_method="area", width=Slot("width", 960),
               height=Slot("height", 544), crop="disabled")
    sam = g("CheckpointLoaderSimple", ckpt_name=Slot("sam", "sam3.1_multiplex_fp16.safetensors"))
    track = g("SAM3_VideoTrack", images=frames, model=sam, initial_mask=g("LoadImageMask", image=Slot("mask", ""),
                                                                         channel="red"),
              detection_threshold=0.5, max_objects=4, detect_interval=1)
    masks = g("SAM3_TrackToMask", track_data=track, object_indices="")
    g("SaveImage", images=g("MaskToImage", mask=masks), filename_prefix=Slot("prefix", "paintaplate/plate/matte/m"))
    g.save("matte")


def export():
    """Full quality: the shot fitted onto the plate, relight optional, saved in the plate's format."""
    g = Graph()
    load = g("PaintAPlate_LoadPlate", path=Slot("path", ""), max_frames=Slot("max_frames", 121), pad_8n1=True)
    gen = g("PaintAPlate_LoadPlate", path=Slot("shot", ""), max_frames=1024, pad_8n1=False)
    erase = g("PaintAPlate_LoadPlate", path=Slot("matte_a", ""), max_frames=1024, pad_8n1=False)
    add = g("PaintAPlate_LoadPlate", path=Slot("matte_b", ""), max_frames=1024, pad_8n1=False)
    union = g("MaskComposite", destination=g("ImageToMask", image=erase, channel="red"),
              source=g("ImageToMask", image=add, channel="red"), x=0, y=0, operation="add")
    gen_plate = g("ImageColorSpace", image=gen, source="sRGB", destination=Slot("color_space", "sRGB"))
    fit = g("PaintAPlate_FitToPlate", plate=load, image=gen_plate, mask=union, align=True, max_shift=8.0,
            match_color=True, grain=Slot("grain", 1.0), grow=Slot("grow", 8), feather=Slot("feather", 12))
    g.slots["fit_mask"] = [[fit.nid, "mask"]]  # the page drops this link when there is no matte
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
    final = g("ImageCompositeMasked", destination=base, source=fit[0], x=0, y=0, resize_source=False, mask=fit[1])
    g("PaintAPlate_SavePlate", images=final, plate=load[2], filename_prefix=Slot("prefix", "paintaplate/plate/export"),
      keep_untouched=Slot("keep_untouched", True), changed=fit[1])
    g.save("export")


if __name__ == "__main__":
    for build in (ingest, edit, shot, matte, export):
        build()
    print("wrote", sorted(os.listdir(OUT)))
