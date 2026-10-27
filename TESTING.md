# Testing PaintAPlate

One command runs the suite. A test whose package or tool is missing skips itself and says what to install. In CI (GitHub Actions sets `CI=true`) the same miss fails instead, so a broken install never passes as skipped.

```bash
pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
```

Where the system Python refuses `pip` (Ubuntu, Debian), install into a virtual environment first: `python3 -m venv ~/.venvs/paintaplate && . ~/.venvs/paintaplate/bin/activate`. Every package in `tests/requirements.txt` has wheels for Python 3.12 to 3.14.

| Module | What it proves | Needs |
| --- | --- | --- |
| `test_plateio` | EXR layers and header kept, ProRes round trip (codec, colour tags, timecode, audio), PNG, TIFF, DPX and EXR writers, frame names, 8n+1 padding, sequences with missing frames or on twos keep their frame numbers | `tests/requirements.txt` |
| `test_mathops` | Alignment survives a relight, grain level and seam field, fill hole and dilate, relight frame (the same light from half-size inputs), relight keeps the plate's detail, push-pull fill, steady masks, a composite whose edge holds still and matches the plate (a shorter matte holds its last frame), and box mattes that hide an erased object's outline | `tests/requirements.txt` |
| `test_routes` | The download route reads only run folders under output/paintaplate, never follows a symbolic link, zips the parts asked for, reuses a current zip and rebuilds a stale one | `tests/requirements.txt` |
| `test_workflows` | `web/workflows` is current; each file opens in ComfyUI as an API workflow; every slot and output the page uses exists; every class and input exists in ComfyUI and ComfyUI-LTXVideo source | source check: `COMFYUI_DIR` |
| `test_web` | The page's modules import only names that exist, every element they look up exists, only the menu entry loads into the graph editor, the scripts parse, the page and Python drop the same optional links, and `tests/js` passes | Node.js 20 or newer for the last three |
| `tests/js` | Node.js's own test runner: sizes, time left, captions, the upsampler's request and the reconciled answer, the shot prompt, the whole-object picker, edit dependencies and the frame cache's ranking (`logic.mjs`), optional links on the real workflow files, the frame cache's budget and eviction (`frames.mjs`), outputs read only once ComfyUI has recorded the prompt (`comfy.mjs`) | Node.js 20 or newer |
| `test_lint` | pyflakes on all Python, shellcheck on the scripts | `tests/requirements.txt` (it brings both) |
| `test_live` | A real ComfyUI loads the pack and serves the page and the download route; every workflow validates; EXR, ProRes and 16-bit PNG plates ingest, composite and export with untouched pixels and extra layers bit-identical, a matte per frame and a zip with the parts asked for; headless Chromium opens a plate, plays it, paints, erases and relights, bypasses an edit, wipes, and downloads the zip through the Export dialog | `COMFYUI_DIR`, `playwright` |

`node --test tests/js/*.test.mjs` runs the JavaScript tests alone. To run one Python module, work from `tests/`: `python -m unittest -v test_web`.

`tools/ci_comfyui.sh <folder>` prepares the ComfyUI for `test_live`: ComfyUI and ComfyUI-LTXVideo at the tested commits, this pack linked in, and empty model files from `tools/placeholders.py`. No model runs: model workflows are cancelled right after ComfyUI validates them, and the browser test swaps them for stand-ins made of core nodes. GitHub Actions (`.github/workflows/tests.yml`) runs the Python level, then the ComfyUI level, on every push.

## How the code is laid out

- `nodes.py`: the six ComfyUI nodes, thin wrappers that convert tensors and call `plateio` (files) or `mathops` (pixels), both tested without torch.
- `routes.py`: the zip download, plain functions plus `setup()`, called from `__init__.py`.
- `tools/build_workflows.py`: writes `web/workflows`. Slots, outputs and the progress node live in each node's `_meta`.
- `web/`: `app.mjs` (the app and its tuning block), `comfy.mjs` (the ComfyUI client, no DOM), `logic.mjs` (pure rules), `canvas.mjs` and `frames.mjs` (the frame cache, after OpenRV's FBCache).

## Working on the page without a GPU

`tests/mock_comfy.py --plate` serves the page with a stand-in ComfyUI: the same HTTP and WebSocket API, numpy instead of models, step previews, progress and interrupts, and the pack's own download route. `--plate` writes a 1280 x 704 test plate to `input/plates/desk.mp4`; open it from the page with the path `plates/desk.mp4`. The stand-in writes VP9 previews, because Playwright's Chromium cannot decode the H.264 MP4 that ComfyUI writes; Chrome, Edge, Safari and Firefox can.

## On a GPU machine

These run the real models; `tools/runpod_start.sh` sets up a Runpod pod and starts ComfyUI.

- `tests/ui_live.py --comfy <ComfyUI> --url http://127.0.0.1:8188 --path plates/<shot> --think 8 --out <folder> --strokes '<json>'` drives the real page and records a timed mark for every stage, screenshots and the downloaded zip. Each stroke is `[key, words, [[x, y], ...], brush size]`, with x and y from 0 to 1 on the frame.
- `tests/gpu_bench.py` times single steps: `edit` (Klein previews and refine, `REFINE_STEPS`), `shot` (Ripple, replace against prepend), `export`, `mp4` (an H.264 copy of an EXR plate) and `anime` (a test plate made with FLUX 3 Image Klein and LTX 2.5).
