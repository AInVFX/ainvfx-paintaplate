# AInVFX PaintAPlate: architecture

This document explains what PaintAPlate does, how it is built and where each part lives, for anyone who maintains the code. It describes version 0.5.0. `TESTING.md` covers the tests.

## 1. What PaintAPlate does

A **plate** is the source footage of a shot: a video file (MP4, MOV, MKV, MXF, WebM, or an animated WebP or GIF) or an image sequence (a folder of EXR, PNG, TIFF or DPX frames, or one sequence in a folder named by its frame pattern, such as `shot.####.exr`). You paint on the plate's first frame, and the change carries through the whole shot. There are three tools:

- **Paint** adds something new where you paint, from your words: a fire, a boat, a lamp.
- **Erase** removes an object. With **Whole object** on (the default), SAM 3.1 finds the whole object under the strokes, by its name when you type one.
- **Light** relights the scene from where you paint, in the colour of the brush.

Generate (the button at the end of the prompt bar, or Enter) starts an edit and its render. FLUX 3 Image Klein makes the edit on the first frame. The shot then renders by itself: LTX 2.5 carries the edits through every frame, SAM 3.1 tracks the changed areas, Follow Matte keeps every generated element inside the matte, and the result is composited onto the plate. A quick preview comes first, then the full-size passes, then the **review**: the full-size composite at the plate's own quality, which the viewer plays from then on. Generate never makes a result twice: an edit whose strokes, words, seed and Whole object switch have not changed keeps its result.

**Export** writes the result for compositing software, only when you press it: the plate's own format (file type or codec, bit depth, frame numbers, colour tags, timecode, audio, EXR layers), with every pixel outside the edits the exact source pixel, and the matte. Nothing is written for compositing software while you iterate.

**Colour** is managed with OpenColorIO, as OpenRV manages it. The config is the one `$OCIO` names, as in RV, else OCIO's built-in studio config (ACES 2.1, with the camera log spaces). Each plate has one colour space in that config, its **file colour space**: read from the file when the plate opens, and changed from the right-click OCIO menu. The viewer shows the plate through a display and a view; the models see the plate converted to the model space; the export converts the edited pixels back to the plate's colour space.

A **fluid shot** starts from a blank plate instead. You paint flat colour keyframes: light grey for smoke, white for steam, orange and yellow for fire, and optional flat zones for sky and ground. AInVFX's ainvfx-fluid IC-LoRA, trained on synthetic data (dataset `AInVFX/ainvfx-fluid`), turns them into smoke, steam, fire, explosions, dust, fog or clouds in one LTX 2.5 pass. The result then becomes the plate for every edit.

## 2. Words used here and in the code

| Word | Meaning |
| --- | --- |
| Plate | The source footage of a shot. |
| First frame | Frame 0 of the plate, where every edit is painted. In the code, `S.original` is the plate's first frame in the model space, and `S.hero` is the first frame with every active edit stacked on it. |
| OCIO config | The OpenColorIO config in use: `$OCIO`, else a built-in config (`ocio://studio-config-latest` by default). `S.ocio.config` names it. |
| File colour space | The colour space a plate's values are in, by its name in the OCIO config (`S.plate.cs`). RV calls it File Color Space. The viewer, the models and the export all use it. |
| Model space | The sRGB-encoded Rec.709 the models were trained on: the config's `sRGB Encoded Rec.709 (sRGB)` (alias `srgb_tx`, role `texture_paint`). In workflows, `@model`; `@linear` is the same space in linear light. |
| Display and view | How the viewer shows scene-linear values on the screen, such as `sRGB - Display` and `Un-tone-mapped`. The viewer only: they never change a result. |
| Edit | One change painted on the first frame: its tool (paint, erase or light), its strokes, its words and its seed. The History panel lists the edits, numbered from 1 at the bottom. |
| Draft | The edit being drawn, before Generate (`S.draft`). |
| Current edit | The edit that new strokes, new words and the Whole object switch change: the edit just started, or the one picked in History (`S.selected`). The Editing tag in the prompt bar names it. |
| New edit | The action that closes the current edit, so the next strokes start a separate one: the N key, the button at the end of the prompt bar, or the right-click Edit menu. Picking another tool does the same. |
| Generate | The button at the end of the prompt bar, or Enter: it starts the draft or the changed current edit, then the render. Pressed with nothing changed, it runs nothing. Ctrl+Enter tries another seed. |
| Patch | The result of an edit: the new pixels of the first frame, as an RGBA image. |
| Pass | One run of a model. A Klein edit runs a quick pass at 768 px, then a full-size pass. |
| Working size | The size edits are made at: the plate's size, at most 1920 px on the long side, in multiples of 32. |
| Preview size | The size of the quick render you watch first. Fast (640 px on the long side) is the default; the menu offers other sizes computed from the plate, and Full. |
| Review | The full-size composite at the plate's quality, made right after the full-size passes. A video plate's review is a movie of its own values; an image sequence's review is also half-float EXR frames the viewer reads at full precision. Workflow `review`. |
| Export | The result written for compositing software, only when Export is pressed. Workflow `export`. |
| Matte | A black and white mask per frame: where an edit changed the shot. |
| Erase pass | The plate with every erased object removed in every frame (the clean plate), made by LTX 2.5 with Lightricks' in-outpainting IC-LoRA. Workflow `clean`; at full size, in Lightricks' two stages: `clean` at half the working size, then `cleanup`. |
| Shot | The plate regenerated by LTX 2.5 with WepeNerd's Ripple IC-LoRA, from the edited first frame. It carries paint and light. Workflow `shot`. |
| Composite | The shot's new pixels inside the mattes, over the plate's own pixels everywhere else. |
| IC-LoRA | A LoRA for LTX that reads a reference video next to the prompt (an in-context LoRA). |
| Prompt writer | FLUX 3 Image Klein's own prompt upsampler (Qwen 3.5 9B). It writes each edit's caption in Black Forest Labs' format. |
| Workflow | A ComfyUI graph in API format, in `web/workflows`. The page runs every step of its work as one. |
| Slot | A named input of a workflow that the page fills before it posts it: a path, a seed, a caption, a colour space. |
| Job kind | The group a posted workflow belongs to: `edit`, `snap`, `prefetch`, `warm`, `fluid`, and the render's kinds `clean`, `shot`, `matte`, `comp`, `review` and `export`. A cancel stops jobs by kind. |

