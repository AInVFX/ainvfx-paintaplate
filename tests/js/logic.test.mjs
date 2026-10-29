// The page's pure rules (web/logic.mjs), run by `node --test tests/js` (tests/test_web.py runs it too).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { changedMask, erasePrompt, erasesPaint, indexValues, nextRender, paintBoxes, pickedColor, stageOne, stopsForEdit, DISPLAY, blankSpec, caption, clampParam, fluidPrompt, keySlots, moveKey, nearKeys, snapKey, dependsOnChange, displayActive, displayLabel, displayUniforms, displayTransfer, fillWorkflow, fitSize, frameUse, gb, parseWorkflow, plainError, previewSize, previewSizes, secs, strokeTarget, toolEndsEdit, panelSize } from "../../web/logic.mjs";

const workflow = (name) => parseWorkflow(JSON.parse(readFileSync(new URL(`../../web/workflows/${name}.json`, import.meta.url))));
const classes = (wf) => Object.values(wf.prompt).map((n) => n.class_type);

test("sizes keep the plate's aspect within 1.5% in multiples of the step", () => {
  assert.deepEqual(fitSize(1280, 704, 960, 32), [928, 512]); // 960 x 544 would be 2.9% off
  assert.deepEqual(fitSize(1920, 1080, 1920, 32), [1920, 1088]);
  assert.deepEqual(fitSize(1080, 1920, 960, 32), [544, 960]); // portrait
  for (const [w, h, cap] of [[1280, 704, 640], [4096, 2160, 1920], [1920, 1012, 960]]) {
    const [a, b] = fitSize(w, h, cap, 32);
    assert.ok(a % 32 === 0 && b % 32 === 0 && Math.max(a, b) <= cap);
  }
});

test("preview sizes come from the plate's size: exact divisions of the working size first, else the best fit under each cap", () => {
  const hd = [[1920, 1080], [1920, 1088]]; // a 1080p plate and its working size (multiples of 32)
  assert.deepEqual(previewSize(...hd, 960), [960, 544]); // an exact half of the working size, 0.7% off the plate's aspect
  assert.deepEqual(previewSize(...hd, 640), [640, 352]); // nothing divides: the largest fit within 2.5% of 16:9
  assert.deepEqual(previewSize(...hd, 448), [448, 256]);
  assert.deepEqual(previewSize(...hd, 1920), [1920, 1088]); // the cap at the working size: one pass
  assert.deepEqual(previewSize(...hd, 4096), [1920, 1088]);
  assert.deepEqual(previewSize([1920, 1088], [1920, 1088], 640), [608, 352]); // a 1088-high plate: 640 x 352 would be 3% off
  assert.deepEqual(previewSize([1280, 704], [1280, 704], 640), [640, 352]); // an exact half
  assert.deepEqual(previewSize([1280, 704], [1280, 704], 960), [928, 512]);
  assert.deepEqual(previewSize([1080, 1920], [1088, 1920], 640), [352, 640]); // portrait keeps its orientation
  const menu = previewSizes(...hd);
  assert.deepEqual(menu.map((o) => [o.label, o.cap, o.size, o.div]),
    [["Full", 1920, [1920, 1088], 1], ["Standard", 960, [960, 544], 2], ["Fast", 640, [640, 352], 0], ["Draft", 448, [448, 256], 0]]);
  assert.deepEqual(previewSizes([640, 352], [640, 352]).map((o) => o.label), ["Full", "Draft"]); // caps at or above the plate are the plate: listed once
  for (const o of [...menu, ...previewSizes([1920, 1012], [1920, 1024]), ...previewSizes([720, 480], [672, 448])]) {
    assert.ok(o.size[0] % 32 === 0 && o.size[1] % 32 === 0, String(o.size));
  }
});

