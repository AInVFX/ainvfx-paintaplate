# AInVFX PaintAPlate

Paint on the first frame of a shot to erase, add or relight. The edit appears on that frame in seconds, then carries through the whole shot. You review the result at the plate's own quality, an EXR against its EXR, through OpenColorIO as in OpenRV. Export then writes it in the plate's own format: same file type, bit depth, frame numbers, colour tags, timecode, audio and EXR layers, with every untouched pixel identical to the plate.

PaintAPlate is a ComfyUI node pack with its own page. Every step is a ComfyUI workflow from `web/workflows`, open weights only:

- **FLUX 3 Image Klein** edits the first frame. Its own prompt upsampler, a Qwen 3.5 9B model from Black Forest Labs, writes each caption from your few words and the frame.
- **LTX 2.5** carries the edit through the shot. Lightricks' in-outpainting IC-LoRA regenerates erased areas; WepeNerd's Ripple IC-LoRA carries paint and light.
- **SAM 3.1** finds whole objects and follows every edit through the shot.
- **ainvfx-fluid**, AInVFX's own IC-LoRA for LTX 2.5, trained on synthetic data (dataset `AInVFX/ainvfx-fluid`), turns flat painted keyframes into smoke, steam, fire, explosions, dust, fog or clouds, from a blank plate.

It was tested on an RTX PRO 6000 (96 GB). Smaller cards have not been tested.

## Run it on Runpod

