# AInVFX Paint a plate: architecture

This document explains what Paint a plate does, how it is built and where each part lives, for anyone who maintains the code. It describes version 1.11.3. `TESTING.md` covers the tests.

## 1. What Paint a plate does

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
| Plate | The source footage of a shot. `warmAll` reads the card from `/system_stats`, sets `S.memoryProfile` and loads what that profile names (section 15). |
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
| Hint | A sentence of the status line that says what to do next: `status(text, "hint")`. It never goes to the log (design rule 12). |
| Stop | Esc, or Stop beside Generate: what generates stops, and no job is posted until Enter (`S.halted`, design rule 13). |
| Layer | An edit, in History's order. While an edit is changed, the frame shows it and the edits under it (design rule 14). |
| Memory profile | What the page does on the card it runs on: `small` under 24 GB of VRAM, `medium`, `large` from 60 GB (`S.memoryProfile`, section 15). |
| Example plates | The synthetic plates of the Hugging Face dataset `AInVFX/ainvfx-paintaplate`, which `get_plates.py` downloads into `input/plates`. |

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
  routes.py ...... /paintaplate/browse  thumb  stat  frames  blank  jobs  scenes  ocio  ocio/shader  download  version
  web/workflows .. 14 API workflows, written by tools/build_workflows.py
        |  core nodes, ComfyUI-LTXVideo nodes and the 14 Paint a plate nodes
        v
NODE PACK (Python)
  nodes.py ....... 14 thin nodes: they convert tensors, then call
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

1. **All GPU work is a ComfyUI workflow.** The page loads a workflow file, fills its slots and posts it. The 14 Paint a plate nodes only do what core ComfyUI cannot. So the app runs on any ComfyUI, and a Comfy API deployment stays possible.
2. **Workflows are generated.** `tools/build_workflows.py` writes `web/workflows`. Nobody edits the JSON by hand: a test fails when the files and the generator disagree.
3. **Each workflow describes itself.** In each node's `_meta`, `slots` maps the node's inputs to slot names, `output` names an output the page reads, and `progress` marks the node whose progress bar stands for the whole workflow.
4. **Optional links.** Some links exist only when the page has something to send: a matte to composite with, words to search by, a relit frame, an image sequence's review frames. When their slots stay empty, the page drops the link and every node that fed it. The rule is written twice, as `OPTIONAL` in `logic.mjs` and in `build_workflows.py`, and a test keeps the two equal.
5. **Pure code is tested without heavy dependencies.** `plateio.py`, `mathops.py` and `ocio.py` need neither torch nor ComfyUI. Every module of `web/` except `app.mjs` and `canvas.mjs` runs in Node, with its tests in `tests/js`. `nodes.py` only converts tensors and calls them; `routes.py` is plain functions plus `setup()`.
6. **One edit at a time.** A stroke goes to the draft, else to the current edit if it has the same tool, else to a new edit (`strokeTarget` in `logic.mjs`). Another tool, or New edit, closes the current edit (`toolEndsEdit`). Undo keeps the current edit while it exists.
7. **Nothing made is lost, and nothing is made twice.** Changing the edit being generated (strokes, words, the switch) stops its Klein pass. No render stops for that, nor for a bypass, an undo, a removal or a new edit: renders go on, and what they make stays. Results are kept per set of edits and per preview size (`S.renders`, keyed by `S.heroKey`), and what the erases make per set of erases (`S.erases`). Every finished job is also recorded in the job index on disk (`routes.py`, `output/paintaplate/jobs`), by the hash of its workflow file, the plate (path, size and time) and its values. A job with the same hash takes those files back instead of running, in this session or a later one on the same machine. A job is recorded only when every file it made is in the output folder (`recordable` in `comfy.mjs`, the rule `routes.write_job` enforces). A render of fewer edits, after a bypass or a removal, takes the frames of an earlier render of more edits when every edit left out is far from those kept and no light is involved (`logic.donorFor`, `donorOf`): only its tracking and composites run, and the Render panel shows the steps taken as "from v<n>". Render in full makes its own shot, with the same edits and seeds.
8. **One colour space per plate.** The plate's file colour space is a name in the OCIO config. The viewer converts from it, the workflows convert from it to the model space, and the export converts the edited pixels back to it. Changing it makes the first frame and the edits again in it; the job index keeps the earlier results, so switching back takes them at once.
9. **Previews may trade quality for speed. The review matches the plate, and the export never trades.** The review of a video plate is a movie of its own values at the working size; the review of an image sequence is also its half-float EXR frames, which the viewer compares with the plate's own frames at full precision.
10. **Paths stay inside ComfyUI.** Every path from the page resolves under ComfyUI's input or output folder (`folders.plate_path`), symbolic links are refused, and absolute paths need `PAINTAPLATE_ALLOW_ABSOLUTE=1`.
11. **One home per value.** Sizes, delays and budgets: the tuning block at the top of `app.mjs`. Model files: the constants at the top of `build_workflows.py`. Tested ComfyUI and ComfyUI-LTXVideo commits: `tools/pins.sh`. Model files and revisions: `get_models.py`.
12. **The log says each fact once, and the status line says what to do next.** The log records what happened, one line per fact: a size, a frame count, a memory figure or a file name appears in one line only. A job writes one line when it ends, with how long it took; it writes more only when it waits over a second in the queue, fails or is stopped. A sentence that tells the person what to do is a hint, `status(text, "hint")`: it shows in the status line and stays out of the log. `told(fact, next)` writes the fact to the log once and shows it in the status line with what to do next; `stopped(fact, next)` does the same for a page that cannot start, as an error. Memory is written in GB as bytes / 2**30, rounded: a 16 GB card reads « 16 GB » everywhere.
13. **A stop stops everything.** After Esc or Stop, nothing else starts until Enter (`S.halted`): an edit that waited keeps its turn, a stroke asks for nothing, and what finished is kept.
14. **Edits are layers.** While an edit is changed, the frame shows that edit and the edits under it (`layered`, `logic.hiddenAbove`). The edits above it are hidden and History dims their rows: they are likely to be generated again.
15. **One set of workflows for every card.** The memory profile only fills slots and decides what loads at start (`MEMORY` in `logic.mjs`, section 15).

## 5. The life of an edit