test("the viewer's colour: identity at rest, one channel as grey, invert, exposure in stops, contrast about 18% grey", () => {
  const flat = (d) => displayUniforms(d).matrix.flat();
  assert.deepEqual(flat(DISPLAY), [1, 0, 0, 0, 1, 0, 0, 0, 1]);
  assert.deepEqual(displayUniforms(DISPLAY).offset, [0, 0, 0]);
  assert.deepEqual(flat({ ...DISPLAY, channel: "r" }), [1, 0, 0, 1, 0, 0, 1, 0, 0]);
  assert.deepEqual(flat({ ...DISPLAY, channel: "l" }), [0.2126, 0.7152, 0.0722, 0.2126, 0.7152, 0.0722, 0.2126, 0.7152, 0.0722]);
  assert.deepEqual(flat({ ...DISPLAY, invert: true }), [-1, 0, 0, 0, -1, 0, 0, 0, -1]);
  assert.deepEqual(displayUniforms({ ...DISPLAY, invert: true }).offset, [1, 1, 1]);
  assert.deepEqual(flat({ ...DISPLAY, saturation: 0 }).slice(0, 3), [0.2126, 0.7152, 0.0722]);
  for (const row of displayUniforms({ ...DISPLAY, hue: 120 }).matrix) assert.ok(Math.abs(row[0] + row[1] + row[2] - 1) < 1e-3); // greys stay grey
  assert.deepEqual(displayUniforms({ ...DISPLAY, exposure: -2 }).slope, 0.25); // exposure scales linear light, as OpenRV's matrix does
  assert.deepEqual(displayTransfer({ exposure: 1, contrast: 1, gamma: 2 }), { slope: 2, intercept: 0, exponent: 0.5 });
  const c = displayTransfer({ exposure: 0, contrast: 2, gamma: 1 });
  assert.ok(Math.abs(c.slope * 0.18 + c.intercept - 0.18) < 1e-9); // 18% grey holds still
  assert.equal(clampParam("exposure", 12), 10);
  assert.equal(displayLabel({ ...DISPLAY, exposure: 1, gamma: 2.2, channel: "r" }), "E +1.0 · γ 2.20 · Red");
  assert.equal(displayActive(DISPLAY), false);
  assert.equal(displayActive({ ...DISPLAY, invert: true }), true);
});

test("a blank plate: sides in 64s up to 1920, 8k + 1 frames, a trained frame rate; keyframes on the LTX grid", () => {
  assert.deepEqual(blankSpec({ width: 1000, height: 500, fps: 30, frames: 100 }), { width: 1024, height: 512, fps: 25, frames: 97 });
  assert.deepEqual(blankSpec({ width: 4000, height: 10, fps: 60, frames: 999 }), { width: 1920, height: 256, fps: 50, frames: 321 });
  assert.deepEqual(keySlots(121).slice(0, 3), [0, 1, 9]);
  assert.deepEqual(keySlots(121).slice(-2), [113, 120]); // as the model card: 1, 9, 17, ... 113, then the last frame
  assert.deepEqual(keySlots(9), [0, 1, 8]);
  assert.equal(snapKey(60, 121), 57);
  const keys = [{ frame: 0 }, { frame: 9 }, { frame: 120 }];
  assert.equal(moveKey(keys, keys[1], 118, 121), 113); // the last frame is taken: the nearest free slot
  assert.equal(moveKey(keys, keys[1], 40, 121), 41);
  assert.deepEqual(nearKeys(keys, 50), { prev: keys[1], next: keys[2] });
  assert.equal(fluidPrompt(""), "ainvfxfluid, smoke plume");
  assert.equal(fluidPrompt("ainvfxfluid, wild fire"), "ainvfxfluid, wild fire");
  assert.equal(fluidPrompt(" thick white steam "), "ainvfxfluid, thick white steam");
});

test("time left reads in seconds, then minutes and seconds", () => {
  assert.equal(secs(5), "about 5 s left");
  assert.equal(secs(96), "about 1 min 40 s left");
  assert.equal(secs(700), "about 12 min left");
  assert.equal(secs(null), "");
  assert.equal(gb(2.5e9), "2.50 GB");
  assert.equal(gb(3e7), "30 MB");
});

