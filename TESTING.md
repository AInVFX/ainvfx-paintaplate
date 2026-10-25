# Testing PaintAPlate

One command runs the suite. Levels that need more than Python skip themselves and say what they need.

```bash
pip install -r tests/requirements.txt
python -m unittest discover -s tests -v
```

| Module | What it proves | Needs |
| --- | --- | --- |
| `test_plateio` | EXR layers and header kept, ProRes round trip (codec, colour tags, timecode, audio), PNG, TIFF, DPX and EXR writers, frame names, 8n+1 padding | Python only |
| `test_mathops` | Alignment survives a relight, colour gain is clamped, grain level matches, relight keeps the plate's detail | Python only |
| `test_workflows` | `web/workflows` is current; every slot points at a real input; every class and input exists in ComfyUI and ComfyUI-LTXVideo source | source check: `COMFYUI_DIR` |
| `test_web` | Every element and workflow the page uses exists; the scripts parse; only the menu entry loads into the graph editor | `node` for parsing |
| `test_lint` | pyflakes on all Python, shellcheck on the scripts | `pyflakes`, `shellcheck` |
| `test_live` | A real ComfyUI loads the pack and serves the page; all six workflows validate; EXR, ProRes and 16-bit PNG plates export with untouched pixels and extra layers bit-identical; headless Chromium paints, erases, relights, picks and exports through the page | `COMFYUI_DIR`, `playwright` |

`tools/ci_comfyui.sh <folder>` prepares the ComfyUI for `test_live`: ComfyUI and ComfyUI-LTXVideo at the tested commits, this pack linked in, and empty model files from `tools/placeholders.py`. No model runs: model workflows are cancelled right after ComfyUI validates them, and the browser test swaps them for stand-ins made of core nodes. GitHub Actions (`.github/workflows/tests.yml`) runs the Python level, then the ComfyUI level, on every push.

To run one module, work from `tests/`: `python -m unittest -v test_web`.

## On a GPU machine

These run the real models; `tools/pod_setup.sh` prepares a machine.

- `tests/ui_live.py --comfy <ComfyUI> --url http://127.0.0.1:8188 --path plates/<shot> --think 8 --out <folder> --strokes '<json>'` drives the real page and records a timed mark for every stage, screenshots and the exported files. Each stroke is `[key, words, [[x, y], ...], pick, brush size]`, with x and y from 0 to 1 on the frame.
- `tests/gpu_bench.py` times single steps: `edit` (Klein previews and refine, `REFINE_STEPS`), `shot` (Ripple, replace against prepend), `export`, `mp4` (an H.264 copy of an EXR plate) and `anime` (a test plate made with FLUX 3 Image Klein and LTX 2.5).

Scenarios run on 25 October 2026 on an RTX PRO 6000: an EXR street shot (add, erase, relight), an EXR desk close-up (erase, add), relight only, an H.264 video plate (erase) and a generated anime plate (erase, add, relight).