## 3. The big picture

```
BROWSER   web/paintaplate.html, served by ComfyUI at /extensions/ainvfx-paintaplate/paintaplate.html
  app.mjs ........ state, interface, edits, the render pipeline, the Open dialog, OCIO (the largest file)
  logic.mjs ...... pure rules: workflows as data, sizes, captions, dependencies, colour, keyframes, edit targets,
                   the OCIO menu tree, the plate browser's order and breadcrumbs
  graph.mjs ...... the whole scene as one ComfyUI workflow
  frames.mjs ..... the decoded-frame caches, after OpenRV: 8-bit frames, and full-precision frames
  display.mjs .... the viewer's colour: one WebGL2 program per colour space and view, with OCIO's GLSL
  canvas.mjs ..... canvas helpers
  comfy.mjs ...... the only module that talks to ComfyUI
        |  HTTP and WebSocket, to the server that serves the page
        v
COMFYUI SERVER
  core API ....... /prompt /ws /history /interrupt /queue /free /upload/image /view /object_info /system_stats
  routes.py ...... /paintaplate/browse  thumb  stat  frames  blank  jobs  scenes  ocio  ocio/shader  download
  web/workflows .. 13 API workflows, written by tools/build_workflows.py
        |  core nodes, ComfyUI-LTXVideo nodes and the 11 PaintAPlate nodes
        v
NODE PACK (Python)
  nodes.py ....... 11 thin nodes: they convert tensors, then call
  plateio.py ..... files: probe, read, write, scan a folder (numpy, PyAV and OpenEXR; no torch)
  mathops.py ..... pixels: fit, relight, mattes, keyframes (numpy and scipy; no torch)
  ocio.py ........ colour: the config, conversions, the viewer's GLSL (numpy and PyOpenColorIO; no torch)
  folders.py ..... where paths from the page may point: ComfyUI's input and output folders
        v
MODELS (about 60 GB)
  FLUX 3 Image Klein (int8) and its prompt writer; LTX 2.5 (22B distilled, int8) with the Ripple,
  in-outpainting and ainvfx-fluid IC-LoRAs; SAM 3.1; the tiny LTX decoder taeltx2_3
```

## 4. Design rules

These rules keep the code small and easy to change. Follow them in every change.

1. **All GPU work is a ComfyUI workflow.** The page loads a workflow file, fills its slots and posts it. The 11 PaintAPlate nodes only do what core ComfyUI cannot. So the app runs on any ComfyUI, and a Comfy API deployment stays possible.
2. **Workflows are generated.** `tools/build_workflows.py` writes `web/workflows`. Nobody edits the JSON by hand: a test fails when the files and the generator disagree.
3. **Each workflow describes itself.** In each node's `_meta`, `slots` maps the node's inputs to slot names, `output` names an output the page reads, and `progress` marks the node whose progress bar stands for the whole workflow.
4. **Optional links.** Some links exist only when the page has something to send: a matte to composite with, words to search by, a relit frame, an image sequence's review frames. When their slots stay empty, the page drops the link and every node that fed it. The rule is written twice, as `OPTIONAL` in `logic.mjs` and in `build_workflows.py`, and a test keeps the two equal.
5. **Pure code is tested without heavy dependencies.** `plateio.py`, `mathops.py` and `ocio.py` need neither torch nor ComfyUI. `logic.mjs`, `graph.mjs` and `frames.mjs` run in Node. `nodes.py` only converts tensors and calls them; `routes.py` is plain functions plus `setup()`.
6. **One edit at a time.** A stroke goes to the draft, else to the current edit if it has the same tool, else to a new edit (`strokeTarget` in `logic.mjs`). Another tool, or New edit, closes the current edit (`toolEndsEdit`). Undo keeps the current edit while it exists.
7. **Nothing made is lost, and nothing is made twice.** Changing the edit being generated (strokes, words, the switch) stops its Klein pass. No render stops for that, nor for a bypass, an undo, a removal or a new edit: renders go on, and what they make stays. Results are kept per set of edits and per preview size (`S.renders`, keyed by `S.heroKey`), and what the erases make per set of erases (`S.erases`). Every finished job is also recorded in the job index on disk (`routes.py`, `output/paintaplate/jobs`), by the hash of its workflow file, the plate (path, size and time) and its values. A job with the same hash takes those files back instead of running, in this session or a later one on the same machine. A job is recorded only when every file it made is in the output folder (`recordable` in `comfy.mjs`, the rule `routes.write_job` enforces).
8. **One colour space per plate.** The plate's file colour space is a name in the OCIO config. The viewer converts from it, the workflows convert from it to the model space, and the export converts the edited pixels back to it. Changing it makes the first frame and the edits again in it; the job index keeps the earlier results, so switching back takes them at once.
9. **Previews may trade quality for speed. The review matches the plate, and the export never trades.** The review of a video plate is a movie of its own values at the working size; the review of an image sequence is also its half-float EXR frames, which the viewer compares with the plate's own frames at full precision.
10. **Paths stay inside ComfyUI.** Every path from the page resolves under ComfyUI's input or output folder (`folders.plate_path`), symbolic links are refused, and absolute paths need `PAINTAPLATE_ALLOW_ABSOLUTE=1`.
11. **One home per value.** Sizes, delays and budgets: the tuning block at the top of `app.mjs`. Model files: the constants at the top of `build_workflows.py`. Tested ComfyUI and ComfyUI-LTXVideo commits: `tools/pins.sh`. Model files and revisions: `get_models.py`.
12. **A log line for every wait.** Each step a person waits for writes one line in the page's log: what runs, with which values, and how long it took.