test("captions name the object when given and build only the chosen tool", () => {
  const bbox = [100, 200, 300, 400];
  assert.match(caption({ tool: "erase", words: "black umbrella", colors: [], color: "#000000", bbox }), /^Remove the black umbrella inside <obj_1>/);
  assert.match(caption({ tool: "erase", words: "", colors: [], color: "#000000", bbox }), /^Remove the object inside/);
  assert.match(caption({ tool: "paint", words: "a cactus", colors: ["#3d7a35"], color: "#3d7a35", bbox }), /with a cactus, in exactly/);
  const light = caption({ tool: "light", words: "", colors: ["#ffd890", "#000000"], color: "#ffd890", bbox });
  assert.match(light, /warm orange light/);
  assert.match(light, /Dark strokes are hints/);
  assert.ok(light.endsWith(JSON.stringify([{ id: "obj_1", bbox, desc: "light source" }])));
});

test("an edit is made again only when something it saw changed", () => {
  const foot = (cells) => ({ bits: Array.from({ length: 16 }, (_, i) => (cells.includes(i) ? 1 : 0)) });
  const a = { id: 1, version: 1, tool: "erase", foot: foot([0, 1]) };
  const paint = { tool: "paint", foot: foot([10, 11]) };
  assert.equal(dependsOnChange(paint, [a], [a]), false); // nothing below it changed
  assert.equal(dependsOnChange(paint, [], [a]), false); // the erase below went, elsewhere on the frame
  assert.equal(dependsOnChange({ ...paint, foot: foot([1, 2]) }, [], [a]), true); // it overlapped
  assert.equal(dependsOnChange(paint, [{ ...a, tool: "light" }], []), true); // a relight came below it
  assert.equal(dependsOnChange({ ...paint, tool: "light" }, [], [a]), true); // a relight sees everything
});

test("the frame cache keeps the frame on screen first, frames ahead before frames behind, round the loop", () => {
  const view = { frame: 50, inPt: 0, outPt: 99 };
  assert.equal(frameUse(50, view), Infinity);
  assert.ok(frameUse(52, view) > frameUse(48, view)); // 2 ahead beats 2 behind
  assert.ok(frameUse(1, { ...view, frame: 98 }) > frameUse(90, { ...view, frame: 98 })); // just past the loop point is close
  assert.ok(frameUse(120, { frame: 50, inPt: 0, outPt: 99 }) < frameUse(0, view)); // outside the range counts least
});

test("optional links drop with what fed them when their slots are empty", () => {
  const comp = workflow("comp");
  const bare = fillWorkflow(comp, { path: "plate.mp4", shot: "output:s" });
  const fit = (wf) => Object.values(wf.prompt).find((n) => n.class_type.includes("FitToPlate"));
  assert.equal(fit(bare).inputs.mask, undefined); // no matte: the link goes
  const matted = fillWorkflow(comp, { path: "plate.mp4", shot: "output:s", matte_a: "output:m" });
  assert.ok(fit(matted).inputs.mask && Object.keys(matted.prompt).length > Object.keys(bare.prompt).length); // with what fed it
  const relight = fillWorkflow(workflow("export"), { path: "plate.exr", shot: "output:s", relight: true });
  assert.equal(Object.values(relight.prompt).some((n) => n._meta?.output === "matte"), false); // no matte to save
  assert.equal(comp.prompt[comp.slots.path[0][0]].inputs.path, ""); // filling copies: the parsed workflow stays as saved
});

test("every workflow names the outputs and the progress node the page reads", () => {
  const wanted = { ingest: ["hero", "proxy", "spec"], prompt: ["text"], edit: ["patch", "relit", "result"],
    snap: ["named", "point_0", "point_1", "point_2", "point_3", "point_4"], clean: ["frames", "video"], shot: ["frames", "video"],
    matte: ["follow", "frames"], comp: ["video"], review: ["frames", "review"], export: ["export", "matte"], warm: ["frame"] };
  for (const [name, outs] of Object.entries(wanted)) {
    const wf = workflow(name);
    assert.deepEqual(Object.keys(wf.outputs).sort(), outs.sort(), name);
    assert.equal(wf.progress.size, name === "snap" ? 0 : 1, name);
  }
});

import { pickObjects, reconcile, shotPrompt, splitTable, upsampleRequest, RIPPLE } from "../../web/logic.mjs";

