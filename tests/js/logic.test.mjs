// The page's pure rules (web/logic.mjs), run by `node --test tests/js` (tests/test_web.py runs it too).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { changedMask, DISPLAY, blankSpec, caption, clampParam, fluidPrompt, keySlots, moveKey, nearKeys, snapKey, dependsOnChange, displayActive, displayLabel, displayMatrix, displayTransfer, fillWorkflow, fitSize, frameUse, gb, parseWorkflow, plainError, previewSize, previewSizes, secs, strokeTarget, toolEndsEdit } from "../../web/logic.mjs";

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
  assert.equal(displayMatrix(DISPLAY), "1 0 0 0 0 0 1 0 0 0 0 0 1 0 0 0 0 0 1 0");
  assert.equal(displayMatrix({ ...DISPLAY, channel: "r" }), "1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 0 0 0 1 0");
  assert.equal(displayMatrix({ ...DISPLAY, channel: "l" }), "0.2126 0.7152 0.0722 0 0 0.2126 0.7152 0.0722 0 0 0.2126 0.7152 0.0722 0 0 0 0 0 1 0");
  assert.equal(displayMatrix({ ...DISPLAY, invert: true }), "-1 0 0 0 1 0 -1 0 0 1 0 0 -1 0 1 0 0 0 1 0");
  assert.deepEqual(displayMatrix({ ...DISPLAY, saturation: 0 }).split(" ").map(Number).slice(0, 3), [0.2126, 0.7152, 0.0722]);
  const spun = displayMatrix({ ...DISPLAY, hue: 120 }).split(" ").map(Number); // every row still sums to 1: greys stay grey
  for (const r of [0, 5, 10]) assert.ok(Math.abs(spun[r] + spun[r + 1] + spun[r + 2] - 1) < 1e-3);
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
    matte: ["follow", "frames"], comp: ["video"], export: ["export", "matte", "review"], warm: ["frame"] };
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