## 5. The life of an edit

1. **Open a plate** (`openPlate`). The route `/paintaplate/stat` reads the plate's size, time and spec, and guesses its file colour space in the OCIO config (`ocio.guess`: the EXR's chromaticities or the video's colour tags, then the config's file rules). The `ingest` workflow decodes the plate once. It saves the first frame in the model space (at most 1920 px on the long side), a playback proxy and the plate spec. A video plate's proxy keeps its own values at the working size, so the viewer converts it as it converts the plate; an image sequence's proxy is in the model space at 960 px, for playback while its own frames load. The page then sets its sizes: the working size, 768 px for quick passes, 960 px for tracking (640 px for erase mattes) and the preview size.
2. **Paint.** Each edit draws on two canvases: `paint` (what Klein sees, for a paint) and `mask` (where the edit may act). `strokeTarget` decides which edit a stroke joins. I (or the pipette by the swatches) picks a colour from the frame for the brush (`pickedColor`).
3. **Prepare while the strokes rest** (`prepareSoon`, then `prefetch` and `prepare`). `takeInputs` reads the words and the Whole object switch into the edit. For an erase with Whole object, the `snap` workflow asks SAM 3.1 for the object by name and from up to five stroke points, and `pickObjects` keeps the right masks. Then the `prompt` workflow asks the prompt writer for a caption, and `reconcile` puts the page's boxes back into it. An erase sends one locked box per painted part (`paintBoxes`), and a caption that removes something the paint does not cover gives way to the page's own (`erasesPaint`). A new stroke cancels this work.
4. **Run the edit** (`launch`, then `generate`) when you press Generate (Enter). An edit whose strokes, words, seed and switch match a result it already made takes that result back (`reuse`, up to `RESULTS_KEPT` results per edit). Ctrl+Enter tries another seed. The `edit` workflow runs twice: a quick pass at 768 px (16 steps, denoise 1, with live previews inside the strokes), then a full-size pass from that result (8 steps, denoise 0.35). The result is the edit's patch. For an erase, the full pass ends in Level Fill, which levels Klein's fill with the background around it: left in, a pale imprint of the removed object became smoke in the erase pass. The `edit` workflow saves its outputs to the output folder, so the job index finds them later.
5. **Stack the first frame** (`recompose`). Active patches stack on `S.original` to make `S.hero`. When an edit changes, the edits above it run again only if they depend on it (`dependsOnChange`: one of the two is a light, or their footprints overlap on a 96-cell grid).
6. **Render** (`idle`, then `pipeline`), from the render queue. Every set of edits shown is a render (`want`), made from a copy of its edits (`freeze`). One step runs at a time (`pickRender`, `logic.nextRender`): every preview before any full size, every full size before any export, the set on show first, then the most recently shown, for the last `RENDERS_WANTED` sets. A render gives way between steps (`YIELD`) and resumes later where it stopped. Nothing stops a step but Generate, which stops a full-size or export step in its first half (`preempt`, `logic.stopsForEdit`); that step runs again later. `plan` skips the steps an edit set does not need:
   - `matte` at 640 px tracks each erased object (SAM 3.1, then Follow Matte: one matte per frame even when SAM returns none, the last matte where SAM loses the object, and no other object SAM finds by itself);
   - `clean` makes the erase pass: each erased area as blocks of LTX's 32 px grid, grown by one block, and a prompt that describes the scene as it stays (`erasePrompt`), never the erased object;
   - `shot` regenerates the shot over the clean plate (or over the plate when nothing is erased), for paint and light;
   - `matte` tracks each painted area, and Follow Matte adds every pixel the shot changed near it, compared with the plate the shot was made over. The paint matte starts from the pixels the edits changed on the first frame (`changedMask`), not from the whole paint zone;
   - `comp` makes the composite at the preview size, in the model space.

   Then the same passes run at full size, without waiting for anything: at full size the erase pass runs in Lightricks' two stages, `clean` at half the working size (the preview's own pass when the preview is that size), then `cleanup`, 2 steps at full size. The viewer plays the full-size shot as soon as it is made: the preview size can lose an effect that the full size keeps. Last comes `review`, the full-size composite in the plate's own colour space, which the viewer plays from then on (`r.review`; for an image sequence, its EXR frames too, `r.reviewFrames`).
