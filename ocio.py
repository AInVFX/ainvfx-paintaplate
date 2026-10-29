"""OpenColorIO for the viewer and the workflows, as OpenRV uses it (src/plugins/rv-packages/ocio_source_setup).

The config is the file $OCIO names, as in RV, else OCIO's built-in studio config. A plate has one colour space in that
config, its file colour space. The viewer turns file values into the config's scene-linear space, applies its colour
tools there, then the display and view, with GLSL from OCIO's GPU processor run in WebGL2. The workflows turn the plate
into the model space, and the edited pixels back into the plate's colour space for the export.

The model space is the sRGB-encoded Rec.709 the models were trained on (FLUX 3 Image Klein, LTX 2.5, SAM 3.1). Into it,
values above 1.0 are tone-mapped as core ComfyUI's Convert Image Color Space maps them to sRGB: an extended Reinhard on
luminance with the batch's peak as white point, then the same gamut compression (comfy_extras/nodes_images.py at
v0.43.0). A plate's model inputs are the ones core made. Out of the model space, values are decoded as they are, as core
decodes sRGB.

Two names stand for spaces derived from the model space, so every config works: "@model", the model space entered through
that tone mapping, and "@linear", the model space decoded to linear light without clipping (Relight Transfer works in it).
Pure numpy and PyOpenColorIO: tests/test_ocio.py runs without torch or ComfyUI.
"""
from __future__ import annotations

import base64
import functools
import os
from concurrent.futures import ThreadPoolExecutor

import numpy as np
import PyOpenColorIO as OCIO

ENV = "$OCIO"  # the config name that means the file the OCIO environment variable names
BUILTIN = "ocio://studio-config-latest"  # ACES 2.1 with the camera log spaces (ARRI, Sony, RED, Canon, ...)
MODEL, LINEAR = "@model", "@linear"
WORKERS = min(16, os.cpu_count() or 4)  # frames in parallel: OCIO releases the GIL while it converts (measured 29 Oct)
_POOL = ThreadPoolExecutor(WORKERS)
# The model space's names and aliases in the ACES configs, then the roles that usually point at it
MODEL_NAMES = ("srgb_tx", "sRGB Encoded Rec.709 (sRGB)", "sRGB - Texture", "Utility - sRGB - Texture",
               "Input - Generic - sRGB - Texture", "srgb_texture", "texture_paint", "color_picking")
# What plateio guesses from a file (core ComfyUI's names), as names and aliases in the ACES configs
FAMILIAR = {
    "sRGB": MODEL_NAMES,
    "linear": ("lin_rec709_srgb", "Linear Rec.709 (sRGB)", "Utility - Linear - sRGB", "lin_srgb", "Linear Rec.709"),
    "linear ACEScg": ("ACEScg", "lin_ap1", "ACES - ACEScg"),
    "HDR ACEScct": ("ACEScct", "acescct_ap1", "ACES - ACEScct"),
    "HDR LogC3": ("ARRI LogC3 (EI800)", "arri_logc3_ei800", "Input - ARRI - V3 LogC (EI800) - Wide Gamut"),
    "HDR": ("Rec.2100-HLG - Display", "rec2100_hlg_display"),
    "HDR PQ": ("Rec.2100-PQ - Display", "rec2100_pq_display"),
}
# With a built-in config, this display and view show an SDR plate as a browser shows it; with $OCIO, the config decides
FAMILIAR_VIEW = ("sRGB - Display", "Un-tone-mapped")
REC709_LUMA = np.array([0.2126, 0.7152, 0.0722], np.float32)


# ---------- Configs ----------

def default_config() -> str:
    return ENV if os.environ.get("OCIO") else BUILTIN