1. **Open a plate** (`openPlate`). The route `/paintaplate/stat` reads the plate's size, time and spec, and guesses its file colour space in the OCIO config (`ocio.guess`: the EXR's chromaticities or the video's colour tags, then the config's file rules). The `ingest` workflow decodes the plate once. It saves the first frame in the model space (at most 1920 px on the long side), a playback proxy and the plate spec. A video plate's proxy keeps its own values at the working size, so the viewer converts it as it converts the plate; an image sequence's proxy is in the model space at 960 px, for playback while its own frames load. The page then sets its sizes: the working size, 768 px for quick passes, 960 px for tracking (640 px for erase mattes) and the preview size.
2. **Paint.** Each edit draws on two canvases: `paint` (what Klein sees, for a paint) and `mask` (where the edit may act). `strokeTarget` decides which edit a stroke joins. I, or the pipette by the swatches where the browser has no eyedropper, picks a colour for the brush (`pickColor`): Chrome and Edge open their own eyedropper (the EyeDropper API), anywhere on the screen; Firefox and Safari take the colour the viewer shows under the next click on the frame (`pickAt`, `pickedColor`). `tests/ui_picker.py` checks both in any browser.
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
2. **The viewer** (`display.mjs`). Each source is drawn through one WebGL2 program, in the order OpenRV chains its nodes under OCIO: `ocioIn` (the source's colour space to scene-linear, as OCIOFile), the colour tools in scene-linear as RVColor (`ColorIPNode.cpp`): gamma first, then one matrix built in RV's order (invert, exposure, contrast about 0.5, hue, saturation), then `ocioOut` (the look, then the display and view, as OCIOLook and OCIODisplay), then the channel shown as grey, picked from the display values, as OCIODisplay floods a channel after its OCIO function. OCIO writes `ocioIn` and `ocioOut` as GLSL ES 3.0 on the server (`/paintaplate/ocio/shader`), with their lookup tables as float textures. A program is made once per colour space and view, so changing either applies at once, also while the shot plays. When the whole chain changes nothing (an 8-bit frame through an identity view, the colour tools at their defaults), the frame is drawn as it is.
3. **What each source is in.** The plate's own frames, a video plate's proxy and its review: the file colour space. The first frame, the patches, the live previews, the preview composites, the shots and an image sequence's review movie: the model space. An image sequence and its review are read as RGB half floats (`DeepFrames`, `/paintaplate/frames`), around the playhead, as OpenRV's cache keeps an EXR's half floats.
4. **The menu.** Right-click, then OCIO, with RV's labels: File Color Space (a tree by colour-space family), Look, Displays (each display with its views) and Change Config. RV binds no key for OCIO; neither does Paint a plate. The display, the view, the look and the config are kept for the next session.
5. **The workflows.** Color Space (OCIO) converts the plate to the model space as core ComfyUI's Convert Image Color Space made sRGB: values above 1.0 tone-mapped with the batch's peak, then a gamut compression (`ocio._into_model`). Out of the model space, values are decoded as they are. Relight Transfer works in `@linear`.

**SDR to HDR** (on whenever its files and nodes are found: `HDR_ON` in `app.mjs`, `?hdr=0` turns it off). The `hdr` workflow is Lightricks' official LTX 2.5 SDR-to-HDR graph: the shot mapped from sRGB to ACEScct by core Convert Image Color Space as the IC-LoRA's guide, fixed scene embeddings for the prompt, CFG 1, 8 distilled steps, a float32 tiled decode, and `LTXVHDRDecodePostprocess` for ACEScg values, saved as half-float EXR in ACES2065-1 (the file rules' space for EXR). The page runs it after the full-size shot (`step(r, "hdr")`) when `logic.wantsHdr` says so: no light edit, and the rule that follows. It runs on its own for new content on a plate that holds values above 1.0 (`logic.wantsHdrFor`, `holdsHdr`); on any other plate only when Deliver's bit-depth pass asks for it, and then the render key gains `|hdr`, so each setting keeps its renders. The switch near the render steps is gone (Adrien, 3 Nov): the rule and Deliver cover both of its cases. A plate holds values above 1.0 when its samples are float or when its colour space decodes code value 1.0 above 1.0 (`logic.holdsHdr`; `headroom` comes from the stat route: a log encoding, PQ or HLG), video or not, and then it exports in its own format with no extra files (Adrien, 3 Nov). Otherwise (an SDR video, an integer sequence in sRGB or a linear encoding) Deliver's bit-depth pass converts it on purpose, asked first (`askDeliverHdr`, `#deliver-confirm`), and the result becomes an EXR sequence (`logic.exrResult`). Its review also writes half-float EXR frames in the plate's colour space with values above 1.0 kept, which the viewer reads at full precision as an image sequence's, and its export drops Save Plate (the optional link `export_plate`) for half-float EXR frames in ACES2065-1 (`export_exr`). `review` and `export` load its frames, convert them to the plate's colour space and fit them with HDR Match (`mathops.hdr_match`): one gain per channel, the median ratio to the plate's own values over the untouched mid-tones (plate luminance 1/64 to 0.71) of the whole shot. A gain changes no ratio, so the range SDR to HDR made above the plate's white stays for grading. Without HDR frames the `hdr_shot` link goes and HDR Match passes the SDR shot through. A 16-bit blank plate runs its fluid shot through `hdr`; the EXR frames become the plate under the edits.

**SDR to HDR's temporal tiles.** The flicker of 29 Oct had two causes. In the files: Lightricks' distilled graph decodes in 64-frame temporal tiles with 8 frames of overlap, and the HDR frames of a 121-frame fluid shot jumped 0.32 stops at frame 56, where the second tile starts (RTX PRO 6000, 2 Nov). The `hdr` workflow decodes in 128-frame tiles with 32 of overlap, as Lightricks' Tiled Fusion graph: the largest step fell to 0.07 stops, the SDR shot's own, and a shot of up to 128 frames is one tile.

**The viewer's 8-bit movies of an image sequence.** The second cause was in the viewer. It drew an image sequence's EXR frames where they had arrived and its 8-bit movie elsewhere, and that movie was in the model space, tone-mapped with the shot's peak (a white of 1.0 shows at about half its value at a peak of 15). Its 8-bit movies now hold log values (`logic.viewerSpace`: ACEScct when the config has it): the playback proxy (`proxy_space` of `ingest`), the review's viewer movie (output `view`, the optional link `review_view`, dropped for a video plate) and the SDR-to-HDR movie (output `movie`). While a source plays, it shows its EXR frames only once all of them are in (`logic.drawsDeep`, `holds`); paused, the precise frame shows. The review movie of the zip stays in the model space.

**Two passes in the wipe** (Ctrl+click on a finished Render step, Cmd+click on a Mac). The wipe's left side shows that pass against the pass on show on its right, both named, to find the step a fault comes from: a shot against its composite, a matte against the picture, a preview against the full size. A second video plays it beside the shot: a follower of the playhead (`followers` in `app.mjs`), synced by `tick` and `seek`. Paused, its frame comes at native size from the frames route, as the right side's does, and the plate shows on the left until it has one. A second Ctrl+click, Esc or F6 ends it, and the wipe goes back to how it was. The Color Inspector reads the side of the wipe its point is on (`inspector.wipeSide`): the plate, the pass compared or the pass on show, named in its Source row. The pixel route takes the plate's size (`of`), so a pass with fewer pixels, such as a preview, is read at the same place in its own pixels: 1.7.0 read the plate's pixel numbers there and failed.

**The X-ray** (W, free in OpenRV's `rvui.mu` and in the page), as PlateLock's: where the edits on show change the plate, tinted over the picture. `xray.xrayPlan` picks the mattes: the export's once Export has made one, else the tracking mattes of the size on show (the erase matte and the paint matte); a light edit changes every pixel, so it tints the whole frame. The tint is drawn on its own canvas, `#xray`, above the picture with its zoom and pan, so the inspector's final colour and the colour picker read the picture without it. Paused, each matte's frame comes from the frames route at 512 px (`XRAY_SIDE`), in any browser; playing, its movie plays as a follower of the playhead. Until every matte has the frame, the last tint stays.

**The viewer against OpenRV (viewer workstream, 2 Nov).** The colour tools are RV's own math, in `display.mjs` (`colorMatrix`, `displayUniforms`), read from OpenRV `0bd9675`: RV multiplies each tool on the left of one 4 x 4 matrix (invert, exposure, contrast as (1 + c) x - c / 2, hue as a sheared rotation about the grey axis that keeps Rec. 709 luma, saturation), and its shader applies gamma before that matrix. Contrast is 0 at rest, as RV's `color.contrast`. RV's invert matrix carries (1, 1, 1, 0) as its last row, so contrast after an invert scales its offset by r + g + b; the viewer keeps that, for RV's values. `ocio.py` asks OCIO for the GPU processor OpenRV asks for (`OPTIMIZATION_DEFAULT`), in GLSL ES 3.0 instead of RV's GLSL 1.3. `tests/test_rv_parity.py` holds the reference (RV's math, with PyOpenColorIO's CPU processor in place of RV's GPU one) and `tests/flows/viewer.py` reads the canvas for 12 pixels and every case.

**Reviewed against OpenRV (3 Nov).** OpenRV's `main` is still `0bd9675` (2 Nov, 14:31 EST). Read again line by line against `display.mjs` and `ocio.py`: `ColorIPNode.cpp` (gamma's exponent is 1 / gamma, applied first as `pow(max(x, 0), exponent)` in `ColorGamma.glsl`; then one matrix, each tool multiplied on the left: invert with its (1, 1, 1, 0) last row, exposure, contrast (1 + c) x - c / 2, hue iR * iZsh * Rz * Zsh * R, saturation with `Rec709FullRangeRGBToYUV8`'s first row, 0.2126001, 0.7151999, 0.0721999; offset, scale, CDL and the luminance LUT stay at rest in Paint a plate), `OCIOIPNode.cpp` (`getOptimizedGPUProcessor(OPTIMIZATION_DEFAULT)`, the channel flood after the display with the same weights) and `ocio_source_setup.py` (OCIOFile, RVColor, OCIOLook, OCIODisplay). No difference in values. Paint a plate's weights are 0.2126, 0.7152, 0.0722: 1e-7 apart, far below one code value. Adrien has no OpenRV, so the parity stands on this reading and on `tests/test_rv_parity.py` with the canvas readback (23 cases, 1 code value at most).

**The colour inspector** (`inspector.mjs`, F5, View > Color Inspector, as `toggleColorInspector` in `rvui.mu` and `inspector.mu`, with annotate mode's rules from `annotate_mode.mu`, OpenRV `0bd9675`). The inspector and the brush are active at once: a plain click paints; Shift+click samples a pixel and Shift+drag averages the pixels it passes (RV's `pointer-1--shift` binds, which annotate mode passes on). The box sits beside the sampled point with a marker on it, and dragging the box moves the point with it (RV's widget drag). The point lives in the plate's own pixels (from the top left) and every redraw reads it again (`refreshInspector` at the end of `render`, `renderFluid` and `applyView`), so the values follow the frame, the source, the pass on show, zoom and pan. The source values come at full precision and native size from `/paintaplate/pixel` (`routes.pixel`: an EXR's half floats as stored, a video's frame decoded with its own YUV matrix and range); the final colour is read from the canvas. It reads the file on show: the shot's EXR frames in their own space (`setShot`'s `framesSpace`), else its movie, whose codes it names as such, else the plate.

**The plate at its own size** (viewer workstream, 2 Nov). The canvas holds the plate at its native size, up to 4096 px on the long side (`NATIVE_SIDE`, the frames route's limit and the pipeline's movies'), and key 1 shows it 1:1 in device pixels (`display.oneToOne`), as RV's 1:1. Editing stays at the working size: strokes, edit previews and the brush draw through one scale (`inWork`), and `frameAt` returns working-size pixels. Paused, the frame on show comes from the frames route at native size and full precision, one frame per source (`sharpFrame`: the plate, and the shot's EXR frames or movie), so an EXR shows its half floats and a video its source frame, decoded on the server (`routes.video_frames`: planar YUV through the file's own matrix and range in float, from its samples at their bit depth). While a source plays, the movies and the 960 px cache stay. From 1:1, the canvas draws with `image-rendering: pixelated`, so a plate pixel shows as a square.

**Zoom and pan as OpenRV** (viewer workstream, 2 Nov). The bindings of `rvui.mu` (`0bd9675`): f fits, Ctrl+F fits the width (RV's Frame Width), 1 to 8 show N:1 and Shift+2 to Shift+8 show 1:N in device pixels (RV's Ctrl+2 to Ctrl+8; Chrome keeps Ctrl and Alt with a digit for its tabs), Ctrl+drag zooms about the press point with RV's `dragZoom` curve (to the right k + 15 m², to the left k - 0.75 m, m = |dx| / width x k x 2), Alt with both buttons zooms too, Alt+drag and the middle button pan, Shift locks the pan to one axis; the wheel steps frames, as in RV. The math is pure (`display.mjs`: `pixelScale`, `dragZoomScale`, `zoomAbout`, `lockAxis`, `pointIn`), and `frameAt` maps the pointer through the view's laid-out box, so a stroke lands under the pointer at every zoom.

**The wipe on a fluid shot.** With the keyframes open and a shot made, the wipe shows this frame's painted keyframe on the left, or black where the frame has none (no onion skins), against the shot on the right; the left label reads « Keyframe ».

**The colour tools while a source plays.** At rest a playing source shows its 8-bit movie until all its EXR frames are in. Once a colour tool moves, a source with EXR frames shows only those (`display.exactFrame`: the frame on show, else the nearest one in), as RV plays what it has decoded: four stops up, the 8-bit ACEScct movie of a fluid shot was 4 display levels off at the median and 24 at p99 in its dark background, with H.264's 8 px blocks.

**Models and licences** (`web/models.json`, `models.mjs`, Help > Models and licences). The registry holds every model file with the licence its Hugging Face repository states at the pinned revision, the original model's licence where a repackaged file differs, its source and its use; `tests/test_models.py` checks it against `get_models.py` and every workflow. The view lists the models behind the result on show, from the files the workflows that made it load (`workflowsFor`, `modelsBehind`), then every model.

**Passes on show.** The Render panel's finished rows with a movie (`logic.PASSES`, `passMovie`) and a First frame row: `choosePass` sets `S.pass`, the viewer shows that pass on every frame, and the pipeline's own `setShot` calls wait until `S.pass` is null again (a second click, Esc after the selection, or other edits). The erase pass keeps its own movie as `cleanRaw`. The tracking steps and the export show their matte: the `matte` and `export` workflows also save it as a grey movie (optional outputs, dropped when the page sends no prefix, as in the ComfyUI graph), drawn through the config's data colour space (`logic.dataSpace`, OCIO's isdata, such as Raw), so it shows its own values. A made fluid shot has its own rows, with its keyframes open or closed (`logic.fluidPasses`): Fluid: keyframes (the control video, an optional output of `fluid`), Fluid: shot, and for a 16-bit plate Fluid: SDR to HDR.

**Start and the fluid export.** With no plate open, boot opens a blank plate at the Blank tab's settings (`BLANK_AT_START`, `openBlank({ atStart })`), 16-bit when SDR to HDR is ready (`logic.defaultDepth`). A fluid shot with no edit on it exports itself (`fluidOnly`, `downloadFluid`): the download route's parts `hdr`, `plate` and `preview` of its folder (`logic.fluidRun`).

**Dropped links** (`drop_link`, `dropLink`) also remove the nodes that only fed what went, so a filled workflow holds no node that feeds nothing.

**Deliver** (`#deliver`, `deliverUI`): the panel of passes that run after the full-size composite, each on or off, in the side panel beside Render. Its first pass is the bit-depth pass: the deliberate SDR to HDR of a plate whose format holds nothing above 1.0 (`S.deliver.hdr`), confirmed first, delivered as an EXR sequence (`logic.exrResult`). The other passes (upscale, alpha, depth, normals, IDs) come next, each model in `web/models.json`.

**The workflows a render ran** (`r.flows`). Each finished or reused step adds its workflows to its render's record (`logic.STEP_FLOWS`: a full-size erase pass runs `clean` and `cleanup`). Models and licences and an export's `MODELS.md` name the models behind the result from that record, the edits' own workflows (the prompt writer and Klein, SAM's object search for an erase) and a fluid shot's (`logic.resultFlows`, `modelsOnShow`), so a step that never ran, such as SDR to HDR on an SDR plate, lists no model.

**New content at the plate's bit depth** (`logic.plateDepth`, read from the plate's pixel format). The frames a shot and the erase pass pass through on their way to the export are 8-bit PNG for an 8-bit plate, 16-bit PNG for a 10, 12 or 16-bit plate (10-bit and 12-bit video, ProRes among them, 16-bit PNG and TIFF, 10-bit DPX), and half-float EXR for a plate of floats, EXR or a float TIFF or DPX (Save Frames' `png`, `png16` and `exr`, the `frames_format` slot of `clean`, `cleanup` and `shot`). The export already writes each plate at its own depth (Save Plate), so the new content keeps more than 256 levels on every plate deeper than 8 bits. SDR to HDR runs on its own for a plate that holds values above 1.0; `S.deliver` holds Deliver's passes for the plate (`hdr`, the deliberate conversion), the fluid shot under the edits keeps them, and scenes save them (version 6; a version-5 scene's switch, on, becomes Deliver's `hdr`).

**Live previews and stopping.** Live Preview patches every LTX pass (preview and full size, the erase pass's two stages, SDR to HDR, the fluid shot): the first preview at step 1, then every other step, each naming its step and the pass's steps from the sampler's `sample_sigmas` (the page shows « step 3 of 8 », and the stage of the two-stage erase pass). At full size the latent is averaged first so the tiny decoder works at about twice the preview's size, and the SDR-to-HDR pass's ACEScct codes show through `mathops.acescct_preview` (Reinhard, then the sRGB curve). `showLive` draws in the frame until a shot exists for the edits on show, then fills the inset `#live-inset`. Esc follows `logic.escapeAction`: `stopGenerating` sets `S.halted`, cancels the render's and the fluid's jobs and keeps every finished step; `idle` waits, and Enter clears it. Stop, beside Generate while anything generates, does what Esc does. Cancel on the opening screen, or Esc, stops a plate that is opening (`cancelOpen`); Close plate stops every job, resets the frame caches and empties the page (`closePlate`), and ComfyUI keeps its models.

## 7. The fluid shot

1. **A blank plate.** With no plate open, the page opens one at start, at the tab's settings (`?blank=0` starts empty). In the Open dialog, the Blank plate tab posts to `/paintaplate/blank`, which writes a black ProRes 4444 canvas in `input/paintaplate/blank`, once per size. Sides are multiples of 64 up to 1920; lengths are 8k + 1 frames, from 9 to 321; frame rates are 24, 25 or 50 fps.
2. **Keyframes.** The brush paints on frame 0, on the last frame, and on the 8k + 1 frames between (`snapKey`). Diamonds on the timeline drag between free slots; Ctrl+C and Ctrl+V copy a keyframe, Delete removes it, and onion skins show the keyframes around the playhead.
3. **Generate** (Enter, `generateFluid`). The `fluid` workflow runs one LTX 2.5 pass. Keyframe Video builds the control video (black frames with each keyframe at its frame). `LTXICLoRALoaderModelOnly` reads the LoRA's downscale factor and hands it to `LTXAddVideoICLoRAGuide`. The sampler is `euler_ancestral` with the 8 distilled sigmas at CFG 1, and the prompt is `ainvfxfluid, ` followed by your words (`fluidPrompt`).
4. **The first edit.** Once made, the fluid shot is the plate the next edits are painted on: History shows it as edit 1, Fluid, under the others. Its pencil brings the keyframes and words back, its eye bypasses it (the blank plate under the edits), and it can try another seed or be removed. The edits on it keep one result per plate they were made on (`recordOf`, `base`).
5. **Scenes.** Save scene keeps the scene on this ComfyUI (`/paintaplate/scenes`, in `output/paintaplate/scenes`): the plate and its file colour space, the OCIO config, display and view, the fluid shot's keyframes, words and seed, and every edit with its strokes as drawn. Open plate > Scenes opens it again, or downloads it. Strokes are saved in pixels of the working size the scene names, and drawn in one pass before any image is made from them: the same scene makes the same images, so the same jobs. A fluid scene keeps its blank plate in the model space, as Open plate makes it; its fluid shot, and for a 16-bit plate its SDR to HDR, come back from the job index, so the EXR frames under the edits keep their files and every job on them is found again. Scenes of versions 1 and 2 still open, with the colour space read from the file.

Without `ainvfx-fluid.safetensors`, fluid shots switch off and the rest of the app works (`boot` sets `S.fluidReady`).

## 8. The Open dialog

Open plate has one tab per source: **ComfyUI files**, **Upload**, **Scenes** and **Blank plate**. ComfyUI files browses the input and output folders and their subfolders through `/paintaplate/browse`, which reads names, sizes and times only (`plateio.scan_folder`): numbered images are grouped into sequences named by frame pattern, an image alone is counted but not listed, and videos, animated images and saved scenes appear as they are. The page sorts and filters the list (`logic.browseItems`), draws `BROWSE_PAGE` items at a time as the list scrolls, and asks for a thumbnail only when it shows; the server makes at most four thumbnails at once and keeps each one in ComfyUI's temp folder. One click reads the item's details and guessed colour space (`/paintaplate/stat`); a double click opens it. At the input or output root, the route also returns the newest plates of the folders below (`routes.plates_below`: 60 at most, from at most 400 folders, Paint a plate's own folders left out), each listed with its folder.

## 9. Where files go

| Folder | What it holds |
| --- | --- |
| `input/plates` | Plates such as the example plates that `get_plates.py` downloads |
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
| `__init__.py` | The entry point: registers the routes, serves `web/`, and exposes the 14 nodes (V3 schema, `comfy_api.v0_0_2`). |
| `nodes.py` | The 14 nodes. |
| `folders.py` | Where paths from the page may point: `plate_path` (a file, a folder or a frame pattern under the input folder, or the output folder with `output:`), `output_folder`, `run_folder`. |
| `plateio.py` | Files: sequences and frame patterns (a missing frame keeps its place, as in OpenRV), the plate spec and its colour guess, the folder scan of the plate browser, EXR writing that keeps every layer and header, still writers (PNG, TIFF, DPX, EXR), the review's half-float EXR frames, `VideoWriter` (the source codec, colour tags, timecode and audio), and the blank canvas. |
| `mathops.py` | Pixels: phase-correlation alignment, grain level, the colour seam field, push-pull fill, steady masks, `fit_to_plate`, `relight`, `follow_matte`, `level_fill`, `keyframe_video`, and the fast bilinear `resize_to`. |
| `ocio.py` | Colour: the configs, the menu's description of one, the plate's colour space guess, conversions into and out of the model space, and the viewer's GLSL with its lookup tables. |
| `routes.py` | The routes: the plate browser and its thumbnails, a plate's size, time, spec and colour space (`stat`), the frames of an image sequence as RGB half floats (`frames`), the blank plate, the job index (`jobs`), scenes, OCIO and its shaders, the zip download and, with `PAINTAPLATE_TRACE=1` in ComfyUI's environment, a trace of every request (section 15). |
| `pyproject.toml` | Package and Registry metadata: the version, `PublisherId` `ainvfx`, `requires-comfyui`, the dependencies as `requirements.txt` lists them (the Registry reads only this static list), and no accelerator classifier, since the nodes run on a CPU. |
| `requirements.txt` | The runtime packages beyond ComfyUI's own: OpenEXR and OpenColorIO. |
| `get_models.py` | Every model file the workflows load, with its repository, its tested revision, its folder and its size. `python get_models.py` downloads what is missing, with ComfyUI's own Python on Windows, macOS or Linux; `--list` says what is in place. The pod setup runs it. It also holds what `get_plates.py` shares: `download`, `listing`, `hub`. |
| `get_plates.py` | The example plates: the MP4 files of the dataset `AInVFX/ainvfx-paintaplate`, into `input/plates`, with the same options and closing line as `get_models.py`. |

Also at the root: `README.md`, `TESTING.md`, this file, `LICENSE` (Apache 2.0), `.gitignore` (the example plates included: they live on Hugging Face) and `.comfyignore` (what the Registry package leaves out). `.github/workflows/tests.yml` runs three kinds of job side by side on every push: the unit tests, the page against the mock ComfyUI in four shards, and a CPU ComfyUI with a headless browser. Its `release` job publishes a new version from `main` (section 13).

### The page, in `web/`

| File | What it does |
| --- | --- |
| `paintaplate.html` | The page: header, tools, the prompt bar (with the Editing tag, Generate and New edit), the menu button, viewport, timeline, the History, Fluid and Render panels, the log, the right-click menu, and the Keys, Export and Open dialogs. |
| `app.mjs` | The app (section 11). |
| `comfy.mjs` | The ComfyUI client: loads the workflows, posts jobs, follows the WebSocket, cancels by job kind, and reads outputs once ComfyUI has recorded the prompt. Before it posts a job of an `INDEXED` workflow it asks the job index, and after a job finishes it records it there. After a job runs out of GPU memory, it asks ComfyUI to free its memory and waits until it is released (ComfyUI frees between prompts) before one retry. |
| `logic.mjs` | Pure rules: filling workflows, sizes, captions, the prompt writer's request and `reconcile`, the shot prompt, the whole-object picker, dependencies, the frame ranking, the colour picker's average, keyframe slots, edit targets, the OCIO menu tree (`ocioTree`), the plate browser's order and breadcrumbs (`browseItems`, `crumbs`) and frame patterns. |
| `graph.mjs` | `sceneGraph`: the whole scene as one ComfyUI workflow, identical nodes shared (Export dialog > ComfyUI graph); `organise` lays it out for a person: a hundred ids per section in run order (README, INPUT, MODELS, each EDIT, ERASE TRACKING, ERASE PASS, SHOT, PAINT TRACKING, SDR TO HDR, OUTPUT), each opening with a README note (core Primitive String Multiline, read by no node, so it never runs), the section and the values the page set in every title. |
| `frames.mjs` | `FrameCache`: decoded frames within a memory budget, ranked by distance from the playhead. `DeepFrames`: the same for an image sequence's own values as RGB half floats, fetched from `/paintaplate/frames`, never for a frame the budget cannot keep. Also the budget's rules (`autoBudget`, `cachePlan`, `CACHE_CHOICES`) and `PlayStats`, what a stretch of playback achieved (section 15). |
| `canvas.mjs` | Canvas helpers; mask bounds as FLUX boxes (0 to 1000). |
| `display.mjs` | `Display`: the viewer's colour, one WebGL2 program per colour space and view (section 6). |
| `inspector.mjs` | The Color Inspector's rules: the plate pixel under a point, the file on show, the side of the wipe it reads, its rows (section 6). |
| `xray.mjs` | The X-ray's rules: which mattes, and a grey matte as the tint's opacity (section 6). |
| `models.mjs`, `models.json` | The registry of every model file with its source, licence and revision (`models.json`), and the rules that name the models behind a result from the workflows that made it (`models.mjs`): the Models and licences dialog and an export's `MODELS.md`. |
| `open.js` | « Open Paint a plate » in ComfyUI's Extensions menu. It is the only `.js` file, because ComfyUI loads every `.js` file in `web/` into its graph editor; the page's own modules use `.mjs`. |
| `app.css` | The dark, RV-like style, with its colours as tokens on `:root`. On a phone held upright, one column that scrolls; on a phone on its side, the tools down the left; the menu as a sheet along the bottom. |
| `upsampler.json` | Black Forest Labs' two system prompts for the prompt writer (table and plain). |
| `logo.png` | The logo, favicon and Registry icon. |
| `brand/` | The README's title, the Registry's icon and banner, the favicon and the touch icon. |

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
| `hdr` | SDR to HDR: Lightricks' LTX 2.5 IC-LoRA makes a full-size shot again in scene-linear values, as half-float EXR in ACES2065-1, and an 8-bit movie in ACEScct for the viewer. |  |

### The 14 nodes, in `nodes.py`

| Node | What it does | Used by |
| --- | --- | --- |
| Load Plate | A video, a frame folder or a frame pattern at full precision: frames, alpha, spec, frame rate, frame count; optional 8k + 1 padding | most workflows |
| Save Plate | Writes the plate's format, with the exact source pixels wherever nothing changed; for a video plate in planar YUV, the untouched pixels are its own YUV samples, with no RGB round trip. The plate's own alpha stays as it is, and an EXR's data window grows only to hold an edit outside it. It lists the files it wrote, so the job index keeps them | `export`, `fluid` |
| Color Space (OCIO) | Converts frames between two colour spaces of an OCIO config, several frames at once; `@model` and `@linear` as in section 6 | most workflows |
| Save Frames | Saves a batch as numbered frames, named as core Save Image names them, several at once: 8-bit PNG, or half-float EXR with lossless PIZ compression (core took 35.3 s for 121 PNG frames at 1080p) | `clean`, `cleanup`, `shot`, `matte`, `review`, `export` |
| Save Movie | Saves a batch as the H.264 movie the page plays, as core Save Video makes it (BT.709, limited range), crf 18 by default and 12 for the proxy and the review, the frames converted several at once and x264 at preset veryfast | `ingest`, `clean`, `cleanup`, `shot`, `comp`, `review` |
| Fit to Plate | Resizes, aligns, matches the colour at the edge, adds grain, steadies the soft mask | `comp`, `review`, `export` |
| Relight Transfer | The new light from the regenerated frame: its brightness with sharp edges, its colour smooth, and no channel divided by almost no light (`light_ratio`); fixed filters only, so a steady shot gives a steady result; one shift for the whole shot (`shot_shift`); a light edit's shade strokes darkening the frame where they are painted, in linear light (`shade_frame`); the texture and highlights from the plate; sRGB inputs are decoded and the result encoded here, frame by frame in parallel | `edit`, `comp`, `review`, `export` |
| Follow Matte | One matte per frame from SAM's track, following the object's own region, which starts where the edit changed the first frame (for paint) or at the first-frame mask, and moves by at most 1/16 of the width per frame | `matte` |
| Level Fill | An erase's fill levelled with the background it continues; off, it passes the image through | `edit` |
| Live Preview | A sampler hook: a tiny-decoder WebP every N steps; it switches itself off on any error | `clean`, `shot`, `fluid` |
| Keyframe Video | Black frames with each keyframe at its frame | `fluid` |
| HDR Match | Sets an HDR shot's level to the plate's: one gain per channel, measured on the untouched mid-tones (`mathops.hdr_match`). |  |
| Keep Black | Where the SDR shot is black, its own black instead of SDR to HDR's noise: a smooth step on the SDR shot's luminance, 0.001 to 0.01 in ACEScg (`mathops.keep_black`) | `hdr` |
| Load VAE (float32) | A VAE built in float32 at load, so ComfyUI's dynamic VRAM sizes its buffers for float32 weights (LTXVVAEForceFloat32 casts a bf16 VAE in place, which failed on a 32 GB card) | `hdr` |

### Tools, in `tools/`

| File | What it does |
| --- | --- |
| `build_workflows.py` | Writes the 14 workflows. It holds the model file names, the sampler settings, the Ripple sentence and the `OPTIONAL` rule. |
| `check_workflows.py` | Checks every class and input against ComfyUI and ComfyUI-LTXVideo source. |
| `placeholders.py` | Empty model files, so a CPU ComfyUI validates the workflows in CI. |
| `pins.sh` | The tested ComfyUI and ComfyUI-LTXVideo commits, read by the three scripts below. |
| `ci_comfyui.sh` | Builds the CPU ComfyUI of the live tests, at the pins. |
| `pod_setup.sh` | GPU machine setup: PyTorch for CUDA 13.0, the pinned ComfyUI and ComfyUI-LTXVideo, the pack's requirements, and the models through `get_models.py`. `FLUID=0` skips ainvfx-fluid; `PLATES=1` adds the example plates. |
| `runpod_start.sh` | One command on a Runpod pod: the setup with its progress, then ComfyUI on port 8188 (`--highvram` from 80 GB of VRAM), and the app's address. `--restart` after an update. |
| `plates_to_hf.py` | Publishes plates: re-muxed with the ComfyUI metadata replaced, a card, one upload. |
| `brand_icons.py` | The page's icons, drawn from the Paint a plate logo in web/brand/title.png: its gold brush and its letter P, on the dark ground of the Registry icon. |
| `offline_bundle.sh` | A tarball for a pod that cannot reach GitHub. |

### Tests, in `tests/`

`TESTING.md` describes every level. In short: the unit tests (the `test_*.py` modules: files, pixels, colour, routes, workflows, the page's modules, the linters, the Registry metadata, the download tools, the README and these docs), the Node tests in `tests/js`, the mock ComfyUI (`mock_comfy.py`) with the page suite (`ui_mock.py`, and one flow per file of `tests/flows`), the live CPU level (`comfy_live.py`, `ui_live.py`), and the GPU scripts (`gpu_matrix.py`, `gpu_bench.py`, `open_probe.py`).

## 11. Inside `app.mjs`

**The tuning block** at the top holds every size, delay and budget: `IDLE_MS` (0.3 s between the last change and the render), `RESULTS_KEPT`, `RENDERS_WANTED` (the sets of edits whose renders go on in the background), `FOLLOW` (how far and how much a change joins the paint matte), `PREFETCH_MS`, `QUICK` and `FULL` (the two Klein passes), `CACHE_MB`, `DEEP_MB`, `DEEP_SIDE`, `WORK_SIDE`, `EDIT_SIDE`, `TRACK_SIDE`, `ERASE_TRACK_SIDE`, `LIVE`, `WARM_ALL_VRAM`, `PREVIEW_CAP`, `UNDO_MAX`, `PAINT_GRID`, `EDIT_GROW`, `PAINT_ZONE`, `ZONE_SOFT`, `WIPE_GRAB`, `COMPOSITE_GROW` and `COMPOSITE_FEATHER`; `BROWSE_PAGE` sits with the Open dialog. For tests, the URL options `?refine=`, `?cache=`, `?deep=` and `?shot=` override some of them.

**The state** is one object, `S`: the plate (with its file colour space `cs`, `deep` for an image sequence, and `proxySpace`), the OCIO config and view (`S.ocio`), the edits (`S.edits`), the draft, the current edit (`S.selected`), the edit being generated (`S.running`), the undo and redo stacks (`S.past`, `S.future`), the playhead with its in and out points, the wipe, the viewer's colour, the fluid shot, the render state (`S.renders`, `S.heroKey`, `S.stage`), the shot on show (`S.shot`: its movie, the colour space of its values, its EXR frames) and the cache of uploads.

**The sections**, in file order, each opened by a `// ----------` line:

| Section | What it holds |
| --- | --- |
| Tuning | The tuning block. |
| What Klein sees | `editImage`, `maskAt`, and `captionFor` (the prompt writer). |
| Plate | `openPlate`, `warmAll` (models load at page open; `logic.warmEnd` words its last line, on the status line only while the start's message is there), the opening steps. |
| Decoded frames | The frame caches, `planCaches` (one budget shared by the caches of the sources on show) and the green stripe of cached frames. |
| Playback, as in RV | Play, pause, seek, in and out points; from memory once every frame is there, else from the videos (`S.memory`, section 15). |
| The picture | `render`, `renderFluid`, the overlays (strokes, live previews, wipe). Every source is drawn through OCIO from the colour space its values are in. Once the shot of the current edits exists, it shows on every frame, paused or playing; the plate shows only in the wipe or while O is held. `#view` names what it shows in `data-picture`, and whether it drew full-precision frames in `data-precision`. |
| Two passes in the wipe | Ctrl+click on a finished Render step puts that pass on the wipe's left side, against the pass on show. |
| The X-ray | W tints where the edits on show change the plate (`xray.mjs`). The section also holds `showLive`, which alone decides which live preview shows, and the stop: `escape` and `stopGenerating`. |
| Painting | The pointer handlers, `rubOut`, `takeInputs`, `prepareSoon` (the prefetch), pan and zoom, with two fingers on a touch screen. |
| A fluid shot | `enterFluid`, `paintKey`, keyframe drag, copy and paste, `generateFluid`, `openBlank`. |
| Edits | `launch` (with `reuse` and `keep`), `select`, `editingUI`, `nextEdit`, `pickTool`, `generate` (the two Klein passes), `prepare` and `prefetch`, `snapErase`, `rebuild`. |
| Undo and redo | `snapshot`, `mark`, `restore`. |
| History | `historyUI`: the list, bypass and removal. |
| In idle time | What starts when nothing is typed or painted: the shot, its mattes, the composite to play, then the export. |
| The render queue | `pipeline`, `plan`, the render steps, the download. It publishes the step that runs in `S.stage` and its render in `S.piping`. |
| Interface | `status` (a hint stays out of the log), `told` and `stopped` (design rule 12), messages (`explained`: what failed, why in plain words from `plainError`, and what to do), the log, the Render panel, the size menu, the Export dialog. |
| The Open dialog | The four tabs, the plate browser, the scenes list, the upload. |
| Scenes | Saving on this ComfyUI and opening a scene; `saveGraph` (the scene as one ComfyUI workflow). |
| The viewer's colour | The full-precision frames (`wantDeep`), and exposure, contrast, gamma, saturation, hue, channels and invert, as RV's interactive edits. |
| Help | The Help dialog, in tabs: Getting started, Tools, Keys, Viewer and colour, Render and export, Models and licences. |
| Models and licences | The models behind the result on show, and every model with its licence (`models.mjs`). |
| The colour inspector | F5, as OpenRV's: the values under the pointer (`inspector.mjs`). |
| OCIO | `loadOcio`, `setOcio` (display, view, look), `setPlateSpace` (the file colour space), `setConfig`, and the menu's OCIO group. |
| The right-click menu | Every action with its key, also behind the menu button for touch screens, submenus within submenus; then `boot()`, the keyboard handler and `enter` (Generate). |

At load, `boot()` loads the OCIO config, then checks that every node class and model file the workflows need exists, and names what is missing.


**Layout.** `layoutUI` sets the side panel's width and the open log's height (`--side-w` and `--log-h` on the body's grid) from two dividers, kept inside the window by `logic.panelSize` so the stage keeps 320 px each way; `localStorage` keeps them (`paintaplate.layout`), and the ResizeObserver on `#viewport` refits the frame.

## 12. How to make common changes

| To change | Edit | Then |
| --- | --- | --- |
| A workflow | `tools/build_workflows.py` | Run it, and commit the JSON with it |
| A model file | Its constant at the top of `build_workflows.py`, plus its line in `MODELS`, its revision and its bytes in `SIZES` in `get_models.py`, its entry in `web/models.json` and its row in the README's credits | Regenerate; `test_workflows`, `test_models`, `test_downloads` and `test_readme` each check their part |
| A size, delay or budget | The tuning block of `app.mjs` | |
| A rule of the page | `logic.mjs`, with its test in `tests/js/logic.test.mjs` | `node --test tests/js/*.test.mjs` |
| What the page does | `app.mjs`, with a check in a flow: a file of `tests/flows`, or `tests/ui_mock.py` | `python tests/ui_mock.py --only <flow>` |
| A sentence of the status line or the log | Design rule 12: a fact to the log once, what to do next as a hint | A check in a flow, as `tests/flows/codebase_log.py` has |
| File or pixel behaviour | `plateio.py` or `mathops.py`, with its test | `nodes.py` only converts |
| Colour | `ocio.py`, with its test in `tests/test_ocio.py` | The viewer reads the GLSL `ocio.shader` writes |
| A node | A class in `nodes.py`, added to the `NODES` list | Restart ComfyUI |
| A route | `routes.py`, plus one line in `setup()` | A test in `test_routes.py` |
| A pinned commit | `tools/pins.sh` | The source check (`COMFYUI_DIR` and `LTXVIDEO_DIR`), then a GPU run |
| A release | `version` in `pyproject.toml`; one commit whose message says what changed and why, author `AInVFX <hello@ainvfx.com>`; pushed to `main`, CI releases it once the tests pass (below) | The whole suite; the patch and the bundle checked on a fresh clone |

Before and after any change: `python -m unittest discover -s tests -v` and `node --test tests/js/*.test.mjs`. Outside CI, `discover` also runs the whole page suite (`test_ui_mock`): `TESTING.md` says how to run the unit tests alone.

## 13. Pins and versions

- **ComfyUI v0.44.2** (`e6515b16`) and **ComfyUI-LTXVideo** `220e1d4`, in `tools/pins.sh`. `requires-comfyui` is `>=0.43.0`, the oldest release the pack was tested on.
- **Models** at pinned Hugging Face revisions (`get_models.py`), 62 GB in all (its `SIZES`). ainvfx-fluid (0.65 GB, revision `6102c50`, retrained on synthetic data on 1 November 2026) is optional.
- **OpenColorIO** 2.4 or newer (`requirements.txt`); 2.6.0 was tested, with its built-in configs.
- **Releases** run in CI: once the three test jobs pass on `main`, the `release` job of `tests.yml` publishes a new `version` to the Comfy Registry with comfy-cli 1.22.0 (pinned: it receives the Registry token), then tags it `v<version>` and makes its GitHub release from the commits since the last release, a pre-release before 1.0.0. Each step skips what is done already, so a re-run (Actions > tests > Run workflow) finishes a release that stopped half-way. The Registry lists a version once its automated security scan passes.

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

**The light brush and its light plan.** Light strokes are soft dabs at a fixed spacing (`logic.dabsAlong`), each stroke adding at most `LIGHT.flow` of its colour (`dabFlow`); shade strokes (a dark colour) go to their own layer, `d.shade`. A relight gives Klein two references: the frame as it is, and the light plan (`lightPlan`), the light's strokes alone on grey (RGB 58, `logic.PLAN_GREY`) with the shade strokes in black, drawn solid, on the `edit` workflow's optional second reference (`edit_plan`). Its request is the page's own (`logic.lightPlanCaption`), so a light needs no prompt writer. Klein ignores a painted shadow, so the shade strokes go to Relight Transfer as a soft white mask (`shadeMask`), which darkens the frame there in linear light (`mathops.shade_frame`, density 0.7, optional link `relight_shade`). The ComfyUI graph uploads the same plan and shade.

Found on 11 November 2026, on the 16 GB reference laptop (62.7 GB of RAM):

- Opening a plate takes far more RAM than its frames. A 1920 x 1080 plate of 121 frames took 23.5 GB at its peak, and ComfyUI kept 17.9 GB after it; one float32 copy of that plate is 3.0 GB. `tests/open_probe.py` names the node that takes it.
- The page sets no limit on a plate's frames: every workflow gets the plate's own count. 121 frames is what is tested; a blank plate takes 9 to 321.
- The times of a 16 GB card, under the small memory profile, are not measured yet (`tests/gpu_matrix.py`).
- **Numbers too far apart are not frames.** A group of numbered images is a frame sequence when at least one of every 100 numbers between its first and its last exists (`plateio.SPARSEST`). Sparser, the numbers count files: one frame per file. ComfyUI's mask editor names its files by the millisecond (`clipspace-mask-1791816680123.png`): until 1.11.4 the Open dialog's thumbnail of such a group took all of ComfyUI's memory.

## 15. Memory: the card, the frame caches and the trace

**The memory profile.** At page open, `warmAll` reads the card's VRAM and RAM from ComfyUI's `/system_stats` and sets `S.memoryProfile`: `{ name, why, does, warm, slots }` (`logic.memoryProfile`). The log says it in one line.

| Profile | VRAM | What loads at start | LTX's tiles |
| --- | --- | --- | --- |
| `small` | Under 24 GB (`MEMORY_FROM.medium`, 24e9 bytes: a 16 GB card reports about 17.2e9) | Nothing. Each model loads when an action needs it, so the prompt writer, Klein and LTX take turns | 256 px, and the guide is encoded in tiles |
| `medium` | From 24 GB (a 24 GB card reports about 25.7e9) | The edit models; LTX with the first shot | 512 px |
| `large` | From 60 GB (`MEMORY_FROM.large`) | Every model, and they stay loaded | 512 px |

One set of workflows serves every profile: `slots` fills the `tile` and `guide_tiled` slots, and `warm` names the workflows `warmAll` posts. `?memory=small` (or `medium`, `large`) in the address, or the `paintaplate.memory` setting, asks for a profile in place of the card's. The borders move with measurements: `tests/gpu_matrix.py` writes each case's peak VRAM and RAM.

**The frame caches.** `FrameCache` (decoded frames) and `DeepFrames` (an image sequence's half floats) share one budget, set in View > Cache memory and kept in `localStorage` as `paintaplate.cache`. It is Auto by default, and `?cache=<MB>` sets it for a test. `planCaches` gives each cache of the sources on show its share and its frame size, again whenever the budget, the frame's size, the sources or the in and out points change (`frames.cachePlan`).

**Playback from memory.** Once every frame between the in and out points is in memory for each source the picture draws (`memoryReady`), playback runs on a clock, from memory. Until then it follows the videos. `S.memory` is that path: `true` from memory, `false` from the videos, `null` when nothing plays. `?stats=1`, or View > Playback statistics, writes one log line for each stretch played (`PlayStats`).

**The trace.** With `PAINTAPLATE_TRACE=1` in ComfyUI's environment, a middleware in `routes.py` (`trace`) writes one line when a request starts and one when it ends: its method and address, the seconds, and the memory the process holds. `TESTING.md` says how to read it.
