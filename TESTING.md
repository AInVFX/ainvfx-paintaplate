# Testing PaintAPlate

Four levels, cheapest first. The first three need no GPU and no models.

| Level | Command | What it proves |
| --- | --- | --- |
| Unit | `python tests/test_plateio.py && python tests/test_mathops.py` | EXR layers and header kept, ProRes round trip (codec, colour tags, timecode, audio), still encoders, frame naming, alignment, grain, colour, relight maths |
| Static | `python tools/check_workflows.py <ComfyUI> <ComfyUI-LTXVideo>` | Every class and input name in the five workflows exists in source |
| Live, CPU | `python tests/comfy_live.py --comfy <ComfyUI> --python <its python>` | A real ComfyUI loads the pack and serves the page; its validator accepts all five workflows; `ingest` and `export` run end to end on EXR, ProRes and 16-bit PNG plates, with untouched pixels and extra layers bit-identical |
| UI, CPU | `python tests/ui_live.py --comfy <ComfyUI> --python <its python>` | Headless Chromium drives the real page: open a plate, paint, erase, light, pick options, idle-time shot, mattes and export. Model steps use core-node stand-ins with the same slots |
| GPU | a pod with the models, then the same live test with the models run | Speed and quality of Klein, Ripple and SAM 3.1 on real plates |

For the CPU levels, model files can be empty placeholders with the right names: the live test cancels model workflows right after ComfyUI validates them.