test("the upsampler request locks one row in Klein's edit format, and a relight stays plain", () => {
  const erase = upsampleRequest({ tool: "erase", words: "red umbrella", bbox: [342, 404, 428, 556] });
  assert.equal(erase.mode, "table");
  assert.deepEqual(erase.locked, [{ id: "obj_1", from: "ref_image_0", src_bbox: [342, 404, 428, 556], tgt_bbox: null, desc: "red umbrella" }]);
  assert.match(erase.request, /"src_bbox": \[342, 404, 428, 556\], "tgt_bbox": null/); // json.dumps spacing, as BFL's code writes it
  assert.equal(upsampleRequest({ tool: "paint", words: "a fire", bbox: [1, 2, 3, 4] }).locked[0].from, "target");
  const light = upsampleRequest({ tool: "light", words: "night time", bbox: [0, 0, 1000, 1000] });
  assert.equal(light.mode, "plain"); assert.equal(light.locked, null); assert.match(light.request, /night time/);
});

test("reconcile keeps the locked row, takes the upsampler's description and its cited rows, and survives a cut-off table", () => {
  const locked = [{ id: "obj_1", from: "ref_image_0", src_bbox: [342, 404, 428, 556], tgt_bbox: null, desc: "red umbrella" }];
  const answer = 'Remove the umbrella <obj_1> above the figure <person_1>. [{"id": "obj_1", "from": "ref_image_0", "src_bbox": [1, 1, 900, 900], ' +
    '"tgt_bbox": null, "desc": "A broad red umbrella."}, {"id": "person_1", "from": "ref_image_0", "src_bbox": [401, 452, 807, 531], ' +
    '"tgt_bbox": [401, 452, 807, 531], "desc": "A figure in a coat."}, {"id": "ghost_1", "from": "target", "src_bbox": null, "tgt_bbox": [1, 1, 5, 5], "desc": "x"}]';
  const [caption, rows] = splitTable(reconcile(answer, locked));
  assert.equal(caption, "Remove the umbrella <obj_1> above the figure <person_1>.");
  assert.deepEqual(rows[0], { ...locked[0], desc: "A broad red umbrella." }); // box kept, description adopted
  assert.equal(rows[1].id, "person_1"); assert.equal(rows.length, 2); // ghost_1 is not cited: dropped
  const [, cut] = splitTable(reconcile('Remove the umbrella <obj_1>. [{"id": "obj_1", "from": "ref_ima', locked));
  assert.deepEqual(cut, locked);
});

test("the shot prompt names paint and light, never an erase", () => {
  assert.equal(shotPrompt([]), RIPPLE);
  const p = shotPrompt([{ tool: "erase", words: "red umbrella" }, { tool: "paint", words: "an explosion" }, { tool: "light", words: "night" }]);
  assert.ok(!p.includes("umbrella")); assert.match(p, /Added in the first frame: an explosion/); assert.match(p, /relit: night/);
});

test("whole object: named instances the stroke touches win; points keep only objects two of them agree on", () => {
  const W = 10, H = 10, area = W * H, mask = (cells) => { const m = new Uint8Array(area); for (const [x, y] of cells) m[y * W + x] = 1; return m; };
  const box = (x0, y0, x1, y1) => mask([...Array(area).keys()].map((i) => [i % W, (i / W) | 0]).filter(([x, y]) => x >= x0 && x < x1 && y >= y0 && y < y1));
  const van = box(3, 3, 6, 6), road = box(0, 8, 10, 10), sky = box(0, 0, 10, 3), stroke = box(4, 4, 5, 9);
  assert.deepEqual(pickObjects({ painted: stroke, named: [van, box(8, 0, 9, 1)], points: [], area }), [van]);
  assert.deepEqual(pickObjects({ painted: stroke, named: [], points: [van, van, road.map((v, i) => (i < 85 ? v : 0)), sky], area }), [van, van]);
  assert.deepEqual(pickObjects({ painted: stroke, named: [], points: [van], area }), [van]); // a dab: one point, one object
});

test("a stroke goes to the strokes in progress, else to the current edit of its tool, else to a new edit", () => {
  const paint = { tool: "paint" }, erase = { tool: "erase" };
  assert.equal(strokeTarget({ draft: paint, current: erase, tool: "paint" }), "draft");
  assert.equal(strokeTarget({ draft: null, current: paint, tool: "paint" }), "current");
  assert.equal(strokeTarget({ draft: null, current: paint, tool: "erase" }), "new");
  assert.equal(strokeTarget({ draft: null, current: null, tool: "light" }), "new");
});