def configs() -> list[dict]:
    """The configs the page may pick, as RV's Change Config offers them: $OCIO when it is set, then the built-in ones."""
    out = [{"name": ENV, "label": f"$OCIO: {os.path.basename(os.environ['OCIO'])}"}] if os.environ.get("OCIO") else []
    out += [{"name": BUILTIN, "label": "ACES studio config, latest (built in)"},
            {"name": "ocio://cg-config-latest", "label": "ACES CG config, latest (built in)"}]
    out += [{"name": f"ocio://{c[0]}", "label": c[1]} for c in OCIO.BuiltinConfigRegistry().getBuiltinConfigs()]
    return out


@functools.lru_cache(maxsize=8)
def config(name: str = "") -> OCIO.Config:
    """The config `name` stands for. Only $OCIO and the built-in configs: never a path the page sends."""
    name = name or default_config()
    if name == ENV:
        if not os.environ.get("OCIO"):
            raise ValueError("The OCIO environment variable is not set")
        return OCIO.Config.CreateFromFile(os.environ["OCIO"])
    if name not in {c["name"] for c in configs()}:
        raise ValueError(f"Unknown OCIO config: {name}")
    return OCIO.Config.CreateFromFile(name)


def find(cfg: OCIO.Config, names) -> str | None:
    """The canonical name of the first of `names` the config knows, as a name, an alias or a role."""
    for n in names:
        cs = cfg.getColorSpace(n)
        if cs is not None:
            return cs.getName()
    return None


def model_space(cfg: OCIO.Config) -> str:
    found = find(cfg, MODEL_NAMES)
    if not found:
        raise ValueError("This OCIO config has no sRGB-encoded Rec.709 space (role texture_paint): the models need it")
    return found


def real(cfg: OCIO.Config, name: str) -> str:
    """The config's own name for `name`, which may be an alias, a role, @model or @linear."""
    if name in (MODEL, LINEAR):
        return model_space(cfg)
    cs = cfg.getColorSpace(name)
    if cs is None:
        raise ValueError(f"The OCIO config has no colour space named {name!r}")
    return cs.getName()


def familiar_view(cfg: OCIO.Config, name: str) -> tuple[str, str]:
    display = cfg.getDefaultDisplay()
    view = cfg.getDefaultView(display)
    d, v = FAMILIAR_VIEW
    if (name or default_config()) != ENV and d in cfg.getDisplays() and v in cfg.getViews(d):
        display, view = d, v
    return display, view


@functools.lru_cache(maxsize=8)
def describe(name: str = "") -> dict:
    """What the OCIO menu lists: colour spaces with their family (RV's menu tree), displays with their views, looks."""
    cfg = config(name)
    display, view = familiar_view(cfg, name)
    spaces = [{"name": cs.getName(), "family": cs.getFamily(), "aliases": list(cs.getAliases()), "data": bool(cs.isData())}
              for cs in cfg.getColorSpaces()]
    return {"config": name or default_config(), "label": cfg.getName() or cfg.getDescription()[:80], "configs": configs(),
            "spaces": spaces, "displays": [{"name": d, "views": list(cfg.getViews(d))} for d in cfg.getDisplays()],
            "display": display, "view": view, "looks": [lk.getName() for lk in cfg.getLooks()], "model": model_space(cfg),
            "scene_linear": real(cfg, OCIO.ROLE_SCENE_LINEAR)}


def guess(name: str, familiar: str, path: str = "") -> str:
    """A plate's file colour space: what plateio read from the file (EXR chromaticities, video tags) in this config,
    else the config's file rules, else its scene-linear space for EXR and the model space for the rest."""
    cfg = config(name)
    found = find(cfg, FAMILIAR.get(familiar, ()))
    if found:
        return found
    if path:
        rule = cfg.getColorSpaceFromFilepath(path)
        rule = rule[0] if isinstance(rule, tuple) else rule
        if rule and cfg.getColorSpace(rule) is not None:
            return cfg.getColorSpace(rule).getName()
    return real(cfg, OCIO.ROLE_SCENE_LINEAR) if familiar.startswith("linear") else model_space(cfg)


