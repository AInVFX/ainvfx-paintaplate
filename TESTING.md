# Testing PaintAPlate

One command runs the suite. A test whose package or tool is missing skips itself and says what to install. In CI (GitHub Actions sets `CI=true`) the same miss fails instead, so a broken install never passes as skipped.

```bash
pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
```

Where the system Python refuses `pip` (Ubuntu, Debian), install into a virtual environment first: `python3 -m venv ~/.venvs/paintaplate && . ~/.venvs/paintaplate/bin/activate`. Every package in `tests/requirements.txt` has wheels for Python 3.12 to 3.14.

| Module | What it proves | Needs |
| --- | --- | --- |
| `test_plateio` | EXR layers and header kept, ProRes round trip (codec, colour tags, timecode, audio), PNG, TIFF, DPX and EXR writers, frame names, 8n+1 padding, sequences with missing frames or on twos keep their frame numbers, a black ProRes 4444 canvas, and a ProRes 4444 plate written again; a frame's own values from half and float EXR (`read_float`); PNG frames written in parallel, every pixel exact; the review's half-float EXR frames, every value exact; the page's movies; untouched YUV samples taken from the source; a frame pattern naming one sequence of a mixed folder, and the folder scan of the plate browser (core's `ComfyUI_00001_.png` names grouped, an image alone counted, not listed); an animated WebP as a video plate; HDR video tags guessing the colour space | `tests/requirements.txt` |
| `test_mathops` | Alignment survives a relight, grain level and seam field, dilate, relight frame, relight keeps the plate's detail, push-pull fill, steady masks, a composite whose edge holds still and matches the plate, the keyframe control video of a fluid shot, the composite's resize against scipy's zoom, Follow Matte (the first-frame mask when SAM returns none, the last matte where it stops, a flame it never saw kept from the shot's changes, stray objects left out, an object found again after a gap, a far piece of SAM's mask left out), Level Fill, and the colour of a new light kept smooth over a channel with almost no light | `tests/requirements.txt` |
| `test_ocio` | The built-in studio config, its model space and scene-linear space, the familiar view, the colour families of RV's menu; unknown configs refused (never a path from the page); the plate's colour space guessed from the file, then from the config's file rules; conversions into the model space equal to core ComfyUI's sRGB output, written again from its equations (SDR frames and a batch with a highlight at 6.0); `@linear` there and back exactly, values above 1.0 and below 0 included; alpha untouched; the viewer's GLSL ES 3.0 with its lookup tables, and the identity check that lets an 8-bit frame be drawn as it is | `tests/requirements.txt` |
| `test_routes` | The download route reads only run folders under output/paintaplate, never follows a symbolic link, zips the parts asked for, reuses a current zip and rebuilds a stale one; the plate browser lists input and output with their subfolders, videos, animated images and frame patterns, never a text file, a link or anything outside, and makes each thumbnail once (core's video, image and animated WebP outputs included); a plate's details name its colour space in the OCIO config; scenes are saved and listed on this ComfyUI, and their names are safe; the blank plate route; the job index; a plate's size and time change when the plate does; the frame route keeps values above 1.0 and below 0, reads a render's review frames by their pattern and refuses paths outside; the handlers, the OCIO routes among them | `tests/requirements.txt` |
| `test_workflows` | `web/workflows` is current; each file opens in ComfyUI as an API workflow; every slot and output the page uses exists; every class and input exists in ComfyUI and ComfyUI-LTXVideo source; `get_models.py` downloads every model file they load at a pinned revision, and the pod setup runs it | source check: `COMFYUI_DIR` |
| `test_web` | The page's modules import only names that exist, every element they look up exists, only the menu entry loads into the graph editor, the scripts parse, the page and Python drop the same optional links and share the Ripple sentence, and `tests/js` passes | Node.js 20 or newer for the last three |
| `tests/js` | Node.js's own test runner: sizes, time left, captions, the upsampler's request and the reconciled answer, the erase pass's prompt, the render queue's order and the steps Generate may stop, the job index key, the full size's first stage, the shot prompt, the whole-object picker, the paint matte's seed, edit dependencies, the frame cache's ranking, the preview sizes a plate divides into, the viewer's colour, the blank plate's sizes and the keyframe grid, which edit a stroke goes to, the OCIO menu's family tree, the plate browser's order, filter and breadcrumbs, frame patterns (`logic.mjs`); the outputs every workflow names, the review's and the export's included; optional links on the real workflow files; the frame cache's budget and eviction (`frames.mjs`); outputs read only once ComfyUI has recorded the prompt (`comfy.mjs`); a scene joined into one ComfyUI workflow whose links all land, with each model loaded once (`graph.mjs`) | Node.js 20 or newer |
| `test_lint` | pyflakes on all Python, shellcheck on the scripts | `tests/requirements.txt` (it brings both) |
| `test_ui_mock` | The page in headless Chromium or Chrome against `tests/mock_comfy.py` (next section) | `playwright` with a browser (skipped without it) |
| `test_live` | A real ComfyUI loads the pack and serves the page; every workflow validates; EXR, ProRes and 16-bit PNG plates ingest, composite, review and export: the review of an image sequence writes one half-float EXR frame per frame whose untouched pixels are the plate's own values, a video plate's review writes none; the export keeps untouched pixels and extra layers bit-identical, with a matte per frame and a zip with the parts asked for; headless Chromium opens a plate, plays it, paints, erases and relights, bypasses an edit, waits for the full quality, wipes, then exports and downloads the zip | `COMFYUI_DIR`, `playwright` |

`node --test tests/js/*.test.mjs` runs the JavaScript tests alone. To run one Python module, work from `tests/`: `python -m unittest -v test_ocio`.

## The page against the mock ComfyUI

`tests/mock_comfy.py --plate` serves the page with a stand-in ComfyUI: the same HTTP and WebSocket API, numpy instead of models, step previews, progress and interrupts, and the pack's own routes (the browser, thumbnails, scenes, OCIO, the job index, the download). `--plate` writes a 1280 x 704 test plate to `input/plates/desk.mp4`. The stand-in writes VP9 previews, because Playwright's Chromium cannot decode H.264; Chrome, Edge, Safari and Firefox can. `python tests/ui_mock.py` runs the page's whole behaviour against it in a few minutes (set `PLAYWRIGHT_CHANNEL=chrome` to drive Google Chrome). It checks, in order:

- **The Open dialog**: the plate browser opens input/plates with its breadcrumbs, one click reads the plate and its colour space, the four tabs show one source each;
- **Colour**: an EXR through the frame route and the viewer's OCIO program, 4.0 still white two stops down, 0.5 from 188 to 99;
- **Edits and renders**: strokes that wait for Generate, Enter again with nothing changed running nothing, Generate making the full quality and nothing for compositing software, then Export writing the result and its matte and downloading the zip; the shot on paused frames, frame 0 included; the erase's matte and clean plate used again when the paint under it is removed; a removal that stops no render step; the preview of the edits on show before any full-size step; undo taking kept results back; numbering, selecting and retyping an edit; Ctrl+Enter; the preview menu; the viewer's colour and the right-click menu; the log; a whole-object erase; one edit at a time;
- **A fluid shot** from a blank plate: keyframes painted, copied, pasted, dragged, deleted and undone, generated once for the same keyframes and words, then edit 1 under a paint edit, saved as a scene on the server and opened again with every job from the job index;
- **A plate's scene** with a paint and a whole-object erase, saved and opened again with every job from the job index;
- **OCIO**: from the right-click menu, another view applies at once, and back while the shot plays; another File Color Space shows at once and opens the plate again in it;
- **Keys**: every key the right-click menu shows is in the Keys dialog, and every documented key does what the dialog says;
- **Out of memory**: the mock's `/mock/oom` makes the next fluid pass fail with ComfyUI's own message; the page asks ComfyUI to free its memory, waits until `/system_stats` shows it released, then makes the shot (posted at once, the retry ran before the free on a GPU, 29 Oct);
- **Phones**, upright and on its side: the plate opened again from the job index, the frame, Generate, the transport, the status line, the log and the menu sheet fit the screen.
- SDR to HDR: no switch for a video plate; on by default for an EXR plate, where the step runs after the full-size shot and before the full quality; switched off, the next render leaves it out; a 16-bit blank plate's fluid shot goes through it and opens as an EXR plate.
- The layout: the side panel and the log resize from their dividers, the stage keeps its room, a new session keeps the sizes, a double-click gives the first sizes back.

## CI

`.github/workflows/tests.yml` runs three jobs side by side on every push, none repeating another's tests:

| Job | What it runs |
| --- | --- |
| Unit tests | The whole suite with no browser and no ComfyUI: the Python modules, the Node tests and the linters. |
| Page tests | `test_ui_mock`: the page against the mock ComfyUI. |
| Live tests | `tools/ci_comfyui.sh` builds ComfyUI and ComfyUI-LTXVideo at the pins on CPU, with empty model files from `tools/placeholders.py`; then `test_live` and the source check of `test_workflows`. No model runs: model workflows are cancelled once ComfyUI has validated them, and the browser test swaps them for stand-ins made of core nodes. |

pip downloads are cached, and the browser jobs drive the runner's own Google Chrome when it has one, so no browser is downloaded.

## On a GPU machine

These run the real models; `tools/runpod_start.sh` sets up a Runpod pod and starts ComfyUI, and with `PLATES=1` adds the test plates from the Hugging Face dataset `AInVFX/ainvfx-paintaplate` (`tools/get_plates.sh` does it alone).

- `tests/ui_live.py --url http://127.0.0.1:8188 --path plates/<shot> --think 8 --out <folder> --strokes '<json>' --channel chrome` drives the real page and records a timed mark for every stage, screenshots, the page's log and the downloaded zip. Each stroke is `[key, words, [[x, y], ...], brush size, options]`, with x and y from 0 to 1 on the frame; the options are `{"whole": false}` (an erase painted as is) and `{"color": "#d32f2f"}` (a swatch). `--fluid '<json>'` makes a fluid shot from a blank plate instead of opening a plate: `{"size": [1280, 704], "fps": 24, "frames": 121, "words": "...", "keys": [[frame, colour, [[x, y], ...], brush size], ...]}`, where a frame is 0, -1 for the last frame, or 8k + 1. Several strokes on one frame build one keyframe, so flat zones for sky and ground can sit under the fluid. With `--strokes`, the shot then becomes the plate and takes them. Playwright's own Chromium cannot play H.264: install Google Chrome with `python -m playwright install chrome` and pass `--channel chrome`.
- `tests/gpu_bench.py` times single steps: `edit` (Klein previews and refine, `REFINE_STEPS`), `shot` (Ripple, replace against prepend), `export`, `mp4` (an H.264 copy of an EXR plate) and `anime` (a test plate made with FLUX 3 Image Klein and LTX 2.5).