test("another tool than the edit being worked on starts a new edit; the same tool keeps it", () => {
  const paint = { tool: "paint" };
  assert.equal(toolEndsEdit({ draft: null, current: paint }, "light"), true);
  assert.equal(toolEndsEdit({ draft: paint, current: null }, "erase"), true);
  assert.equal(toolEndsEdit({ draft: null, current: paint }, "paint"), false);
  assert.equal(toolEndsEdit({ draft: null, current: null }, "erase"), false);
});

test("a failed step says why in plain words", () => {
  assert.equal(plainError("PaintAPlate_LoadPlate: No image frames found in /w/ComfyUI/output/paintaplate/a1/v2/matte_b_640x352"),
    "the paint matte saved no frames, so there was nothing to read.");
  assert.equal(plainError("PaintAPlate_LoadPlate: No image frames found in /w/output/paintaplate/a1/v2/640x352/clean"), "the erase pass saved no frames, so there was nothing to read.");
  assert.equal(plainError("KSampler: CUDA out of memory. Tried to allocate 2 GiB"), "the GPU ran out of memory.");
  assert.equal(plainError("PaintAPlate_LoadPlate: Plate path leaves the ComfyUI folders: ../x"), "the file is outside ComfyUI's input and output folders.");
  assert.equal(plainError("UNETLoader: Value not in list: unet_name: 'x.safetensors' not in []"), "a model or a node it needs is missing.");
  assert.equal(plainError("something odd"), "ComfyUI stopped with an error.");
});

test("the paint matte starts where the edit changed the first frame, inside the paint zones", () => {
  const px = (r, g, b) => [r, g, b, 255];
  const a = new Uint8ClampedArray([...px(200, 50, 20), ...px(10, 10, 10), ...px(90, 90, 90), ...px(200, 0, 0)]);
  const b = new Uint8ClampedArray([...px(10, 10, 10), ...px(10, 10, 10), ...px(80, 90, 90), ...px(0, 0, 0)]);
  const z = new Uint8ClampedArray([...px(255, 255, 255), ...px(255, 255, 255), ...px(255, 255, 255), ...px(0, 0, 0)]);
  assert.deepEqual([...changedMask(a, b, z)], [1, 0, 0, 0]);
});

test("an erase painted in separate parts locks one box per part and asks to remove nothing else", () => {
  const boxes = [[0, 0, 120, 508], [0, 492, 471, 758]];
  const ask = upsampleRequest({ tool: "erase", words: "", bbox: [0, 0, 471, 758], boxes });
  assert.deepEqual(ask.locked.map((r) => [r.id, r.src_bbox, r.tgt_bbox]), [["obj_1", boxes[0], null], ["obj_2", boxes[1], null]]);
  assert.match(ask.request, /Remove the objects <obj_1> and <obj_2> completely, with their shadows/);
  assert.match(ask.request, /Remove nothing else\./);
  const one = upsampleRequest({ tool: "erase", words: "van", bbox: [10, 20, 30, 40], boxes: [[10, 20, 30, 40]] });
  assert.deepEqual(one.locked.map((r) => r.src_bbox), [[10, 20, 30, 40]]);
  assert.match(one.request, /Remove the van <obj_1> completely, with its shadow and its reflection, and continue the background behind it\. Remove nothing else\./);
});

test("the paint splits into a few tight boxes, so what stands between the strokes stays out of them", () => {
  const w = 96, h = 54, bits = new Uint8Array(w * h);
  for (let y = 0; y < 5; y++) for (let x = 0; x < 48; x++) bits[y * w + x] = 1; // a truss along the top
  for (let y = 0; y < 25; y++) for (let x = 47; x < 50; x++) bits[y * w + x] = 1; // a mast that joins it
  const boxes = paintBoxes({ bits, w, h });
  const inside = (y, x) => boxes.some(([y1, x1, y2, x2]) => y >= y1 && y <= y2 && x >= x1 && x <= x2);
  assert.equal(boxes.length, 2, JSON.stringify(boxes));
  assert.ok(inside(40, 200) && inside(300, 505), "every painted part is in a box");
  assert.ok(!inside(300, 200), "the place between them, where an astronaut stood, is in none");
  assert.deepEqual(paintBoxes({ bits: new Uint8Array(w * h), w, h }), []);
});