1. Accept the licences of the gated models on Hugging Face: [FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy), [LTX 2.5](https://huggingface.co/Lightricks/LTX-2.5) and the [in-outpainting IC-LoRA](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting). Create a read token.
2. Start a pod with an RTX PRO 6000, the image `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`, a host with CUDA 13.0 or newer, 150 GB of disk, ports 8188 and 8888, and your token in an `HF_TOKEN` environment variable. Prefer a European data centre.
3. In the pod's JupyterLab terminal:

   ```sh
   git clone https://github.com/AInVFX/ainvfx-paintaplate /workspace/ainvfx-paintaplate
   PLATES=1 bash /workspace/ainvfx-paintaplate/tools/runpod_start.sh
   ```

   The script installs the tested ComfyUI and ComfyUI-LTXVideo, links this pack, downloads 60 GB of models and starts ComfyUI. `PLATES=1` adds the 23 test plates of the dataset [AInVFX/ainvfx-paintaplate](https://huggingface.co/datasets/AInVFX/ainvfx-paintaplate) to `input/plates`; `FLUID=0` skips ainvfx-fluid. The script prints each step, then the page's address: `https://<pod id>-8188.proxy.runpod.net/extensions/ainvfx-paintaplate/paintaplate.html`.

After `git pull`, `bash tools/runpod_start.sh --restart` loads the new code. `tools/offline_bundle.sh` prepares a pod that cannot reach GitHub. Port 8188 has no password: anyone with the pod's address can use it.

## Run it on your own machine

1. Install ComfyUI v0.43.0 or newer, and [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) (tested at `220e1d4`).
2. Clone this repository into `ComfyUI/custom_nodes/` and install its requirements, OpenEXR and OpenColorIO: `pip install -r requirements.txt`.
3. Download the models below into `ComfyUI/models/`. `tools/pod_setup.sh` does it with your token, at the tested revisions.
4. Start ComfyUI, then open **Extensions > Open PaintAPlate**, or `http://127.0.0.1:8188/extensions/ainvfx-paintaplate/paintaplate.html`.

| File | Folder under `models/` | Size | Repository (tested revision) |
| --- | --- | --- | --- |
| `flux3-image-klein-int8-convrot.safetensors` | `diffusion_models/` | 5.8 GB | [black-forest-labs/flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) (`feef60b`) |
| `qwen3vl_4b_int8_convrot.safetensors` | `text_encoders/` | 4.9 GB | same |
| `qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors` | `text_encoders/` | 6.7 GB | same |
| `flux2-vae.safetensors` | `vae/` | 0.3 GB | same |
| `ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors` | `diffusion_models/` | 21.5 GB | [Lightricks/LTX-2.5](https://huggingface.co/Lightricks/LTX-2.5) (`49b093a`) |
| `gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors` | `text_encoders/` | 15.4 GB | same |
| `ltx-2.5-video-vae-conv-bf16.safetensors` | `vae/` | 1.5 GB | same |
| `ltx-2.5-audio-vae-bf16.safetensors` | `vae/` | 0.4 GB | same |
| `ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors` | `loras/` | 1.3 GB | [Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting) (`8becd61`) |
| `LTX25_Ripple_v11.safetensors` | `loras/` | 0.7 GB | [WepeNerd/LTX-Ripple](https://huggingface.co/WepeNerd/LTX-Ripple) (`76abac5`) |
| `sam3.1_multiplex_fp16.safetensors` | `checkpoints/` | 1.7 GB | [Comfy-Org/sam3.1](https://huggingface.co/Comfy-Org/sam3.1) (`7bb8374`) |
| `taeltx2_3.safetensors` | `vae_approx/` | 0.02 GB | [Kijai/LTX2.3_comfy](https://huggingface.co/Kijai/LTX2.3_comfy) (`6d980fd`), from [madebyollin/taehv](https://github.com/madebyollin/taehv) (MIT) |
| `ainvfx-fluid.safetensors` (optional: fluid shots) | `loras/` | 0.65 GB | [AInVFX/ainvfx-fluid](https://huggingface.co/AInVFX/ainvfx-fluid) (`fd4855a`), file `ltx-2.5/ainvfx-fluid.safetensors` |

## Use it

**Open plate** has one tab per source. **ComfyUI files** browses ComfyUI's input and output folders and their subfolders: videos, animated images, and image sequences, each named by its frame pattern (`shot.####.exr`, or `ComfyUI_#####_.png` for core Save Image's frames). It stays fast on folders of thousands of outputs. One click shows a plate's size, frames, format and colour space; a double click opens it. **Upload** sends files from your computer. **Scenes** opens a scene saved on this ComfyUI. **Blank plate** starts a fluid shot.

Type a few words, pick a tool, paint on the first frame, then **Generate** (or Enter).

- **Paint** adds what you describe where you paint. It may change the frame a little around your strokes, so a fire can light what it touches.
- **Erase** removes the object under your stroke. With **Whole object**, SAM 3.1 finds all of it: name it ("red umbrella") and the stroke may even cross the background. A shadow outside the object stays: erase it with a second stroke, Whole object off.
- **Light** relights the shot. Describe the light ("night time", "warm sunset from the left") and paint where it comes from.

The edit appears on the first frame, then the shot renders by itself: a quick preview first (Fast, 640, by default), with a small animation of the shot while LTX samples it, then the full size, then the **full quality**: the full-size composite at the plate's quality, which the viewer plays from then on. For an EXR plate, the wipe (F6) compares the result's EXR frames with the plate's own, at full precision, so exposure and the other colour tools show what the export will hold. **Export** writes the result in the plate's format and its matte, only when you press it, then downloads them as one zip, with the review movie or the regenerated shot if you tick them. In the same dialog, **ComfyUI graph** saves the whole scene as one ComfyUI workflow.

**Colour** follows OpenRV. Right-click the frame, then **OCIO**: **File Color Space** sets the plate's colour space (the viewer shows it at once, and the edits are made again in it), **Look** and **Displays** set what the viewer shows while the shot plays, and **Change Config** picks the OCIO config. The config is the one `$OCIO` names, as in RV, else OCIO's built-in ACES studio config. The plate's colour space is read from the file when it opens. Exposure (Shift+E), contrast (K), gamma (Y), saturation (Shift+S), hue (H) and the channels work as RV's.

Click an edit in History to select it: its words come back, and painting, rubbing out or retyping changes it. The edits above it follow when they depend on it. Undo and redo sit at the top of History. **Save scene** keeps the plate, its colour space and every edit on this ComfyUI. The models load while you look at the page, so the first edit starts at once. Press `?` for the keys; playback follows OpenRV, and the right-click menu holds every action with its key.

A **fluid shot** starts from a blank plate: paint flat colour blobs (light grey smoke, white steam, orange and yellow fire, flat zones for sky and ground) on frame 0 and on the last frame, describe the fluid, then Generate. The shot becomes the plate for every edit.

## How it works

| Workflow | What it does |
| --- | --- |
| `ingest` | Reads the plate, saves the first frame and a playback movie |
| `prompt` | Klein's upsampler writes the caption: the frame, your words and the painted box in, the caption Klein was trained on out |
| `snap` | SAM 3.1 finds the object under an erase stroke, point by point and by name |
| `edit` | Klein edits the first frame: a quick pass at 768, then the full size |
| `matte` | SAM 3.1 follows an edit through the shot; Follow Matte keeps what the edit made inside the matte |
| `clean`, `cleanup` | The erase pass: the in-outpainting IC-LoRA regenerates each erased area; at full size in Lightricks' two stages |
| `shot` | Ripple carries the edited first frame through the shot, over the clean plate when there are erases |
| `comp` | The composite at the preview size |
| `review` | The full-size composite at the plate's quality, for the viewer |
| `export` | The same composite, saved in the plate's format with its matte, on Export |
| `warm` | Loads LTX 2.5 at start, on cards with 60 GB or more |
| `fluid` | ainvfx-fluid turns painted keyframes into a fluid shot |

The page fills each workflow's slots before posting it: every node lists them in `_meta.slots`, and `tools/build_workflows.py` writes the files. The eleven PaintAPlate nodes only do what core ComfyUI cannot: Load Plate, Save Plate, Color Space (OCIO), Save Frames, Save Movie, Fit to Plate, Relight Transfer, Follow Matte, Level Fill, Live Preview and Keyframe Video. Their file handling lives in `plateio.py`, their pixel maths in `mathops.py` and their colour in `ocio.py`, all tested without torch. A job made once is kept in a job index on disk, so the same edit on the same plate never runs twice, even in a later session. `ARCHITECTURE.md` maps the code; `TESTING.md` describes every test level.

## Change it

- The workflows: edit `tools/build_workflows.py`, then run `python tools/build_workflows.py`. Each file also opens in ComfyUI by drag and drop.
- The page: `web/app.mjs` (the app, with its tuning block at the top), `web/logic.mjs` (pure rules, tested in Node), `web/display.mjs` (the viewer's OCIO), `web/graph.mjs` (the scene as one ComfyUI workflow), `web/comfy.mjs` (the ComfyUI client).
- Tests: `pip install -r tests/requirements.txt`, then `python -m unittest discover -s tests -v`. GitHub Actions runs the unit tests, the page against a mock ComfyUI, and a real ComfyUI on CPU, on every push.

## Limits

- A cast shadow outside the erased object stays: erase it with a second stroke.
- An erased object can come back if its name reaches the shot's prompt, so the page never names erases there.
- Very thin objects need their name for Whole object: « floodlight pole » finds more than « floodlight ».
- An erased head comes back as a head: paint the new head over the old one instead.
- An addition painted across a foreground object breaks up mid-shot: paint additions in open space.
- Edits are painted on the first frame; shots up to 121 frames; edits at up to 1920 px on the long side.

## Licences and credits

PaintAPlate's code is Apache 2.0. The models keep their own licences: read each model card before use. LTX 2.5 and its IC-LoRAs (Ripple, in-outpainting, ainvfx-fluid) are under the LTX-2.x Community License, which asks for a paid licence from 10 million USD of annual revenue. SAM 3.1 is under the SAM License. The tiny decoder comes from madebyollin/taehv (MIT). The upsampler's system prompts in `web/upsampler.json` are Black Forest Labs' own text (Apache 2.0). The test plates of `AInVFX/ainvfx-paintaplate` are synthetic, made with LTX 2.5, MOSS-Image and FLUX 3 Image Klein, and published under CC BY 4.0.

Made by [AInVFX](https://ainvfx.com).
