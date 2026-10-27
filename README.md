# AInVFX PaintAPlate

Paint on the first frame of a shot to erase, add or relight. The edit appears on that frame in seconds, then carries through the whole shot, and the result comes back in the plate's own format: same file type, bit depth, frame numbers, colour tags, timecode and audio, with every untouched pixel identical to the plate.

PaintAPlate is a ComfyUI node pack with its own page. Every step is a ComfyUI workflow from `web/workflows`, open weights only:

- **FLUX 3 Image Klein** edits the first frame. Its own prompt upsampler, a Qwen 3.5 9B model from Black Forest Labs, writes each caption from your few words and the frame.
- **LTX 2.5** carries the edit through the shot. Lightricks' in-outpainting IC-LoRA regenerates erased areas; WepeNerd's Ripple IC-LoRA carries paint and light.
- **SAM 3.1** finds whole objects and follows every edit through the shot.

It was tested on an RTX PRO 6000 (96 GB). Smaller cards have not been tested.

## Run it on Runpod

1. Accept the licences of the gated models on Hugging Face: [FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy), [LTX 2.5](https://huggingface.co/Lightricks/LTX-2.5) and the [in-outpainting IC-LoRA](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting). Create a read token.
2. Start a pod with an RTX PRO 6000, the image `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`, a 150 GB container disk, ports 8188 and 8888, and your token in an `HF_TOKEN` environment variable. Prefer a European data centre: a US host once made the composite ten times slower.
3. In the pod's JupyterLab terminal:

   ```sh
   git clone https://github.com/AInVFX/ainvfx-paintaplate /workspace/ainvfx-paintaplate
   bash /workspace/ainvfx-paintaplate/tools/runpod_start.sh
   ```

   The script installs the tested ComfyUI and ComfyUI-LTXVideo, links this pack, downloads 60 GB of models and starts ComfyUI. It prints each step, then the page's address: `https://<pod id>-8188.proxy.runpod.net/extensions/ainvfx-paintaplate/paintaplate.html`.

After `git pull`, `bash tools/runpod_start.sh --restart` loads the new code in about 10 seconds. `tools/offline_bundle.sh` prepares a pod that cannot reach GitHub.

## Run it on your own machine

1. Install ComfyUI v0.42.5 or newer, and [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo) (tested at `220e1d4`).
2. Clone this repository into `ComfyUI/custom_nodes/` and install its requirement: `pip install -r requirements.txt`.
3. Download the models below into `ComfyUI/models/`. `tools/pod_setup.sh` does it with your token, at the tested revisions (set `WORKDIR` and `VENV` to your own folders).
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

## Use it

Open a plate: a video file, or a folder of EXR, PNG, TIFF or DPX frames. Type a few words, pick a tool, paint on the first frame. The edit starts 2 seconds after your last stroke.

- **Paint** adds what you describe where you paint. It may change the frame a little around your strokes, so a fire can light what it touches.
- **Erase** removes the object under your stroke. With **Whole object**, SAM 3.1 finds all of it: name it ("red umbrella") and the stroke may even cross the background. A shadow outside the object stays: erase it with a second stroke, Whole object off.
- **Light** relights the shot. Describe the light ("night time", "warm sunset from the left") and paint where it comes from.

Click an edit in History to select it: its words come back, and painting, rubbing out or retyping changes it. The edits above it follow when they depend on it. Undo and redo sit at the top of History. **Save scene** writes a `.paintaplate.json` file with the plate and every edit; Open plate opens it again on the same ComfyUI. The models load while you look at the page, so the first edit starts at once. Press `?` for the keys; playback follows OpenRV.

The shot renders in idle time: first a quick preview (Fast, 640, by default), then the full size and the export in the background. **Export** downloads the result, its matte, a review movie or the regenerated shot as one zip.

## Tested on

The five plates in `tests/plates`, and Tears of Steel source footage as a 1920 x 1012 linear EXR sequence: a man's head replaced by a robot head, tracked through a camera move and a focus pull, then exported as EXR. Tears of Steel: (CC) Blender Foundation | mango.blender.org; the actors keep their image rights.

## How it works

| Workflow | What it does |
| --- | --- |
| `ingest` | Reads the plate, saves the first frame and a playback movie |
| `prompt` | Klein's upsampler writes the caption: the frame, your words and the painted box in, the caption Klein was trained on out |
| `snap` | SAM 3.1 finds the object under an erase stroke, point by point and by name |
| `edit` | Klein edits the first frame: a quick pass at 768, then the full size |
| `matte` | SAM 3.1 follows an edit through the shot |
| `clean` | The erase pass: the in-outpainting IC-LoRA regenerates each erased area, shown to it as a green box |
| `shot` | Ripple carries the edited first frame through the shot, over the clean plate when there are erases |
| `comp`, `export` | The new pixels fitted to the plate (alignment, colour, grain), composited inside the mattes, saved in the plate's format |
| `warm` | Loads LTX 2.5 at start, on cards with 60 GB or more |

The page fills each workflow's slots before posting it: every node lists them in `_meta.slots`, and `tools/build_workflows.py` writes the files. The six PaintAPlate nodes only fill gaps in core ComfyUI: Load Plate, Save Plate, Fit to Plate, Relight Transfer, Fill Matte and Box Matte. Their maths live in `mathops.py` and their file handling in `plateio.py`, both tested without torch. `TESTING.md` maps the code and every test level.

## Change it

- The workflows: edit `tools/build_workflows.py`, then run `python tools/build_workflows.py`. Each file also opens in ComfyUI by drag and drop.
- The page: `web/app.mjs` (the app, with its tuning block at the top), `web/logic.mjs` (pure rules, tested in Node), `web/comfy.mjs` (the ComfyUI client).
- The upsampler's system prompts: `web/upsampler.json`, Black Forest Labs' own text (Apache 2.0).
- Tests: `python -m unittest discover -s tests -v`.

## Limits

- A cast shadow outside the erased object stays: erase it with a second stroke.
- An erased object can come back if its name reaches the shot's prompt, so the page never names erases there.
- Very thin objects need their name for Whole object: « floodlight pole » finds more than « floodlight ».
- An erased head comes back as a head: the models never leave a body without one. Paint the new head over the old one instead.
- A fire can come with fuel the scene never had. Describe what burns: "the towel itself on fire".
- Shots up to 121 frames; edits at up to 1920 pixels on the long side.

## Licence

Apache 2.0, see [`LICENSE`](LICENSE). The models have their own licences. FLUX 3 Image Klein uses the FLUX Kommunity License: outputs may be used commercially below 5 million USD of annual revenue. Its upsampler is Apache 2.0. LTX 2.5, Ripple and the in-outpainting IC-LoRA use the LTX-2 Community License: a paid licence is needed from 10 million USD of annual revenue. SAM 3.1 uses the SAM License. Read each model card before production use.