test("a caption must erase what was painted: a locked box it cites, or removed rows that hold the paint", () => {
  const w = 100, h = 50, bits = new Uint8Array(w * h);
  for (let y = 0; y < 11; y++) for (let x = 60; x < 80; x++) bits[y * w + x] = 1;
  const paint = { bits, w, h }, locked = [{ id: "obj_1", from: "ref_image_0", src_bbox: [0, 600, 220, 800], tgt_bbox: null, desc: "the object to remove" }];
  const row = (id, src_bbox, desc) => ({ id, from: "ref_image_0", src_bbox, tgt_bbox: null, desc });
  const astronaut = `Remove the astronaut <person_1>. Keep every other element unchanged. ${JSON.stringify([...locked, row("person_1", [400, 180, 600, 240], "An astronaut")])}`;
  const crane = `Remove the crane <crane_1> completely. ${JSON.stringify([...locked, row("crane_1", [0, 590, 230, 810], "A crane")])}`;
  assert.equal(erasesPaint(astronaut, locked, paint), false, "the paint holds no astronaut: the page's own caption is used");
  assert.equal(erasesPaint(crane, locked, paint), true);
  assert.equal(erasesPaint(`Remove the object <obj_1>. ${JSON.stringify(locked)}`, locked, paint), true);
});

test("the erase pass's prompt is the scene as it stays: no people, no text, nothing erased", () => {
  const rows = [{ id: "obj_1", from: "ref_image_0", src_bbox: [1, 2, 3, 4], tgt_bbox: null, desc: "the van" },
    { id: "street_1", from: "ref_image_0", src_bbox: [0, 0, 1000, 1000], tgt_bbox: [0, 0, 1000, 1000], desc: "A wet asphalt street at night" },
    { id: "person_1", from: "ref_image_0", src_bbox: [10, 10, 50, 20], tgt_bbox: [10, 10, 50, 20], desc: "A man walking" },
    { id: "En_Text_1", from: "ref_image_0", src_bbox: [10, 10, 90, 90], tgt_bbox: [10, 10, 90, 90], desc: "A sign that reads OPEN" }];
  const caption = `Remove the van <obj_1>. ${JSON.stringify(rows)}`;
  assert.equal(erasePrompt([caption, caption]), "A wet asphalt street at night.");
  assert.equal(erasePrompt(["Remove the van <obj_1>.", undefined]), "");
});

test("the full size's first stage is half the working size, in multiples of 32", () => {
  assert.deepEqual(stageOne([1920, 1088]), [960, 544]);
  assert.deepEqual(stageOne([1280, 704]), [640, 352]);
  assert.deepEqual(stageOne([1920, 800]), [960, 416]);
});

test("the render queue: every preview first, then every full size, then every export; the set on show first, then the newest", () => {
  const r = (id, cls, current = false, wanted = 1, urgent = false) => ({ id, cls, current, wanted, urgent });
  assert.equal(nextRender([r("on show", "full", true, 3), r("older", "preview", false, 2)]), "older", "a preview before any full size");
  assert.equal(nextRender([r("a", "preview", false, 1), r("b", "preview", false, 2), r("c", "preview", true, 3)]), "c");
  assert.equal(nextRender([r("a", "full", false, 1), r("b", "full", false, 2)]), "b", "then the most recently shown");
  assert.equal(nextRender([r("other", "full", false, 2), r("on show", "export", true, 3)]), "other", "an export waits for the full sizes");
  assert.equal(nextRender([r("other", "full", false, 2), r("on show", "export", true, 1, true)]), "on show", "unless someone waits for it");
  assert.equal(nextRender([r("done", null), r("failed", undefined)]), null);
});

test("Generate stops only a full-size or export step in its first half", () => {
  assert.equal(stopsForEdit({ cls: "full", progress: 0.3 }), true);
  assert.equal(stopsForEdit({ cls: "export", progress: 0.1 }), true);
  assert.equal(stopsForEdit({ cls: "full", progress: 0.6 }), false, "past halfway it finishes");
  assert.equal(stopsForEdit({ cls: "preview", progress: 0.05 }), false, "a preview step always finishes");
});