7. **Export**, when you press Export (`S.wantDownload`). The `export` workflow makes the same composite, then Save Plate writes it in the plate's format with the exact source pixels wherever nothing changed (a video plate's own YUV samples), and the matte frames, beside the review. The route `/paintaplate/download` zips the parts ticked in the Export dialog. A render that is not on show never exports.

On cards with 24 GB or more, preview passes show a live preview: every second step, the Live Preview node decodes the frames LTX predicts into a looping WebP.

## 6. Colour, as OpenRV does it

1. **The config.** `ocio.py` loads `$OCIO` when it is set, else a built-in config; the page can switch among them (`/paintaplate/ocio` lists them). It never opens a path the page sends.
2. **The viewer** (`display.mjs`). Each source is drawn through one WebGL2 program, in the order OpenRV chains its nodes under OCIO: `ocioIn` (the source's colour space to scene-linear, as OCIOFile), the colour tools in scene-linear (exposure, contrast, one matrix for hue, saturation, the channel and invert, then gamma, as RVColor), then `ocioOut` (the look, then the display and view, as OCIOLook and OCIODisplay). OCIO writes `ocioIn` and `ocioOut` as GLSL ES 3.0 on the server (`/paintaplate/ocio/shader`), with their lookup tables as float textures. A program is made once per colour space and view, so changing either applies at once, also while the shot plays. When the whole chain changes nothing (an 8-bit frame through an identity view, the colour tools at their defaults), the frame is drawn as it is.
3. **What each source is in.** The plate's own frames, a video plate's proxy and its review: the file colour space. The first frame, the patches, the live previews, the preview composites, the shots and an image sequence's review movie: the model space. An image sequence and its review are read as RGB half floats (`DeepFrames`, `/paintaplate/frames`), around the playhead, as OpenRV's cache keeps an EXR's half floats.
4. **The menu.** Right-click, then OCIO, with RV's labels: File Color Space (a tree by colour-space family), Look, Displays (each display with its views) and Change Config. RV binds no key for OCIO; neither does PaintAPlate. The display, the view, the look and the config are kept for the next session.
5. **The workflows.** Color Space (OCIO) converts the plate to the model space as core ComfyUI's Convert Image Color Space made sRGB: values above 1.0 tone-mapped with the batch's peak, then a gamut compression (`ocio._into_model`). Out of the model space, values are decoded as they are. Relight Transfer works in `@linear`.

**SDR to HDR.** The `hdr` workflow is Lightricks' official LTX 2.5 SDR-to-HDR graph: the shot mapped from sRGB to ACEScct by core Convert Image Color Space as the IC-LoRA's guide, fixed scene embeddings for the prompt, CFG 1, 8 distilled steps, a float32 tiled decode, and `LTXVHDRDecodePostprocess` for ACEScg values, saved as half-float EXR in ACES2065-1 (the file rules' space for EXR). The page runs it after the full-size shot (`step(r, "hdr")`) when `logic.wantsHdr` says so: an EXR plate, the switch on, no light edit; the switch is part of the render key (`|sdr`), so each setting keeps its renders. `review` and `export` load its frames, convert them to the plate's colour space and fit them with HDR Match (`mathops.hdr_match`): one curve per channel in log2, from the HDR shot's values to the plate's own, measured outside the grown matte over the whole shot, non-decreasing, and a constant gain beyond the measured range. Without HDR frames the `hdr_shot` link goes and HDR Match passes the SDR shot through. A 16-bit blank plate runs its fluid shot through `hdr`; the EXR frames become the plate under the edits.

## 7. The fluid shot

1. **A blank plate.** In the Open dialog, the Blank plate tab posts to `/paintaplate/blank`, which writes a black ProRes 4444 canvas in `input/paintaplate/blank`, once per size. Sides are multiples of 64 up to 1920; lengths are 8k + 1 frames, from 9 to 321; frame rates are 24, 25 or 50 fps.
2. **Keyframes.** The brush paints on frame 0, on the last frame, and on the 8k + 1 frames between (`snapKey`). Diamonds on the timeline drag between free slots; Ctrl+C and Ctrl+V copy a keyframe, Delete removes it, and onion skins show the keyframes around the playhead.
3. **Generate** (Enter, `generateFluid`). The `fluid` workflow runs one LTX 2.5 pass. Keyframe Video builds the control video (black frames with each keyframe at its frame). `LTXICLoRALoaderModelOnly` reads the LoRA's downscale factor and hands it to `LTXAddVideoICLoRAGuide`. The sampler is `euler_ancestral` with the 8 distilled sigmas at CFG 1, and the prompt is `ainvfxfluid, ` followed by your words (`fluidPrompt`).
4. **The first edit.** Once made, the fluid shot is the plate the next edits are painted on: History shows it as edit 1, Fluid, under the others. Its pencil brings the keyframes and words back, its eye bypasses it (the blank plate under the edits), and it can try another seed or be removed. The edits on it keep one result per plate they were made on (`recordOf`, `base`).
5. **Scenes.** Save scene keeps the scene on this ComfyUI (`/paintaplate/scenes`, in `output/paintaplate/scenes`): the plate and its file colour space, the OCIO config, display and view, the fluid shot's keyframes, words and seed, and every edit with its strokes as drawn. Open plate > Scenes opens it again, or downloads it. Strokes are saved in pixels of the working size the scene names, and drawn in one pass before any image is made from them: the same scene makes the same images, so the same jobs. Scenes of versions 1 and 2 still open, with the colour space read from the file.

Without `ainvfx-fluid.safetensors`, fluid shots switch off and the rest of the app works (`boot` sets `S.fluidReady`).

## 8. The Open dialog

Open plate has one tab per source: **ComfyUI files**, **Upload**, **Scenes** and **Blank plate**. ComfyUI files browses the input and output folders and their subfolders through `/paintaplate/browse`, which reads names, sizes and times only (`plateio.scan_folder`): numbered images are grouped into sequences named by frame pattern, an image alone is counted but not listed, and videos, animated images and saved scenes appear as they are. The page sorts and filters the list (`logic.browseItems`), draws `BROWSE_PAGE` items at a time as the list scrolls, and asks for a thumbnail only when it shows; the server makes at most four thumbnails at once and keeps each one in ComfyUI's temp folder. One click reads the item's details and guessed colour space (`/paintaplate/stat`); a double click opens it.

## 9. Where files go

| Folder | What it holds |
| --- | --- |
| `input/plates` | Plates such as the test plates from `tools/get_plates.sh` |
| `input/paintaplate/<plate id>/` | Files uploaded from the Upload tab |
| `input/paintaplate/up/` | Images the page uploads (first frames, masks, keyframes), named by the hash of their pixels |
| `input/paintaplate/blank/` | Blank canvases for fluid shots |
| `output/paintaplate/<plate id>/v<N>/` | Renders: one folder per preview size (such as `640x352/`), `full/` for the full-size passes, the review movie, `review/` for an image sequence's EXR frames, and after Export, `export/`, the matte and the download zips |
| `output/paintaplate/<plate id>/fluid_v<N>/` | Fluid shots: the ProRes plate and its preview |
| `output/paintaplate/scenes/` | Scenes saved on this ComfyUI |
| `output/paintaplate/jobs/` | The job index: one record per finished job |

## 10. Code map

### Python, at the root

| File | What it does |
| --- | --- |
| `__init__.py` | The entry point: registers the routes, serves `web/`, and exposes the 11 nodes (V3 schema, `comfy_api.v0_0_2`). |
| `nodes.py` | The 12 nodes. |
| `folders.py` | Where paths from the page may point: `plate_path` (a file, a folder or a frame pattern under the input folder, or the output folder with `output:`), `output_folder`, `run_folder`. |
| `plateio.py` | Files: sequences and frame patterns (a missing frame keeps its place, as in OpenRV), the plate spec and its colour guess, the folder scan of the plate browser, EXR writing that keeps every layer and header, still writers (PNG, TIFF, DPX, EXR), the review's half-float EXR frames, `VideoWriter` (the source codec, colour tags, timecode and audio), and the blank canvas. |
| `mathops.py` | Pixels: phase-correlation alignment, grain level, the colour seam field, push-pull fill, steady masks, `fit_to_plate`, `relight`, `follow_matte`, `level_fill`, `keyframe_video`, and the fast bilinear `resize_to`. |
| `ocio.py` | Colour: the configs, the menu's description of one, the plate's colour space guess, conversions into and out of the model space, and the viewer's GLSL with its lookup tables. |
| `routes.py` | The routes: the plate browser and its thumbnails, a plate's size, time, spec and colour space (`stat`), the frames of an image sequence as RGB half floats (`frames`), the blank plate, the job index (`jobs`), scenes, OCIO and its shaders, and the zip download. |
| `pyproject.toml` | Package and Registry metadata: the version, `PublisherId` `ainvfx`, `requires-comfyui`. |
| `requirements.txt` | The runtime packages beyond ComfyUI's own: OpenEXR and OpenColorIO. |
| `get_models.py` | Every model file the workflows load, with its repository, its tested revision and its folder, downloaded with ComfyUI's own Python on Windows, macOS or Linux. The pod setup runs it. |

Also at the root: `README.md`, `TESTING.md`, this file, `LICENSE` (Apache 2.0), `.gitignore` (the test plates included: they live on Hugging Face) and `.comfyignore` (what the Registry package leaves out). `.github/workflows/tests.yml` runs three jobs side by side on every push: the unit tests, the page against the mock ComfyUI, and a CPU ComfyUI with a headless browser. `.github/workflows/publish.yml` publishes to the Comfy Registry when run by hand, with its action pinned to a commit.

### The page, in `web/`

| File | What it does |
| --- | --- |
| `paintaplate.html` | The page: header, tools, the prompt bar (with the Editing tag, Generate and New edit), the menu button, viewport, timeline, the History, Fluid and Render panels, the log, the right-click menu, and the Keys, Export and Open dialogs. |
| `app.mjs` | The app (section 11). |
| `comfy.mjs` | The ComfyUI client: loads the workflows, posts jobs, follows the WebSocket, cancels by job kind, and reads outputs once ComfyUI has recorded the prompt. Before it posts a job of an `INDEXED` workflow it asks the job index, and after a job finishes it records it there. After a job runs out of GPU memory, it asks ComfyUI to free its memory and waits until it is released (ComfyUI frees between prompts) before one retry. |
| `logic.mjs` | Pure rules: filling workflows, sizes, captions, the prompt writer's request and `reconcile`, the shot prompt, the whole-object picker, dependencies, the frame ranking, colour maths, keyframe slots, edit targets, the OCIO menu tree (`ocioTree`), the plate browser's order and breadcrumbs (`browseItems`, `crumbs`) and frame patterns. |
| `graph.mjs` | `sceneGraph`: the whole scene as one ComfyUI workflow, identical nodes shared (Export dialog > ComfyUI graph). |
| `frames.mjs` | `FrameCache`: decoded frames within a memory budget (384 MB by default), ranked by distance from the playhead. `DeepFrames`: the same for an image sequence's own values as RGB half floats (512 MB per cache), fetched from `/paintaplate/frames`, never for a frame the budget cannot keep. |
| `canvas.mjs` | Canvas helpers; mask bounds as FLUX boxes (0 to 1000). |
| `display.mjs` | `Display`: the viewer's colour, one WebGL2 program per colour space and view (section 6). |
| `open.js` | « Open PaintAPlate » in ComfyUI's Extensions menu. It is the only `.js` file, because ComfyUI loads every `.js` file in `web/` into its graph editor; the page's own modules use `.mjs`. |
| `app.css` | The dark, RV-like style, with its colours as tokens on `:root`. On a phone held upright, one column that scrolls; on a phone on its side, the tools down the left; the menu as a sheet along the bottom. |
| `upsampler.json` | Black Forest Labs' two system prompts for the prompt writer (table and plain). |
| `logo.png` | The logo, favicon and Registry icon. |

### The 14 workflows, in `web/workflows`

| Workflow | What it does | Called by |
| --- | --- | --- |
| `ingest` | Opens a plate: first frame in the model space, playback proxy, spec | `openPlate` |
| `prompt` | The prompt writer's caption (core Text Generate) | `captionFor` |
| `edit` | One Klein pass inside a mask: the frame, the patch, the relit frame, saved to the output folder; an erase's full pass ends in Level Fill | `generate` (two passes), `warmAll` |
| `snap` | SAM 3.1 from up to five points, and by name | `snapErase` |
| `clean` | The erase pass: in-outpainting IC-LoRA, the erased areas as blocks of LTX's 32 px grid, the scene as the prompt | `pipeline`: previews, and the first stage at full size |
| `cleanup` | The erase pass at full size: 2 steps from the half-size pass, without the reference video, as in Lightricks' two-stage workflow | `pipeline` |
| `shot` | The Ripple IC-LoRA (strength 1.35) carries the edited first frame through the shot | `pipeline` |
| `matte` | SAM 3.1 video tracking, then Follow Matte, one PNG per frame | the render's tracking steps |
| `comp` | The composite at the preview size, as a movie | `pipeline` |
| `review` | The full-size composite at the plate's quality: a movie, and for an image sequence half-float EXR frames | `pipeline` |
| `export` | The same composite, then Save Plate in the plate's format, and the matte | `pipeline`, on Export |
| `warm` | Loads the LTX 2.5 stack at page open, on cards of 60 GB or more | `warmAll` |
| `fluid` | The ainvfx-fluid pass, saved as ProRes 4444 | `generateFluid` |
| `hdr` | SDR to HDR: Lightricks' LTX 2.5 IC-LoRA makes a full-size shot again in scene-linear values, as half-float EXR in ACES2065-1. |  |

### The 11 nodes, in `nodes.py`

| Node | What it does | Used by |
| --- | --- | --- |
| Load Plate | A video, a frame folder or a frame pattern at full precision: frames, alpha, spec, frame rate, frame count; optional 8k + 1 padding | most workflows |
| Save Plate | Writes the plate's format, with the exact source pixels wherever nothing changed; for a video plate, the untouched pixels are its own YUV samples, with no RGB round trip. It lists the files it wrote, so the job index keeps them | `export`, `fluid` |
| Color Space (OCIO) | Converts frames between two colour spaces of an OCIO config, several frames at once; `@model` and `@linear` as in section 6 | most workflows |
| Save Frames | Saves a batch as numbered frames, named as core Save Image names them, several at once: 8-bit PNG, or half-float EXR with lossless PIZ compression (core took 35.3 s for 121 PNG frames at 1080p) | `clean`, `cleanup`, `shot`, `matte`, `review`, `export` |
| Save Movie | Saves a batch as the H.264 movie the page plays, as core Save Video makes it (BT.709, limited range), crf 18 by default and 12 for the proxy and the review, the frames converted several at once and x264 at preset veryfast | `ingest`, `clean`, `cleanup`, `shot`, `comp`, `review` |
| Fit to Plate | Resizes, aligns, matches the colour at the edge, adds grain, steadies the soft mask | `comp`, `review`, `export` |
| Relight Transfer | The new light from the regenerated frame: its brightness with sharp edges, its colour smooth, and no channel divided by almost no light (`light_ratio`); the texture and highlights from the plate; sRGB inputs are decoded and the result encoded here, frame by frame in parallel | `edit`, `comp`, `review`, `export` |
| Follow Matte | One matte per frame from SAM's track, following the object's own region, which starts where the edit changed the first frame (for paint) or at the first-frame mask, and moves by at most 1/16 of the width per frame | `matte` |
| Level Fill | An erase's fill levelled with the background it continues; off, it passes the image through | `edit` |
| Live Preview | A sampler hook: a tiny-decoder WebP every N steps; it switches itself off on any error | `clean`, `shot`, `fluid` |
| Keyframe Video | Black frames with each keyframe at its frame | `fluid` |
| HDR Match | Fits an HDR shot to the plate on the untouched pixels: one curve per channel (`mathops.hdr_match`). |  |

### Tools, in `tools/`

| File | What it does |
| --- | --- |
| `build_workflows.py` | Writes the 13 workflows. It holds the model file names, the sampler settings, the Ripple sentence and the `OPTIONAL` rule. |
| `check_workflows.py` | Checks every class and input against ComfyUI and ComfyUI-LTXVideo source. |
| `placeholders.py` | Empty model files, so a CPU ComfyUI validates the workflows in CI. |
| `pins.sh` | The tested ComfyUI and ComfyUI-LTXVideo commits, read by the three scripts below. |
| `ci_comfyui.sh` | Builds the CPU ComfyUI of the live tests, at the pins. |
| `pod_setup.sh` | GPU machine setup: PyTorch for CUDA 13.0, the pinned ComfyUI and ComfyUI-LTXVideo, the pack's requirements, and the models through `get_models.py`. `FLUID=0` skips ainvfx-fluid; `PLATES=1` adds the test plates. |
| `runpod_start.sh` | One command on a Runpod pod: the setup with its progress, then ComfyUI on port 8188 (`--highvram` from 80 GB of VRAM), and the app's address. `--restart` after an update. |
| `get_plates.sh` | The test plates, from the Hugging Face dataset `AInVFX/ainvfx-paintaplate` into `input/plates`. |
| `plates_to_hf.py` | Publishes plates: re-muxed with the ComfyUI metadata replaced, a card, one upload. |
| `offline_bundle.sh` | A tarball for a pod that cannot reach GitHub. |

### Tests, in `tests/`

`TESTING.md` describes every level. In short: unit tests (`test_plateio`, `test_mathops`, `test_ocio`, `test_routes`, `test_workflows`, `test_web`, `test_lint`), the Node tests in `tests/js`, the mock ComfyUI (`mock_comfy.py`) with the page test `ui_mock.py`, the live CPU level (`comfy_live.py`, `ui_live.py`), and the GPU drivers (`ui_live.py --url`, `gpu_bench.py`).

## 11. Inside `app.mjs`

**The tuning block** at the top holds every size, delay and budget: `IDLE_MS` (0.3 s between the last change and the render), `RESULTS_KEPT`, `RENDERS_WANTED` (the sets of edits whose renders go on in the background), `FOLLOW` (how far and how much a change joins the paint matte), `PREFETCH_MS`, `QUICK` and `FULL` (the two Klein passes), `CACHE_MB`, `DEEP_MB`, `DEEP_SIDE`, `WORK_SIDE`, `EDIT_SIDE`, `TRACK_SIDE`, `ERASE_TRACK_SIDE`, `LIVE`, `WARM_ALL_VRAM`, `PREVIEW_CAP`, `UNDO_MAX`, `PAINT_GRID`, `EDIT_GROW`, `PAINT_ZONE`, `ZONE_SOFT`, `WIPE_GRAB`, `COMPOSITE_GROW` and `COMPOSITE_FEATHER`; `BROWSE_PAGE` sits with the Open dialog. For tests, the URL options `?refine=`, `?cache=`, `?deep=` and `?shot=` override some of them.

**The state** is one object, `S`: the plate (with its file colour space `cs`, `deep` for an image sequence, and `proxySpace`), the OCIO config and view (`S.ocio`), the edits (`S.edits`), the draft, the current edit (`S.selected`), the edit being generated (`S.running`), the undo and redo stacks (`S.past`, `S.future`), the playhead with its in and out points, the wipe, the viewer's colour, the fluid shot, the render state (`S.renders`, `S.heroKey`, `S.stage`), the shot on show (`S.shot`: its movie, the colour space of its values, its EXR frames) and the cache of uploads.

**The sections**, in file order, each opened by a `// ----------` line:

| Section | What it holds |
| --- | --- |
| Tuning | The tuning block. |
| What Klein sees | `editImage`, `maskAt`, and `captionFor` (the prompt writer). |
| Plate | `openPlate`, `warmAll` (models load at page open), the opening steps. |
| Decoded frames | The frame caches and the green stripe of cached frames. |
| Playback, as in RV | Play, pause, seek, in and out points. |
| The picture | `render`, `renderFluid`, the overlays (strokes, live previews, wipe). Every source is drawn through OCIO from the colour space its values are in. Once the shot of the current edits exists, it shows on every frame, paused or playing; the plate shows only in the wipe or while O is held. `#view` names what it shows in `data-picture`, and whether it drew full-precision frames in `data-precision`. |
| Painting | The pointer handlers, `rubOut`, `takeInputs`, `prepareSoon` (the prefetch), pan and zoom, with two fingers on a touch screen. |
| A fluid shot | `enterFluid`, `paintKey`, keyframe drag, copy and paste, `generateFluid`, `openBlank`. |
| Edits | `launch` (with `reuse` and `keep`), `select`, `editingUI`, `nextEdit`, `pickTool`, `generate` (the two Klein passes), `prepare` and `prefetch`, `snapErase`, `rebuild`. |
| Undo and redo | `snapshot`, `mark`, `restore`. |
| History | `historyUI`: the list, bypass and removal. |
| In idle time | The render queue, `pipeline`, `plan`, the render steps, the download. |
| Interface | Status, messages (`explained`: what failed, why in plain words from `plainError`, and what to do), the log, the Render panel, the size menu, the Export dialog. |
| The Open dialog | The four tabs, the plate browser, the scenes list, the upload. |
| Scenes | Saving on this ComfyUI and opening a scene; `saveGraph` (the scene as one ComfyUI workflow). |
| The viewer's colour | The full-precision frames (`wantDeep`), and exposure, contrast, gamma, saturation, hue, channels and invert, as RV's interactive edits. |
| OCIO | `loadOcio`, `setOcio` (display, view, look), `setPlateSpace` (the file colour space), `setConfig`, and the menu's OCIO group. |
| The right-click menu | Every action with its key, also behind the menu button for touch screens, submenus within submenus; then `boot()`, the keyboard handler and `enter` (Generate). |

At load, `boot()` loads the OCIO config, then checks that every node class and model file the workflows need exists, and names what is missing.


**Layout.** `layoutUI` sets the side panel's width and the open log's height (`--side-w` and `--log-h` on the body's grid) from two dividers, kept inside the window by `logic.panelSize` so the stage keeps 320 px each way; `localStorage` keeps them (`paintaplate.layout`), and the ResizeObserver on `#viewport` refits the frame.

## 12. How to make common changes

| To change | Edit | Then |
| --- | --- | --- |
| A workflow | `tools/build_workflows.py` | Run it, and commit the JSON with it |
| A model file | Its constant at the top of `build_workflows.py`, plus its line in `MODELS` and its revision in `get_models.py` | Regenerate; `test_workflows` checks that `get_models.py` downloads every file the workflows load |
| A size, delay or budget | The tuning block of `app.mjs` | |
| A rule of the page | `logic.mjs`, with its test in `tests/js/logic.test.mjs` | `node --test tests/js/*.test.mjs` |
| What the page does | `app.mjs`, with a check in `tests/ui_mock.py` | `python tests/ui_mock.py` |
| File or pixel behaviour | `plateio.py` or `mathops.py`, with its test | `nodes.py` only converts |
| Colour | `ocio.py`, with its test in `tests/test_ocio.py` | The viewer reads the GLSL `ocio.shader` writes |
| A node | A class in `nodes.py`, added to the `NODES` list | Restart ComfyUI |
| A route | `routes.py`, plus one line in `setup()` | A test in `test_routes.py` |
| A pinned commit | `tools/pins.sh` | The source check (`COMFYUI_DIR` and `LTXVIDEO_DIR`), then a GPU run |
| A release | `version` in `pyproject.toml`; one commit whose message says what changed and why, author `AInVFX <hello@ainvfx.com>` | The whole suite; the patch and the bundle checked on a fresh clone |

Before and after any change: `python -m unittest discover -s tests -v` and `node --test tests/js/*.test.mjs`.

## 13. Pins and versions

- **ComfyUI v0.43.0** (`426f5eea`) and **ComfyUI-LTXVideo** `220e1d4`, in `tools/pins.sh`. `requires-comfyui` is `>=0.43.0`: the first release that contains what the pack was tested on.
- **Models** at pinned Hugging Face revisions (`get_models.py`), about 60 GB in all. ainvfx-fluid (0.65 GB, revision `fd4855a`, trained on synthetic data) is optional.
- **OpenColorIO** 2.4 or newer (`requirements.txt`); 2.6.0 was tested, with its built-in configs.
- **The Registry publish** runs by hand (Actions > Publish to Comfy Registry), with `Comfy-Org/publish-node-action` pinned to a commit.

## 14. Known limits

These come from GPU tests on an RTX PRO 6000 in October 2026.

- An addition painted across a foreground object breaks up mid-shot: a scooter painted over a fountain's rim did. Paint additions in open space.
- An erased head comes back as a head. Paint the new head over the old one instead.
- An explosion painted on a moving car drives off with it. Erase the car first.
- A name finds that object only: « floodlight » found the lamp, and « floodlight pole » the pole.
- The paint matte takes what the shot changed within 1/16 of the width of the object's region. An effect that jumps further than that in one frame is not caught.
- After frames where the object is not seen, the matte searches up to 4 × 1/16 of the width around its last place: an object that comes back further away stays out.
- In a fluid shot, the painted colours win over the words: paint a dusk sky in dusk colours.
- A video plate's review is 8-bit H.264 at crf 12, the same class as an 8-bit plate; a 10-bit video plate's review loses its extra bits in the viewer (the export keeps them). An image sequence's review is read at 960 px on the long side for playback.
- Model inputs come from the plate in the model space: values above 1.0 are tone-mapped into it, and edited pixels come back within 0 to 1 of it, as with core's conversion.
