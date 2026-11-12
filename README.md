<h1 align="center"><img src="web/brand/title.png" alt="AInVFX Paint a plate" width="100%"></h1>

**Winner of the Open Weights Only category and of the "VFX Workflow Built with LTX" bonus in Comfy's [Open Source Higgsfield](https://comfy.org/open-source-higgsfield/) contest** (November 2026). #OpenSourceHiggsfield

<table>
<tr>
<td align="center" width="50%"><a href="https://youtu.be/EsL3O7WvBr4"><img src="https://img.youtube.com/vi/EsL3O7WvBr4/maxresdefault.jpg" alt="The showcase of Paint a plate on YouTube: painted fire, smoke and water, a set extension, a green screen, a relight" width="100%"></a><br><b><a href="https://youtu.be/EsL3O7WvBr4">▶ Watch the showcase (4 minutes)</a></b><br>Shots made live with the app</td>
<td align="center" width="50%"><a href="https://youtu.be/Kt9O3Aw46-g"><img src="https://img.youtube.com/vi/Kt9O3Aw46-g/maxresdefault.jpg" alt="The demo of Paint a plate on YouTube: erase, add and relight on the first frame of a shot" width="100%"></a><br><b><a href="https://youtu.be/Kt9O3Aw46-g">▶ Watch the demo (2 minutes)</a></b><br>How the app works</td>
</tr>
</table>