# ---------- Converting pixels ----------

def decode(x: np.ndarray) -> np.ndarray:
    """sRGB to linear light as core decodes it, extended: the linear segment below the break, the power law above 1."""
    return np.where(x <= 0.04045, x / 12.92, np.power((np.maximum(x, 0.04045) + 0.055) / 1.055, 2.4)).astype(np.float32)


def encode(y: np.ndarray) -> np.ndarray:
    """The inverse of decode."""
    return np.where(y <= 0.0031308, y * 12.92, 1.055 * np.power(np.maximum(y, 0.0031308), 1 / 2.4) - 0.055).astype(np.float32)


@functools.lru_cache(maxsize=64)
def _cpu(name: str, src: str, dst: str):
    return config(name).getProcessor(src, dst).getDefaultCPUProcessor()


def _each(fn, frames):
    return list(_POOL.map(fn, frames))


def _rgb(fn):
    """fn on the RGB of a frame; an alpha channel stays as it is."""
    def one(f):
        rgb = fn(np.array(f[..., :3], np.float32, order="C"))
        return rgb if f.shape[-1] == 3 else np.concatenate([rgb, f[..., 3:]], -1)
    return one


def _ocio(name, src, dst, frames):
    if src == dst:
        return list(frames)
    cpu = _cpu(name, src, dst)

    def apply(rgb):
        cpu.applyRGB(rgb)
        return rgb
    return _each(_rgb(apply), frames)


def _into_model(frames):
    """Core's linear Rec.709 to sRGB for SDR output: tone mapping with the batch's peak, gamut compression, encoding."""
    peak = max(1.0, max((float(np.max(f[..., :3] @ REC709_LUMA, initial=0.0)) for f in frames), default=1.0))

    def one(rgb):
        if peak > 1.0001:  # core allows transfer-function roundoff at SDR white without tone mapping
            lum = np.maximum(rgb @ REC709_LUMA, 0.0)[..., None]
            rgb = rgb * ((1.0 + lum / (peak * peak)) / (1.0 + lum))
        lum = np.clip(rgb @ REC709_LUMA, 0.0, 1.0)[..., None]
        lo, hi = rgb.min(-1, keepdims=True), rgb.max(-1, keepdims=True)
        tiny = np.finfo(np.float32).tiny
        sat = np.clip(np.minimum((1.0 - lum) / np.maximum(hi - lum, tiny), lum / np.maximum(lum - lo, tiny)), 0.0, 1.0)
        inside = (lo >= -1e-5) & (hi <= 1.00001)
        rgb = np.clip(np.where(inside, rgb, lum + (rgb - lum) * sat), 0.0, 1.0)
        return encode(rgb)
    return _each(_rgb(one), frames)


def convert(frames, name: str, src: str, dst: str) -> list[np.ndarray]:
    """Each frame's RGB from `src` to `dst` in config `name`, frames in parallel; alpha untouched. Either may be @model or
    @linear. @linear is the config's Linear Rec.709 when it has one (a matrix from ACEScg, nothing clipped), else the model
    space decoded; into @model, frames pass through it, then core's tone mapping and gamut compression."""
    frames = list(frames)
    if src == dst or not frames:
        return frames
    cfg = config(name)
    lin = find(cfg, FAMILIAR["linear"])

    def where(n):  # (the config's name, whether the values are the model space decoded to linear light)
        if n == LINEAR:
            return (lin, False) if lin else (model_space(cfg), True)
        return real(cfg, n), False
    (rs, s_dec), (rd, d_dec) = where(src), where(dst)
    if s_dec:
        frames = _each(_rgb(encode), frames)
    if dst == MODEL and src != MODEL:
        return _into_model(_ocio(name, rs, lin, frames) if lin else _each(_rgb(decode), _ocio(name, rs, model_space(cfg), frames)))
    out = _ocio(name, rs, rd, frames)
    return _each(_rgb(decode), out) if d_dec else out


