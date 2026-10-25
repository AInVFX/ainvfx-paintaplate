# AInVFX PaintAPlate

Paint on the first frame of a shot to erase, add or relight. Two options appear while you paint. Pick one, and the whole shot comes back in the plate's own format: same file type, bit depth, frame numbers, colour space, layers, timecode and audio. Pixels you did not touch stay identical to the input.

PaintAPlate runs inside ComfyUI. The app is one page served by ComfyUI itself, and every step is an ordinary workflow you can open, read and change.

Built for Comfy's Open Source Higgsfield challenge, October 2026.

## Install

1. ComfyUI **0.42.5 or newer**. ACEScg plates need a ComfyUI build after 0.42.5 (the ACEScg colour space landed on 23 October 2026); older builds offer linear Rec.709 instead.
2. Install this pack from the Registry (ComfyUI-Manager, search "PaintAPlate"), or clone it into `ComfyUI/custom_nodes/` and run `pip install -r requirements.txt`.
3. Install **ComfyUI-LTXVideo** (Lightricks) for the LTX IC-LoRA guide node.
4. Download the models below, then restart ComfyUI.
5. Open the app from **Extensions > Open PaintAPlate**, or at `http://127.0.0.1:8188/extensions/ainvfx-paintaplate/paintaplate.html`.

Start ComfyUI with live previews on: `--preview-method latent2rgb`. On a 96 GB card, add `--highvram` so every model stays loaded between runs.

### Models

| Folder | File | Source | Licence |
| --- | --- | --- | --- |
| `diffusion_models` | `flux3-image-klein-int8-convrot.safetensors` (5.8 GB) | `black-forest-labs/flux-3-image-klein-comfy` | FLUX Kommunity |
| `text_encoders` | `qwen3vl_4b_int8_convrot.safetensors` (4.9 GB) | same repo | FLUX Kommunity |
| `vae` | `flux2-vae.safetensors` | same repo, `vae/` | FLUX Kommunity |
| `diffusion_models` | `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` (21.5 GB) | `Lightricks/LTX-2.5` | LTX-2 Community |
| `text_encoders` | `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` (15.4 GB) | `Lightricks/LTX-2.5` | LTX-2 Community |
| `vae` | `ltx-2.5-video-vae-conv-bf16.safetensors`, `ltx-2.5-audio-vae-bf16.safetensors` | `Lightricks/LTX-2.5` | LTX-2 Community |
| `loras` | `LTX25_Ripple_v11.safetensors` | `WepeNerd/LTX-Ripple` | LTX-2 Community |
| `checkpoints` | `sam3.1_multiplex_fp16.safetensors` | `Comfy-Org/sam3.1` (the file of the official SAM 3 template) | SAM License |

All models are open weights. The FLUX, LTX and SAM repositories ask you to accept their licence on Hugging Face first. Everything fits in about 52 GB of VRAM, plus working memory for the shot.

## Use

| Tool | Key | What it does |
| --- | --- | --- |
| Paint | B | Paint a rough shape in a colour, then say what it is: "a fire", "a wooden desk" |
| Erase | E | Paint over what should go. Erase part of a person and only that part goes |
| Light | L | Paint where the light comes from, in its colour. Words are optional |
| Restore | R | Brings back the plate under the brush |

`[` and `]` change the brush size. `1` and `2` pick an option, `Enter` asks for two new ones, `Esc` discards the edit, `Ctrl+Z` undoes a stroke. Hold `O` to see the original frame. Up to three edits stack on one shot.

When you pause, PaintAPlate uses the idle time: it refines both options at full size, then renders the shot, tracks the edited areas and exports at full quality. Any new stroke cancels that work and starts again from the cheapest step it affects.

## How it works

| Workflow | Steps |
| --- | --- |
| `ingest` | Load Plate, Convert Image Color Space, first frame and a playback proxy |
| `edit` | FLUX 3 Image Klein edits inside the painted mask; Image Composite Masked keeps every other pixel |
| `shot` | LTX 2.5 with the Ripple IC-LoRA carries the edited first frame through the shot |
| `matte` | SAM 3.1 follows each painted area through the frames |
| `export` | Fit to Plate, Relight Transfer, Image Composite Masked, Save Plate |

Core ComfyUI does the colour conversion, compositing, masks, sampling and step previews. Four nodes fill the gaps:

| Node | Gap it fills |
| --- | --- |
| Load Plate | Folders of frames, the source spec, padding to the 8k+1 frames LTX needs. Decoding is core's |
| Save Plate | Writes in the source format. For EXR, every other layer, part and header attribute is kept, and pixels outside the edit are copied bit for bit. Video keeps codec, pixel format, colour tags, timecode and audio |
| Fit to Plate | Resizes generated frames to the plate, removes small shifts, matches colour and grain around the edit |
| Relight Transfer | Takes light, shadows and reflections from the regenerated shot and keeps the plate's own texture, grain, sharpness and highlights above 1.0 |

The page fills named slots in each workflow and posts it to ComfyUI. Step previews arrive over ComfyUI's WebSocket, so an option starts to appear after the first sampling step.

## Guarantees and limits

- Outside the edited areas, EXR, PNG, TIFF and DPX output is identical to the input, bit for bit. A video output is re-encoded, so untouched pixels are as close as the codec allows.
- A relight changes every pixel by design. Its fine detail still comes from the plate.
- The shot renders at half the working size by default, for speed. Add `?shot=full` to the page address to render it at full working size.
- Shots up to 121 frames (5 s at 24 fps). Edits are painted on the first frame.
- The Ripple model card says to replace the first frame, which is what this pack does. Its author's example workflow prepends it instead, which shifts the plate by one frame.

## Development

```bash
python tools/build_workflows.py                         # writes web/workflows/*.json
python tools/check_workflows.py ../../ ../ComfyUI-LTXVideo   # every class and input name against source
python tests/test_plateio.py && python tests/test_mathops.py
```

Workflows are generated from `tools/build_workflows.py`, never edited by hand. Releases publish to the Comfy Registry from GitHub when the version in `pyproject.toml` changes.

## Licence and credits

Code: Apache 2.0. Models keep their own licences, listed above. Thanks to Black Forest Labs (FLUX 3 Image Klein), Lightricks (LTX 2.5, ComfyUI-LTXVideo), WepeNerd (LTX Ripple), Meta (SAM 3.1) and the ComfyUI team.

Made by [AInVFX](https://ainvfx.com).