Paint a plate is a visual effects tool that runs in [ComfyUI](https://github.com/comfyanonymous/ComfyUI), on your own machine, with open weights only. Paint on the first frame of a shot to erase, add or relight: the edit appears on that frame in seconds, then carries through the whole shot. The result comes back in the plate's own format, with every untouched pixel identical to the plate.

## What it can do

| | |
| --- | --- |
| **Erase** | Removes the object under your stroke. With **Whole object**, SAM 3.1 finds all of it: name it ("red umbrella") |
| **Paint** | Adds what you describe where you paint, in the style of the image. It follows your drawing's outline, pose and colours |
| **Light** | Relights the shot. Paint where the light comes from, in its colour. Paint in black to darken an area |
| **A fluid shot** | Starts from a blank plate. Paint flat colour blobs on a few keyframes: ainvfx-fluid turns them into smoke, steam, fire, explosions, dust, fog or clouds. The shot becomes the plate for every edit |
| **Review** | The viewer follows OpenRV: colour through OpenColorIO, the same keys, a wipe against the plate, the Color Inspector. |
| **Export** | Writes the result in the plate's own format (file type, bit depth, frame numbers, colour tags, timecode, audio, EXR layers) with its matte, as one zip. **ComfyUI graph** saves the whole scene as one ComfyUI workflow in the editor's own format: one group per step, each with a note, to drop on ComfyUI's canvas |
| **Deliver** | Readies a shot for delivery. Its bit-depth pass turns an SDR result into half-float EXR frames |

The limits that matter today: edits are painted on the first frame only; shots are tested up to 121 frames; edits are made at up to 1920 px on the long side; a plate can be up to 3840 x 2160.

Planned next, and not there yet: shots up to 20 seconds, plates at LTX 2.5's largest size (3840 x 2176), and every tool proven at up to 50 fps. Lightricks documents LTX 2.5 at up to 20 seconds for 24 or 25 fps and up to 1080p, and at up to 10 seconds for 48 or 50 fps or for larger sizes.

## What it needs

- **ComfyUI** v0.43.0 or newer, with [ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo). It is tested on ComfyUI v0.44.2: `tools/pins.sh` names the tested commits.
- **An NVIDIA GPU with 16 GB of VRAM at least; 32 GB or more recommended.** Under 24 GB the models load one at a time and LTX works in tiles, so each step takes longer. From 32 GB every step finishes at 1920 x 1088 and 121 frames. A 96 GB card is the fastest and takes plates above 2K.
- **64 GB of RAM.** This is what is tested.
- **62 GB of disk** for the models.

On a Mac or a smaller card, run it on Runpod (install option 3).

## Install

The steps are the same on Windows, macOS and Linux. **Run every command of this page with the Python that runs ComfyUI**: activate its virtual environment first, or call its own `python` (the table under "Get the models" names it for each setup). The system's Python does not have ComfyUI's packages.

### 1. With ComfyUI Manager (recommended)

1. In ComfyUI, open **Extensions > All Extensions** (with the Manager's legacy interface: **Manager > Custom Nodes Manager**). Search for **Paint a plate** and install **AInVFX Paint a plate** ([its Registry page](https://registry.comfy.org/nodes/ainvfx-paintaplate)). Install **ComfyUI-LTXVideo** the same way, then restart ComfyUI. With comfy-cli: `comfy node install ainvfx-paintaplate`.
2. Get the models (below).
3. With ComfyUI running, open this address in your browser:

   ```
   http://127.0.0.1:8188/extensions/ainvfx-paintaplate/paintaplate.html
   ```

If ComfyUI has no **Extensions** entry, its Manager is off: in ComfyUI's folder, run `pip install -r manager_requirements.txt`, then start ComfyUI with `--enable-manager`.

### 2. By hand

From your ComfyUI folder:

```sh
cd custom_nodes
git clone https://github.com/AInVFX/ainvfx-paintaplate
git clone https://github.com/Lightricks/ComfyUI-LTXVideo
python -m pip install -r ainvfx-paintaplate/requirements.txt -r ComfyUI-LTXVideo/requirements.txt
```

Then follow steps 2 and 3 above.

### 3. On Runpod

1. Accept the models' licences and create a Hugging Face read token (see "Get the models").
2. Start a pod: an RTX PRO 6000, the image `runpod/pytorch:1.0.2-cu1281-torch280-ubuntu2404`, a host with CUDA 13.0 or newer, a 150 GB container disk, ports 8188 and 8888, and your token in an `HF_TOKEN` environment variable.
3. In the pod's JupyterLab terminal:

   ```sh
   git clone https://github.com/AInVFX/ainvfx-paintaplate /workspace/ainvfx-paintaplate
   PLATES=1 bash /workspace/ainvfx-paintaplate/tools/runpod_start.sh
   ```

The script installs the tested ComfyUI and ComfyUI-LTXVideo, links this pack, runs the two download commands below and starts ComfyUI. It then prints the page's address. After a `git pull`, `bash tools/runpod_start.sh --restart` loads the new code. After an update, a scene opened again makes each of its jobs again once: a result made by another version is not taken back. Port 8188 has no password: anyone with the pod's address can use it.

## Get the models

One command downloads them, on a local machine and on a pod. Run it in the pack's folder, `custom_nodes/ainvfx-paintaplate`.

1. On Hugging Face, accept the licence of [FLUX 3 Image Klein](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy), of [LTX 2.5](https://huggingface.co/Lightricks/LTX-2.5), of the [in-outpainting IC-LoRA](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting) and, for SDR to HDR, of the [SDR-to-HDR IC-LoRA](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR). Then create a [read token](https://huggingface.co/settings/tokens).
2. Set the token: `export HF_TOKEN=hf_...` on Linux and macOS, `$env:HF_TOKEN = "hf_..."` in PowerShell on Windows.
3. Run:

   ```sh
   python get_models.py --list    # each file, its size, and whether it is in place
   python get_models.py           # downloads what is missing: 62 GB in all
   ```

| Your setup | The Python to use |
| --- | --- |
| Linux or macOS, ComfyUI installed by hand | `python`, with ComfyUI's virtual environment active |
| Comfy Desktop | `python`, in its terminal panel |
| Windows, portable ComfyUI | `..\..\..\python_embeded\python.exe` |

Each file goes to its folder under `models/`, at the revision that was tested. A file already in place is skipped, so you can run the command again. When Hugging Face refuses a file, its line says why and names the page to open. The last line counts the files downloaded, already there and missing. If your models live in another folder, name it: `python get_models.py path/to/models`. `--no-fluid` skips ainvfx-fluid and `--no-hdr` skips SDR to HDR: that feature is then off, and the rest works.

## Get the example plates

```sh
python get_plates.py           # 23 plates, 148 MB, into ComfyUI's input/plates
```

The plates are synthetic shots from the dataset [AInVFX/ainvfx-paintaplate](https://huggingface.co/datasets/AInVFX/ainvfx-paintaplate) (CC BY 4.0), and they need no token. **Open plate** lists them under `plates`. `python get_plates.py --only horse.mp4` downloads one plate, and `--list` names them all.

## A first edit

1. Press **Open plate**, then double-click a plate, for example `plates/horse.mp4`.
2. Type a few words at the top, for example "a campfire".
3. Pick **Paint**, **Erase** or **Light**, and paint on the first frame.
4. Press **Generate** (or Enter). The edit appears on the first frame, then the shot renders by itself: a quick preview first, then the full size.
5. Press **Export** to write the result in the plate's own format.

Each edit stays in History: click one to change it, and add as many as you need. **Save scene** keeps the plate and its edits on this ComfyUI.

Good to know:

- Erase a thin object by its full name: "floodlight pole" finds more than "floodlight".
- A shadow outside the erased object stays: erase it with a second stroke, **Whole object** off.
- To replace a head, paint the new head over the old one. An erased head comes back as a head.
- Paint additions on open ground. An addition painted across a foreground object breaks up during the shot.
- Judge an effect on the full-size shot, not on the fast preview.

**Where the rest is.** Press `?` for the keys. The right-click menu holds every action with its key, and the viewer's colour tools under **OCIO**. [`ARCHITECTURE.md`](ARCHITECTURE.md) explains how the pack works and how to change it. [`TESTING.md`](TESTING.md) describes every test.

## When something goes wrong

- **The log.** The **Log** button opens it. It records what happened, one line per fact, and the button is highlighted when an error arrives.
- **The memory profile.** Its line in the log says how the page uses your card. Small, under 24 GB of VRAM: models load one at a time and LTX runs in tiles. Medium: the edit models load when the page opens. Large, from 60 GB: LTX 2.5 loads at start too.
- **Stop.** Esc, or **Stop** beside Generate, stops what generates. What finished is kept, and Enter goes on from there.
- **ComfyUI's memory grows, or the page waits and nothing runs.** Start ComfyUI with `PAINTAPLATE_TRACE=1` in its environment. Every request then writes a line in ComfyUI's terminal when it starts and when it ends, with the memory the process holds. Add these lines to your report.
- **A model or a node is missing.** The page names it at start. `python get_models.py --list` shows what is in place.
- **Report a fault** in the [issues](https://github.com/AInVFX/ainvfx-paintaplate/issues), with the log's lines, your GPU and your ComfyUI version.

## How it works

Every step is a ComfyUI workflow from `web/workflows`: the page fills its slots and posts it to ComfyUI. A job made once is kept in a job index on disk, so the same edit on the same plate never runs twice. The table under Credits says what each model does.

## Questions from the community

**Why LTX 2.5?** Its weights are open and run on your own machine, under a licence that allows it, as the contest's Open Weights Only category asked. Its IC-LoRAs also let one video model make the erase, paint, light and fluid passes.

**How was ainvfx-fluid trained?** It is an IC-LoRA for LTX 2.5, trained in three stages on 176 synthetic scenes with the `ltx_iclora` recipe of [ainvfx-runpod](https://github.com/AInVFX/ainvfx-runpod). Its [model card](https://huggingface.co/AInVFX/ainvfx-fluid) and its [dataset card](https://huggingface.co/datasets/AInVFX/ainvfx-fluid) give the method, the data and the compute.

**Where do I get the app?** Here. ComfyUI Manager installs it from the [Comfy Registry](https://registry.comfy.org/nodes/ainvfx-paintaplate), which serves the code of this repository.

## Credits and licences

Paint a plate builds on the work of others:

- **[OpenRV](https://github.com/AcademySoftwareFoundation/OpenRV)** (Academy Software Foundation). The viewer follows it: colour tools, keys, wipe and Color Inspector. **[OpenColorIO](https://github.com/AcademySoftwareFoundation/OpenColorIO)** does the colour.
- **[ComfyUI](https://github.com/comfyanonymous/ComfyUI)** runs every step, with **[ComfyUI-LTXVideo](https://github.com/Lightricks/ComfyUI-LTXVideo)** by Lightricks.
- **The models**, each under its own licence. Read a model's licence before you use it.

| Model | What it does here | Licence |
| --- | --- | --- |
| [FLUX 3 Image Klein (int8), Qwen3-VL-4B-Instruct, FLUX 3 Image Klein's text encoder (int8), FLUX 3 Image Klein prompt upsampler, Qwen 3.5 9B (w4a8), FLUX 2 VAE](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy) | Edits the first frame. Reads the caption for FLUX 3 Image Klein. Writes every edit's caption. Encodes and decodes FLUX 3 Image Klein's images | [FLUX Kommunity License v1.0](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/LICENSE.md) |
| [LTX 2.5 22B distilled (int8), Gemma 4 12B text encoder with LTX 2.5 projections (int8), LTX 2.5 video VAE (convolutional), LTX 2.5 audio VAE](https://huggingface.co/Lightricks/LTX-2.5) | Carries every edit through the shot; makes fluid shots and SDR to HDR. Reads LTX 2.5's prompts. Encodes and decodes LTX 2.5's video. LTX 2.5's audio latent, which its video samples with | [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) |
| [Ripple IC-LoRA v1.1 (WepeNerd)](https://huggingface.co/WepeNerd/LTX-Ripple) | Carries paint and light through the shot | [LTX-2 Community License Agreement](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) |
| [LTX 2.3 in-outpainting IC-LoRA (Lightricks)](https://huggingface.co/Lightricks/LTX-2.3-22b-IC-LoRA-In-Outpainting) | Makes the erase pass | [LTX-2 Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2) |
| [SAM 3.1 (Meta)](https://huggingface.co/Comfy-Org/sam3.1) | Finds and tracks the objects painted on | [SAM License](https://huggingface.co/Comfy-Org/sam3.1/blob/main/LICENSE) |
| [TAEHV tiny LTX decoder (taeltx2_3)](https://huggingface.co/Kijai/LTX2.3_comfy) | Decodes the live preview while a pass runs | [LTX-2 Community License Agreement](https://github.com/Lightricks/LTX-2/blob/main/LICENSE) |
| [LTX 2.5 SDR-to-HDR IC-LoRA (Lightricks), Its fixed scene embeddings](https://huggingface.co/Lightricks/LTX-2.5-22b-IC-LoRA-SDR-To-HDR) | Turns the SDR shot into scene-linear HDR. The prompt SDR to HDR takes | [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) |
| [ainvfx-fluid IC-LoRA (AInVFX)](https://huggingface.co/AInVFX/ainvfx-fluid) | Turns painted keyframes on a blank plate into smoke, steam or fire | [LTX-2.x Community License](https://github.com/Lightricks/LTX-2/blob/main/LICENSE-2_x) |

Two of these licences set a revenue threshold. The LTX-2.x Community License asks a company with annual revenues of 10 million USD or more to buy a licence from Lightricks for any use other than testing, evaluation and non-commercial research. The FLUX Kommunity License lets a person or a company whose yearly revenue, affiliates included, is under 5 million USD use what the model generates commercially, if the outputs pass content filters or a review before they are shown, and carry a notice that AI made them where the law asks for one; for any other commercial use, Black Forest Labs sells a licence. The tiny decoder is [TAEHV](https://github.com/madebyollin/taehv) by madebyollin, under the MIT licence; Paint a plate downloads it from a repository whose card names the LTX-2 Community License Agreement. The upsampler's system prompts in `web/upsampler.json` are Black Forest Labs' own text (Apache 2.0). The example plates are synthetic, made with LTX 2.5, MOSS-Image and FLUX 3 Image Klein, and published under CC BY 4.0. Paint a plate's own code is under the Apache 2.0 licence.

## Links

- [ainvfx.com](https://www.ainvfx.com): AI consulting for studios, and generative AI training for artists and studios
- The contest result: [article](https://www.ainvfx.com/blog/paint-a-plate-wins-open-weights-only-at-open-source-higgsfield-the-comfyui-contest/) · [Comfy's winners page](https://comfy.org/open-source-higgsfield/)
- The showcase, with what changed up to version 1.11: [article](https://www.ainvfx.com/blog/paint-a-plate-in-action-a-showcase-new-features-and-an-open-dataset-for-ainvfx-fluid/)
- ainvfx-fluid: [45-minute deep dive](https://youtu.be/Ho4tmJzEkIs) · [article](https://www.ainvfx.com/blog/paint-your-fluid-simulations-a-free-ltx-2-5-ic-lora-for-smoke-and-fire-in-comfyui/)
- Training: the [Generative AI Bootcamp for Film and TV](https://www.ainvfx.com/bootcamp/) and the [masterclass series](https://www.ainvfx.com/masterclass/)
- YouTube: the [AInVFX channel](https://www.youtube.com/@AInVFX) · the [showcase](https://youtu.be/EsL3O7WvBr4) · the [demo](https://youtu.be/Kt9O3Aw46-g)
- Community: the [AInVFX Discord](https://discord.gg/6CKSa3b5ks)

Made by [AInVFX](https://www.ainvfx.com).