# ---------- The viewer's shader ----------

def _gpu(proc, function: str, prefix: str) -> dict:
    """GLSL ES 3.0 for WebGL2, with every lookup table as float32 in base64."""
    desc = OCIO.GpuShaderDesc.CreateShaderDesc(language=OCIO.GPU_LANGUAGE_GLSL_ES_3_0, functionName=function,
                                               resourcePrefix=prefix)
    proc.getDefaultGPUProcessor().extractGpuShaderInfo(desc)
    data = lambda t: base64.b64encode(np.asarray(t.getValues(), np.float32).tobytes()).decode()  # noqa: E731
    near = lambda t: str(t.interpolation).endswith("NEAREST")  # noqa: E731
    tables = [{"sampler": t.samplerName, "kind": "2d", "width": t.width, "height": t.height,
               "channels": 1 if str(t.channel).endswith("RED_CHANNEL") else 3, "nearest": near(t), "data": data(t)}
              for t in desc.getTextures()]
    tables += [{"sampler": t.samplerName, "kind": "3d", "size": t.edgeLen, "channels": 3, "nearest": near(t), "data": data(t)}
               for t in desc.get3DTextures()]
    if len(list(desc.getUniforms())):
        raise ValueError("This transform has dynamic properties, which the viewer does not set")
    return {"text": desc.getShaderText(), "function": function, "tables": tables}


def _identity(cfg, src: str, display: str, view: str) -> bool:
    """True when the whole chain leaves 8-bit values as they are, so the viewer may draw a video frame directly."""
    cpu = cfg.getProcessor(OCIO.DisplayViewTransform(src=src, display=display, view=view)).getDefaultCPUProcessor()
    g = np.linspace(0.0, 1.0, 17, dtype=np.float32)
    grid = np.stack(np.meshgrid(g, g, g, indexing="ij"), -1).reshape(-1, 3).copy()
    out = grid.copy()
    cpu.applyRGB(out)
    return float(np.abs(out - grid).max()) < 0.5 / 255


@functools.lru_cache(maxsize=32)
def shader(name: str, space: str, display: str, view: str, look: str = "") -> dict:
    """The viewer's two OCIO functions for a source in `space`, as OpenRV chains its OCIO nodes: ocioIn, the file values
    to scene-linear (OCIOFile), where the viewer's colour tools apply; then ocioOut, the look and the display and view
    (OCIOLook, OCIODisplay)."""
    cfg = config(name)
    src = real(cfg, space)
    if display not in cfg.getDisplays() or view not in cfg.getViews(display):
        raise ValueError(f"The OCIO config has no view {view!r} on display {display!r}")
    lin = OCIO.ROLE_SCENE_LINEAR
    out = OCIO.DisplayViewTransform(src=lin, display=display, view=view)
    if look:
        if cfg.getLook(look) is None:
            raise ValueError(f"The OCIO config has no look named {look!r}")
        out = OCIO.GroupTransform([OCIO.LookTransform(src=lin, dst=lin, looks=look), out])
    return {"in": _gpu(cfg.getProcessor(OCIO.ColorSpaceTransform(src=src, dst=lin)), "ocioIn", "ocio_in_"),
            "out": _gpu(cfg.getProcessor(out), "ocioOut", "ocio_out_"),
            "identity": not look and _identity(cfg, src, display, view)}


def display_rgb(rgb: np.ndarray, name: str, space: str) -> np.ndarray:
    """An image as the viewer shows it at its defaults, for thumbnails: through the familiar display and view."""
    cfg = config(name)
    display, view = familiar_view(cfg, name)
    out = np.array(rgb[..., :3], np.float32, order="C")
    cfg.getProcessor(OCIO.DisplayViewTransform(src=real(cfg, space), display=display, view=view)).getDefaultCPUProcessor().applyRGB(out)
    return np.clip(out, 0.0, 1.0)
