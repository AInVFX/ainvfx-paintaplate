<h1 align="center"><img src="web/brand/title.png" alt="AInVFX Paint a plate" width="100%"></h1>

**Winner of the Open Weights Only category and of the "VFX Workflow Built with LTX" bonus in Comfy's [Open Source Higgsfield](https://comfy.org/open-source-higgsfield/) contest** (November 2026). #OpenSourceHiggsfield

[![The showcase of Paint a plate on YouTube: painted fire, smoke and water, a set extension, a green screen, a relight](https://img.youtube.com/vi/EsL3O7WvBr4/maxresdefault.jpg)](https://youtu.be/EsL3O7WvBr4)

**[▶ Watch the showcase (4 minutes)](https://youtu.be/EsL3O7WvBr4)**: shots made live with Paint a plate.

**[▶ Watch the deep dive (1 hour)](https://youtu.be/6uVHvw6gsC8)**: a complete guide, from the install to the export.

**Contents:** [What it does](#what-it-does) · [What you need](#what-you-need) · [Install](#install) · [A first edit](#a-first-edit) · [Tips](#tips) · [When something goes wrong](#when-something-goes-wrong) · [How it works](#how-it-works) · [Questions from the community](#questions-from-the-community) · [Limits](#limits) · [Contributing](#contributing) · [Credits and licences](#credits-and-licences) · [Links](#links)

Paint a plate is a visual effects tool that runs in [ComfyUI](https://github.com/comfyanonymous/ComfyUI), on your own machine, with open weights only. A plate is the filmed shot that the effects go into. Paint on the first frame of a plate to erase, add or relight, watch the edit carry through the shot, and export it in the plate's own format, layers and untouched pixels. FLUX 3 Image Klein, Black Forest Labs' image model, makes the edit on the first frame in seconds. LTX 2.5, Lightricks' video model, extends it to the whole shot. Every untouched pixel of the result is identical to the plate.

## What it does

| Feature | What it does |
| --- | --- |
| **Clean** | Removes the object under your stroke and regenerates the background behind it. Enable **Whole object** to remove all of it: name it in the text prompt ("red umbrella"), and SAM 3.1 (Meta's Segment Anything Model) finds it |
| **Paint** | Adds what the text prompt describes where you paint, in the style of the image. It follows the outline, pose and colours of your strokes. SAM 3.1 tracks it, and the **Matte strategy** menu chooses how much of the new shot to keep, from the object alone to the whole shot, so the plate stays untouched everywhere else |
| **Light** | Relights the shot. Paint where the light comes from, in its colour. Paint in black to darken an area |
| **A fluid shot** | Starts from a blank plate. Paint your fluid (smoke, fire, water and more) in flat colours on a few keyframes, and ainvfx-fluid, our fluid model, generates the shot as the first row of History. Then edit it with Paint, Clean or Light, as any plate |
| **Review** | The viewer follows [OpenRV](https://github.com/AcademySoftwareFoundation/OpenRV), the Academy Software Foundation's review player: colour through OpenColorIO (OCIO), the same keys, a wipe against the plate, the Colour Inspector |
| **Finish** | Enable **SDR to HDR** to turn a standard dynamic range plate, edited or not, into high dynamic range: half-float EXR frames in ACES2065-1. Enable **Upscale** to upscale or restore the result with ByteDance's SeedVR2 7B: from the plate's own size up to 3840 x 2160 |
| **Export** | Writes the files you tick in the Export dialog as one zip: the plate, the shot, the layer, the matte and the composite, at each stage the render made (preview, full size, HDR, upscaled). The matte is the mask of what the edit changed. Frames keep the plate's format. A movie becomes ProRes 4444 XQ, with its colour tags, timecode and audio, or 16-bit PNG frames when it holds more than 10 bits. With SDR to HDR, the HDR stage gives half-float EXR frames in ACES2065-1. Each file is named after the plate, or the scene once saved, then its row in the Export dialog. Enable **ComfyUI graph** to export every step as ComfyUI workflows, with their source images, to open and change in ComfyUI: one for the fluid shot, one for the edits and one for Finish's steps, to run in that order |

## What you need

- **ComfyUI v0.45.3 or newer**, with [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo).
- **An NVIDIA GPU with 16 GB of VRAM** at least. 16 GB is the tested minimum: every tool runs there, more slowly, because the models load one at a time. More VRAM is faster: from 24 GB, the edit models load when the page opens, and from 60 GB, every model does and stays loaded. For a plate above 2K, more than 2048 px on its long side, a 96 GB GPU is recommended: see [Limits](#limits).
- **79 GB of disk** for the models.
- **64 GB of RAM**, recommended: the smallest amount we tested. RAM grows with a plate's length and size: see [Limits](#limits).

On a Mac, or without such a GPU, run Paint a plate [on Runpod](#on-runpod).

## Install

The steps are the same on Windows and Linux. Run each command with the Python that runs ComfyUI, since the system's Python lacks ComfyUI's packages:

| Your setup | The Python to use |
| --- | --- |
| Linux, ComfyUI installed by hand | `python`, with ComfyUI's virtual environment active |
| Comfy Desktop | `python`, in its terminal panel |
| Windows, portable ComfyUI | `..\..\..\python_embeded\python.exe`, from the pack's folder |

1. **Install ComfyUI** v0.45.3 or newer, with [its install guide](https://docs.comfy.org/installation).
2. **Accept the terms of four models on Hugging Face.** Sign in, then open each page and accept its terms:
   - [FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy)
   - [LTX 2.5](https://huggingface.co/Lightricks/LTX-2.5)
   - [LTX 2.3 in-outpainting IC-LoRA](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting)
   - [LTX 2.5 SDR-to-HDR IC-LoRA](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR), for SDR to HDR

   Then create a [read token](https://huggingface.co/settings/tokens). The other models download with no extra step.
3. **Install Paint a plate and ComfyUI-LTXVideo**, in one of two ways:
   - **With ComfyUI Manager** (recommended). In ComfyUI, open **Extensions > All Extensions** (with the Manager's legacy interface: **Manager > Custom Nodes Manager**). Search for **Paint a plate** and install **AInVFX Paint a plate** ([its Registry page](https://registry.comfy.org/nodes/ainvfx-paintaplate)). Install **ComfyUI-LTXVideo** the same way. With comfy-cli, the pack installs with `comfy node install ainvfx-paintaplate`. If ComfyUI shows no **Extensions** entry, turn its Manager on: in ComfyUI's folder, run `python -m pip install -r manager_requirements.txt`, then start ComfyUI with `--enable-manager`.
   - **With git**, from ComfyUI's folder:

     ```sh
     cd custom_nodes
     git clone https://github.com/AInVFX/ainvfx-paintaplate
     git clone https://github.com/Lightricks/ComfyUI-LTXVideo
     python -m pip install -r ainvfx-paintaplate/requirements.txt
     python -m pip install -r ComfyUI-LTXVideo/requirements.txt
     ```
4. **Restart ComfyUI.**
5. **Download the models** into ComfyUI's `models` folders: 17 files, 79 GB in all. Get the ones you lack by hand, from [the model files](#the-model-files), which gives each file's link and folder, or with [`get_models.py`](get_models.py). For the script, go to the pack's folder, `custom_nodes/ainvfx-paintaplate`, and set your token: `export HF_TOKEN=hf_...` on Linux, `$env:HF_TOKEN = "hf_..."` in PowerShell on Windows. Then run:

   ```sh
   python get_models.py --list    # each file, its folder and size, and whether it is in place
   python get_models.py           # downloads what is missing: 79 GB in all
   ```

   The script puts each file in its folder, at the revision that was tested, and skips a file already in place: you can run it again. If Hugging Face refuses a file, its line says why and names the page to open. For a download by hand, `--list` names each file's folder, Hugging Face repository and tested revision. For models in another folder, name it: `python get_models.py path/to/models`. `--no-fluid` skips ainvfx-fluid, `--no-hdr` skips SDR to HDR and `--no-upscale` skips SeedVR2 7B (Upscale): that feature is then off, and the rest works.
6. **Download the example plates** with [`get_plates.py`](get_plates.py). This step is optional and needs no token.

   ```sh
   python get_plates.py           # 23 plates, 148 MB, into ComfyUI's input/plates
   ```

   The plates are synthetic shots made with AI, from the dataset [AInVFX/ainvfx-paintaplate](https://huggingface.co/datasets/AInVFX/ainvfx-paintaplate). **Open plate** lists them under `plates`. `python get_plates.py --only horse.mp4` downloads one plate, and `--list` names them all.
7. **Open the page.** With ComfyUI running, open this address in your browser:

   ```
   http://127.0.0.1:8188/extensions/ainvfx-paintaplate/paintaplate.html
   ```

### On Runpod

Runpod rents GPUs by the hour, in the cloud. Its 96 GB GPUs run every tool of Paint a plate at full speed, plates above 2K included, with no powerful GPU of your own.

1. Accept the four models' terms and create a Hugging Face read token, as in [step 2 of Install](#install).
2. Start a pod: an RTX PRO 6000, Runpod's latest official PyTorch template (tested with the image `runpod/pytorch:2.2.0-cu1320-torch2150-ubuntu2404`), a host with CUDA 13.0 or newer, a 150 GB container disk, ports 8188 and 8888, and your token in an `HF_TOKEN` environment variable of the pod. To keep the token as a Runpod secret, create a secret named `HF_TOKEN`, then give the pod's `HF_TOKEN` variable the value `{{ RUNPOD_SECRET_HF_TOKEN }}`: a secret alone does not reach the pod.
3. In the pod's JupyterLab terminal, run:

   ```sh
   git clone https://github.com/AInVFX/ainvfx-paintaplate /workspace/ainvfx-paintaplate
   PLATES=1 bash /workspace/ainvfx-paintaplate/tools/runpod_start.sh
   ```

   [The script](tools/runpod_start.sh) installs the latest ComfyUI and ComfyUI-LTXVideo, links this pack into ComfyUI, downloads the models and the example plates, and starts ComfyUI. Then it prints the page's address.

After a `git pull`, `bash tools/runpod_start.sh --restart` loads the new code. Port 8188 has no password: anyone with the pod's address can use the page.

No Runpod account yet? Create it through [our referral link](https://www.runpod.io/?ref=iad0yzht), and sign up with Google. Once you add credit, Runpod adds free credit to your account. It also gives AInVFX a small credit based on what you spend, which pays for the pods Paint a plate is tested on. It costs you nothing more, and it is a simple way to say thank you. The amounts and the rules are on [Runpod's referral page](https://docs.runpod.io/accounts-billing/referrals).

## A first edit

1. Press **Open plate**, then double-click a plate, for example `plates/horse.mp4`. Sequence files and folders of frames are supported. A plate opens with up to 20 s of frames, or as many as this machine holds. In the same dialog, **Blank plate** starts a fluid shot.
2. Pick a tool: **Paint**, **Clean** or **Light** (keys P, C and L). Describe the edit in the text prompt, for example "a campfire". Then paint on the first frame.
3. Press Enter (or **Generate**) to make the edit on the first frame, then the shot. The Render panel shows each step as it runs, and each pass displays live. **Render > Preview** can first make a shot preview: a quick pass of the whole shot at half or a quarter of the size.
4. Play the shot with Space, and compare it with the plate in the wipe.
5. Press **Export** to write the result in the plate's own format.

Each edit stays in History, and you can add as many as you need. Hover or click a row to show its strokes. Use the pencil to edit. **Save scene** keeps the plate and its edits on this ComfyUI.

## Tips

- Clean a thin object by its full name: "floodlight pole" finds more than "floodlight".
- With **Whole object** on, Clean also removes the object's cast shadow when the prompt writer, the model that writes each edit's caption, mentions it. If a shadow stays, clean it with a second stroke, **Whole object** off.
- To replace a head, paint the new head over the old one.
- With a shot preview at half or a quarter size, judge an effect on the full-size shot.
- Paint a plate reads each plate's colour space from its file, and the export writes every pixel back in that space. Change it only for a camera's log footage, which no file tag describes: right-click > OCIO > Plate, then the camera's log space.
- Open the EXR frames of SDR to HDR in ACES2065-1, in a viewer or in compositing software. Read with a plain gamma, they look darker and less saturated than the plate.
- Open a plate behind a symbolic link inside ComfyUI's input or output folder by its full path, when ComfyUI runs on your own machine: the Open dialog does not follow such a link. The input or output folder itself can be a link, or set with ComfyUI's `--input-directory` and `--output-directory`.
- Export's zip names each file after the plate, or the scene once saved, then its row: for a plate named `desk`, `desk_v1.zip` holds `desk_composite_full_size.mov`, the matte's frames in `matte/`, `desk_shot_full_size.mp4`, `desk_comfyui_graph.json` and `desk_models.md`. When the zip holds several ComfyUI graphs, each is named after what it makes: `desk_fluid_shot_comfyui_graph.json`, `desk_edits_comfyui_graph.json` and `desk_finish_comfyui_graph.json`. With SDR to HDR, its frames are the row **HDR**, in `hdr/`.
- **Source plate**, off by default, adds the plate's own files to the zip, in `source_plate/`. A plate of 4K EXR frames can take many gigabytes: the dialog shows their size first, and the zip downloads as it is written.
- To run the exported ComfyUI graphs on another machine, copy the zip's `input/` folder into ComfyUI's input folder and the plate to the path the graphs name, then run the graphs in their order: each reads the output from the previous one.
- Press `?` for the keys. The backquote key shows the viewer full screen, where S opens the colours and T the edit's text prompt. The right-click menu lists every action with its keyboard shortcut, and the viewer's colour tools under **OCIO**.

## When something goes wrong

- **The log.** The **Log** button opens it. It records what happened, one line per fact, and the button is highlighted when an error arrives. The download icon beside it saves the log as a text file, with the versions and the machine as ComfyUI reports them. Its paths start at ComfyUI's folder, as `output/paintaplate/…`, so it shows nothing of your own folders.
- **The memory profile.** Its line in the log says how the page uses your GPU, from its VRAM: see [What you need](#what-you-need).
- **Stop.** Esc, or **Stop** beside Generate, stops what generates. Finished steps are kept. Press Enter to continue from there.
- **ComfyUI's memory grows, or the page waits and nothing runs.** Start ComfyUI with `PAINTAPLATE_TRACE=1` in its environment. Every request then writes a line in ComfyUI's terminal when it starts and when it ends, with the memory the process holds. Add these lines to your report: [TESTING.md](TESTING.md#the-trace-when-comfyuis-memory-grows-and-no-job-runs) explains them.
- **A model or a node is missing.** The page names it at start. `python get_models.py --list` shows what is in place.
- **Report a fault** in the [issues](https://github.com/AInVFX/ainvfx-paintaplate/issues), with the saved log attached.

## How it works

Paint a plate is a web page that ComfyUI serves, with a pack of 16 nodes. Each step is one of 17 ComfyUI workflows, in [`web/workflows`](web/workflows): the page fills in its values and sends it to ComfyUI. A job made once is kept in a job index on disk, so the same edit on the same plate never runs twice. For Paint and Clean, the prompt writer names the edit's object and what the plate keeps, and the matte comes from SAM 3.1's answers to several questions about them. The composite then blends the regenerated shot into the plate through the matte. The [models table](#credits-and-licences) says what each model does.

[ARCHITECTURE.md](ARCHITECTURE.md) explains how the pack works and how to change it. [TESTING.md](TESTING.md) describes every test.

## Questions from the community

**Why LTX 2.5?** Its weights are open and run on your own machine, under a licence that allows it, as the contest's Open Weights Only category asked. Its IC-LoRAs also let one video model make the clean plate, paint, light and fluid passes. An IC-LoRA (in-context LoRA) is a small add-on that teaches LTX 2.5 one task, from a guide video.

**How was ainvfx-fluid trained?** It is an IC-LoRA for LTX 2.5, trained in three stages on 176 synthetic scenes with the `ltx_iclora` recipe of [ainvfx-runpod](https://github.com/AInVFX/ainvfx-runpod). Its [model card](https://huggingface.co/AInVFX/ainvfx-fluid) and its [dataset card](https://huggingface.co/datasets/AInVFX/ainvfx-fluid) give the method, the data and the compute.

**Where do I get the app?** Here, or from the [Comfy Registry](https://registry.comfy.org/nodes/ainvfx-paintaplate), which serves the code of this repository: see [Install](#install).

## Limits

**Length and frame rate**

- A plate opens with up to 20 s at its frame rate, LTX 2.5's longest shot: 481 frames at 24 fps, 497 at 25 fps and 1,001 at 50 fps. It also opens with no more frames than this machine's RAM holds through every step. The Open dialog says so before the plate opens, and the log names any frames left out.
- Every tool is tested at 121 frames. Longer shots also run, tested at 497 frames (1920 x 1080, 25 fps) and 1,001 frames (960 x 544, 50 fps) on a 96 GB GPU with 175 GB of RAM. They need more VRAM and more RAM, and take about twice the time that the Render panel announces.

**Size**

- Edits are painted on the first frame only, and made at up to 1920 px on the long side.
- A plate can be up to 3840 x 2160. Upscale goes up to the same size.
- A plate above 2K runs best on a 96 GB GPU. On an RTX PRO 6000 (96 GB), the erase of a 3840 x 2160 plate of 121 frames took 341 s. On an RTX 5090 (32 GB), the same erase was still running after 30 minutes.

**Memory and time**

- RAM grows with a plate's length and size. With 52 GB of RAM for ComfyUI and a 16 GB GPU, a 1920 x 1080 plate opens with 121 frames. With 175 GB of RAM and a 96 GB GPU, it opens with 513 frames, and a 3840 x 2160 plate with 129. A 3840 x 2160 plate of 121 frames ran on a 96 GB GPU with 188 GB of RAM, where ComfyUI held up to 164 GB.
- Under 16 GB of VRAM, LTX works in 256 px tiles, and a soft band can show where two tiles overlap, most in SDR to HDR's frames.
- Upscale runs again with each new render. At 3840 x 2160, for 121 frames, it takes about 46 min for Paint or Clean on a 16 GB GPU, 23 min for the result alone, and about 14 min on a 96 GB GPU.
- On a 16 GB GPU, one pass of Upscale holds 25 frames at 3840 x 2160 and 121 frames at 1920 x 1080. A longer shot runs in passes and windows, with overlapped frames where they blend.
- On a 16 GB GPU, Upscale above 2K on the long side can run out of VRAM.

**Export**

- Due to the 10-bit limit of FFmpeg's ProRes encoder, a movie that holds more than 10 bits is currently exported as 16-bit PNG frames.

**The matte, for Paint and Clean**

- A paint's matte can lose the painted object on some frames, when SAM 3.1 stops finding it: the composite then shows the plate there. The log's matte line names the frames where the object is hidden or out of the frame. Try another seed, another text prompt or another stroke.
- A painted object that leaves the frame and comes back loses its matte: the composite shows the plate there from then on. On 497 frames of `horse.mp4` at 1920 x 1080, the cow reached the frame's edge at frame 125, and the composite lost it once it was back in view. **Whole shot** in the **Matte strategy** menu keeps it.
- A painted object that comes back from behind something can get its matte back a few frames late: check those frames.
- A paint's matte can take in a change that the shot made right beside the painted object: check around the object.
- A paint's matte can keep a few small spots near the edit, where the regenerated frame differs slightly from the plate.
- A faint paint, such as thin smoke or a soft glow, can keep only its densest part: where the shot changes the plate too little, the composite shows the plate. Paint it denser or brighter, try another seed, or choose **Object and effects** in its **Matte strategy** menu.
- The shot preview's matte can cover parts of the object far from the edit. Export uses the full-size matte.

**Clean**

- A body part removed with Clean, such as a head, can reappear in the result.
- The check after Clean compares colours. An object of another colour that takes the removed object's place passes it, so look at the first frame.
- A Clean of a large area, such as branches across a window, can leave faint marks where the object was. They come from the regenerated frames: try another seed to change them.
- Where something moves right beside a cleaned object, the composite can show a regenerated part of it: check those frames.
- A paint added over a Clean edit can show a faint shape of the removed object again on some frames. Check the result frame by frame.

**Paint**

- A paint that replaces an object, such as a new arm over an arm, can leave thin pieces of the old object in view on later frames, where the old object reaches beyond the new one.
- On a long shot, a Paint can drift from the plate: on 1,001 frames of `horse.mp4` at 960 x 544 and 50 fps, the painted cow left the shot by frame 201, and a larger cow appeared later.

**Light**

- A shadow painted with Light comes out soft: a text prompt can ask for a deeper one.
- A relight can leave a thin light or dark edge along bright outlines.
- A Light edit with SDR to HDR can show a faint patch of light that floats over the plate. It comes from the Light edit, before SDR to HDR: try another seed or another stroke to change it.

## Contributing

Contributions are welcome. Fork the repository, make your change on a branch, and let GitHub Actions run the tests on your fork. Then open a pull request that says what changes, why, and how you tested it. [CONTRIBUTING.md](CONTRIBUTING.md) gives each step.

## Credits and licences

Paint a plate builds on the work of others:

- **[OpenRV](https://github.com/AcademySoftwareFoundation/OpenRV)** (Academy Software Foundation). The viewer follows it: colour tools, keys, wipe and Colour Inspector. **[OpenColorIO](https://github.com/AcademySoftwareFoundation/OpenColorIO)** does the colour.
- **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)** runs every step, with **[ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo)** by Lightricks.
- **The models**, each under its own licence:

| Model | What it does here | Licence |
| --- | --- | --- |
| [FLUX 3 Image Klein (int8), Qwen3-VL-4B-Instruct, FLUX 3 Image Klein's text encoder (int8), FLUX 3 Image Klein prompt upsampler, Qwen 3.5 9B (w4a8), FLUX 2 VAE](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) | Edits the first frame. Reads the caption for FLUX 3 Image Klein. Writes every edit's caption, and names the objects that SAM 3.1 looks for. Encodes and decodes FLUX 3 Image Klein's images | [FLUX Kommunity License v1.0](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/LICENSE.md) |
| [LTX 2.5 22B distilled (int8), Gemma 4 12B text encoder with LTX 2.5 projections (int8), LTX 2.5 video VAE (convolutional), LTX 2.5 audio VAE](https://huggingface.co/Lightricks/LTX-2.5) | Extends every edit to the whole shot; makes fluid shots and SDR to HDR. Reads LTX 2.5's prompts. Encodes and decodes LTX 2.5's video. Makes the audio latent that LTX 2.5 needs to sample video | [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) |
| [Ripple IC-LoRA v1.1 (WepeNerd)](https://huggingface.co/WepeNerd/LTX-Ripple) | Extends Paint and Light edits to the whole shot | [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) |
| [LTX 2.3 in-outpainting IC-LoRA (Lightricks)](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting) | Makes the clean plate pass | [LTX-2 Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2) |
| [SAM 3.1 (Meta)](https://huggingface.co/Comfy-Org/sam3.1) | Finds and tracks the objects you paint on | [SAM License](https://huggingface.co/Comfy-Org/sam3.1/blob/main/LICENSE) |
| [TAEHV tiny LTX decoder (taeltx2_3)](https://huggingface.co/Kijai/LTX2.3_comfy) | Decodes the live preview while a pass runs | [LTX-2 Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2) |
| [LTX 2.5 SDR-to-HDR IC-LoRA (Lightricks), Its fixed scene embeddings](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR) | Turns the SDR shot into scene-linear HDR. The prompt that SDR to HDR uses | [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) |
| [ainvfx-fluid IC-LoRA (AInVFX)](https://huggingface.co/AInVFX/ainvfx-fluid) | Turns painted keyframes into a fluid: smoke, fire, water and more | [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) |
| [SeedVR2 7B (fp16), ByteDance's video restoration model, SeedVR2's VAE](https://huggingface.co/Comfy-Org/SeedVR2) | Upscales the result to the size chosen, up to 3840 x 2160. Encodes and decodes the frames that SeedVR2 7B upscales | [Apache-2.0](https://huggingface.co/Comfy-Org/SeedVR2/blob/main/README.md) |

### The model files

Each file, with its page on Hugging Face and the folder it goes in, under ComfyUI's `models` folder. [`get_models.py`](get_models.py) downloads the same files to the same folders. Five files are optional: without `ainvfx-fluid.safetensors`, fluid shots switch off; without `ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors` and `ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors`, SDR to HDR; without `seedvr2_7b_fp16.safetensors` and `seedvr2_ema_vae_fp16.safetensors`, Upscale. The rest works without them.

| File | Folder | Size |
| --- | --- | --- |
| [`flux3-image-klein-int8-convrot.safetensors`](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/diffusion_models/flux3-image-klein-int8-convrot.safetensors) | `models/diffusion_models/` | 5.8 GB |
| [`qwen3vl_4b_int8_convrot.safetensors`](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/text_encoders/qwen3vl_4b_int8_convrot.safetensors) | `models/text_encoders/` | 4.9 GB |
| [`qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors`](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/text_encoders/qwen3.5_9b_flux3_prompt_upsampler_w4a8.safetensors) | `models/text_encoders/` | 6.7 GB |
| [`flux2-vae.safetensors`](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/vae/flux2-vae.safetensors) | `models/vae/` | 336 MB |
| [`ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors`](https://huggingface.co/Lightricks/LTX-2.5/blob/main/diffusion_models/ltx-2.5-22b-distilled-transformer-comfy-int8-convrot.safetensors) | `models/diffusion_models/` | 21.5 GB |
| [`gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors`](https://huggingface.co/Lightricks/LTX-2.5/blob/main/text_encoders/gemma4-12b-with-proj-ltx-2.5-comfy-int8-convrot.safetensors) | `models/text_encoders/` | 15.4 GB |
| [`ltx-2.5-video-vae-conv-bf16.safetensors`](https://huggingface.co/Lightricks/LTX-2.5/blob/main/vae/ltx-2.5-video-vae-conv-bf16.safetensors) | `models/vae/` | 1.5 GB |
| [`ltx-2.5-audio-vae-bf16.safetensors`](https://huggingface.co/Lightricks/LTX-2.5/blob/main/vae/ltx-2.5-audio-vae-bf16.safetensors) | `models/vae/` | 365 MB |
| [`LTX25_Ripple_v11.safetensors`](https://huggingface.co/WepeNerd/LTX-Ripple/blob/main/LTX25_Ripple_v11.safetensors) | `models/loras/` | 654 MB |
| [`ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors`](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting/blob/main/ltx-2.3-22b-ic-lora-in-outpainting-0.9.safetensors) | `models/loras/` | 1.3 GB |
| [`sam3.1_multiplex_fp16.safetensors`](https://huggingface.co/Comfy-Org/sam3.1/blob/main/checkpoints/sam3.1_multiplex_fp16.safetensors) | `models/checkpoints/` | 1.7 GB |
| [`taeltx2_3.safetensors`](https://huggingface.co/Kijai/LTX2.3_comfy/blob/main/vae/taeltx2_3.safetensors) | `models/vae_approx/` | 24 MB |
| [`ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors`](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR/blob/main/ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors) | `models/loras/` | 1.3 GB |
| [`ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors`](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR/blob/main/ltx-2.5-22b-ic-lora-sdr-to-hdr-scene-emb.safetensors) | `models/embeddings/` | 13 MB |
| [`ainvfx-fluid.safetensors`](https://huggingface.co/AInVFX/ainvfx-fluid/blob/main/ltx-2.5/ainvfx-fluid.safetensors) | `models/loras/` | 654 MB |
| [`seedvr2_7b_fp16.safetensors`](https://huggingface.co/Comfy-Org/SeedVR2/blob/main/diffusion_models/seedvr2_7b_fp16.safetensors) | `models/diffusion_models/` | 16.5 GB |
| [`seedvr2_ema_vae_fp16.safetensors`](https://huggingface.co/Comfy-Org/SeedVR2/blob/main/vae/seedvr2_ema_vae_fp16.safetensors) | `models/vae/` | 501 MB |

**The licences in short.** This table sums up what each licence asks. Each licence's own text is what binds you: read it before you use a model.

| Licence | Covers | What it asks of you |
| --- | --- | --- |
| [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) | LTX 2.5 and the models built on it: SDR to HDR, Ripple, ainvfx-fluid | Free use, commercial included, while your company's annual revenues stay under 10 million USD. From 10 million USD, a paid licence from Lightricks for any use other than non-commercial ones, such as testing, evaluation and research |
| [LTX-2 Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2) | The models built on LTX 2.3: the in-outpainting IC-LoRA, and the repository of the tiny decoder | The same threshold of 10 million USD of annual revenues |
| [FLUX Kommunity License v1.0](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/LICENSE.md) | FLUX 3 Image Klein, with its text encoder, prompt writer and VAE | Free non-commercial use. Commercial use of what it generates for a person or a company under 5 million USD of yearly revenue, affiliates included: the outputs pass a content filter or a review before you share them, and carry a notice that AI made them where the law asks for one. For any other commercial use, a licence from Black Forest Labs |
| [SAM License](https://huggingface.co/Comfy-Org/sam3.1/blob/main/LICENSE) | SAM 3.1 | Free use, commercial included. Share it only with a copy of the licence, and name it in any research publication that used it. No use that trade controls forbid, such as military or weapons uses |
| [Apache 2.0](https://www.apache.org/licenses/LICENSE-2.0) | SeedVR2 7B and its VAE; the prompt writer's system prompt in [`web/upsampler.json`](web/upsampler.json), Black Forest Labs' own text; Paint a plate's own code ([LICENSE](LICENSE)) | Free use, commercial included. Keep the licence and its notices with any copy |
| [MIT](https://github.com/madebyollin/taehv/blob/main/LICENSE) | [TAEHV](https://github.com/madebyollin/taehv), the tiny decoder, by madebyollin | Free use. Keep the licence notice with any copy |
| [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) | The example plates: synthetic shots made with LTX 2.5, MOSS-Image and FLUX 3 Image Klein | Credit AInVFX when you share them |

## Links

- [ainvfx.com](https://www.ainvfx.com): AI consulting for studios, and generative AI training for artists and studios
- The contest result: [article](https://www.ainvfx.com/blog/paint-a-plate-wins-open-weights-only-at-open-source-higgsfield-the-comfyui-contest/) · [Comfy's winners page](https://comfy.org/open-source-higgsfield/)
- The showcase, its new features and the open dataset of ainvfx-fluid: [article](https://www.ainvfx.com/blog/paint-a-plate-in-action-a-showcase-new-features-and-an-open-dataset-for-ainvfx-fluid/)
- ainvfx-fluid: [45-minute deep dive](https://youtu.be/Ho4tmJzEkIs) · [article](https://www.ainvfx.com/blog/paint-your-fluid-simulations-a-free-ltx-2-5-ic-lora-for-smoke-and-fire-in-comfyui/)
- Training: the [Generative AI Bootcamp for Film and TV](https://www.ainvfx.com/bootcamp/) and the [masterclass series](https://www.ainvfx.com/masterclass/)
- YouTube: the [AInVFX channel](https://www.youtube.com/@AInVFX) · the [showcase](https://youtu.be/EsL3O7WvBr4)
- Community: the [AInVFX Discord](https://discord.gg/6CKSa3b5ks)

Made by [AInVFX](https://www.ainvfx.com).