test("a job index key leaves out output folders and the live preview rate, and keeps every value that changes the result", () => {
  const a = indexValues({ seed: 4, prefix: "paintaplate/x/v1/clean/f", video_prefix: "v1/clean", live: 2, hero: "up/ab.png", prompt: "A street." });
  assert.deepEqual(a, [["hero", "up/ab.png"], ["prompt", "A street."], ["seed", 4]]);
  assert.deepEqual(indexValues({ prompt: "A street.", hero: "up/ab.png", seed: 4, matte_prefix: "v9/m" }), a, "in any order, from any session");
});

test("the colour picker averages the pixels under the cursor", () => {
  assert.equal(pickedColor(new Uint8ClampedArray([255, 0, 0, 255, 0, 0, 255, 255])), "#800080");
  assert.equal(pickedColor(new Uint8ClampedArray([10, 20, 30, 255, 200, 200, 200, 0])), "#0a141e"); // outside the frame: not counted
  assert.equal(pickedColor(new Uint8ClampedArray([0, 0, 0, 0])), null);
});


import { browseItems, crumbs, framePattern, ocioTree } from "../../web/logic.mjs";

test("the OCIO menu's File Color Space tree follows the families, as RV builds it", () => {
  const tree = ocioTree([{ name: "ACEScg", family: "ACES" }, { name: "ARRI LogC4", family: "Input/ARRI" }, { name: "Sony S-Log3", family: "Input/Sony" }, { name: "Raw", family: "" }]);
  assert.deepEqual(tree.spaces, ["Raw"]);
  assert.deepEqual(tree.children.map((c) => c.name), ["ACES", "Input"]);
  assert.deepEqual(tree.children[1].children.map((c) => [c.name, c.spaces]), [["ARRI", ["ARRI LogC4"]], ["Sony", ["Sony S-Log3"]]]);
});

test("the plate browser: folders first, numbers in order or newest first, a filter on the name, breadcrumbs, frame patterns", () => {
  const items = [{ name: "shot10.mp4", kind: "video", mtime: 3 }, { name: "renders", kind: "folder", mtime: 1 }, { name: "shot2.mp4", kind: "video", mtime: 9 },
    { name: "ComfyUI_#####_.png", kind: "sequence", mtime: 5 }];
  assert.deepEqual(browseItems(items).map((i) => i.name), ["renders", "ComfyUI_#####_.png", "shot2.mp4", "shot10.mp4"]);
  assert.deepEqual(browseItems(items, { by: "newest" }).map((i) => i.name), ["renders", "shot2.mp4", "ComfyUI_#####_.png", "shot10.mp4"]);
  assert.deepEqual(browseItems(items, { query: "SHOT" }).map((i) => i.name), ["shot2.mp4", "shot10.mp4"]);
  assert.deepEqual(crumbs("output:video/a"), [{ label: "Output", path: "output:" }, { label: "video", path: "output:video" }, { label: "a", path: "output:video/a" }]);
  assert.deepEqual(crumbs(""), [{ label: "Input", path: "" }]);
  assert.equal(framePattern("frames_00001_.exr"), "frames_#####_.exr");
  assert.equal(framePattern("shot.1001.exr"), "shot.####.exr");
});

test("a divider's drag stays inside the window and never squeezes a panel or the stage under its least", () => {
  const side = { least: 220, stage: 320, around: 84 }, log = { least: 60, stage: 240, around: 90 };
  const view = { width: 1400, height: 900 };
  assert.equal(panelSize("side", 408, view, side), 408);
  assert.equal(panelSize("side", 2000, view, side), 996); // 1400 - 84 - 320: the stage keeps 320 px
  assert.equal(panelSize("side", 100, view, side), 220);
  assert.equal(panelSize("side", 300, { width: 500, height: 900 }, side), 220); // a narrow window: the panel's least wins
  assert.equal(panelSize("log", 330.4, view, log), 330);
  assert.equal(panelSize("log", 900, view, log), 570); // 900 - 90 - 240
  assert.equal(panelSize("log", 10, view, log), 60);
});
