// The page's pure rules (web/logic.mjs), run by `node --test tests/js` (tests/test_web.py runs it too).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { changedMask, erasePrompt, erasesPaint, indexValues, nextRender, paintBoxes, pickedColor, stageOne, stopsForEdit, blankSpec, caption, fluidPrompt, keySlots, moveKey, nearKeys, snapKey, dependsOnChange, fillWorkflow, fitSize, frameUse, gb, parseWorkflow, plainError, previewSize, previewSizes, secs, strokeTarget, toolEndsEdit, panelSize, hdrPlate, wantsHdr, hdrFps, blankDepth, escapeAction } from "../../web/logic.mjs";

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
  assert.match(caption({ tool: "paint", words: "a cactus", colors: ["#3d7a35"], color: "#3d7a35", bbox }), /with a cactus, following the drawing's outline, pose and size, in exactly/); // a paint keeps the drawing's shape and the image's style
  const light = caption({ tool: "light", words: "", colors: ["#ffd890", "#000000"], color: "#ffd890", bbox });
  assert.equal(light, lightPlanCaption({ colors: ["#ffd890", "#000000"], color: "#ffd890", words: "" })); // a relight's request is the page's own
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
    matte: ["follow", "frames", "movie"], comp: ["video"], review: ["frames", "review", "view"], export: ["exr", "export", "matte", "matte_movie"], warm: ["frame"],
    fluid: ["control", "plate", "video"] };
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
  const light = upsampleRequest({ tool: "light", words: "night time", bbox: [0, 0, 1000, 1000], colors: ["#388e3c"], color: "#388e3c" });
  assert.equal(light.mode, "plain"); assert.equal(light.locked, null); // no prompt writer for a relight: the light plan says it
  assert.equal(light.request, lightPlanCaption({ colors: ["#388e3c"], color: "#388e3c", words: "night time" }));
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
  const p = shotPrompt([{ tool: "erase", words: "red umbrella" }, { tool: "paint", words: "an explosion" }, { tool: "light", words: "night", hue: "cool blue" }]);
  assert.ok(!p.includes("umbrella")); assert.match(p, /Added in the first frame: an explosion/); assert.match(p, /relit with cool blue light: night/);
  assert.match(shotPrompt([{ tool: "light", words: "", hue: "green" }]), /relit with green light; this new light holds/); // no words: the colour still counts
});

test("the in-frame colour picker averages the pixels under the click", () => {
  assert.equal(pickedColor(new Uint8ClampedArray([255, 0, 0, 255, 0, 0, 255, 255])), "#800080");
  assert.equal(pickedColor(new Uint8ClampedArray([10, 20, 30, 255, 200, 200, 200, 0])), "#0a141e"); // outside the frame: not counted
  assert.equal(pickedColor(new Uint8ClampedArray([0, 0, 0, 0])), null);
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
  const gone = "ComfyUI did not answer: it may be restarting, or the connection dropped."; // a pod restarted under the page (29 Oct)
  assert.equal(plainError(`Unexpected token '<', "<!DOCTYPE "... is not valid JSON`), gone);
  assert.equal(plainError("No answer from ComfyUI (HTTP 502, an error page): it may be restarting, or the connection dropped"), gone);
  assert.equal(plainError("Failed to fetch"), gone);
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

import { fluidWipeLeft } from "../../web/logic.mjs";

test("the wipe on a fluid row shows the step's input on the left: black, the keyframes, the SDR shot", () => {
  assert.equal(fluidWipeLeft("fluid_keys"), "black");
  assert.equal(fluidWipeLeft("fluid_shot"), "fluid_keys");
  assert.equal(fluidWipeLeft("fluid_hdr"), "fluid_shot");
  assert.equal(fluidWipeLeft("full"), null);
  assert.equal(fluidWipeLeft(null), null);
});

import { plateStem } from "../../web/logic.mjs";

test("a plate's name keeps a movie's trailing digits and drops only an image sequence's frame number", () => {
  assert.equal(plateStem("plates/train_v2.mp4", false), "train_v2");
  assert.equal(plateStem("chalet_v2.mp4", false), "chalet_v2");
  assert.equal(plateStem("C:\\plates\\room.1001.exr", true), "room");
  assert.equal(plateStem("shot_v3_0001.png", true), "shot_v3");
  assert.equal(plateStem("still_2.png", false), "still_2"); // a single image: its digits are part of its name
  assert.equal(plateStem("", false), "plate");
});

import { warmEnd } from "../../web/logic.mjs";

test("the model warm-up's last line: on the status line only while the start's message is there, and never « every model loaded » after a cancel", () => {
  assert.deepEqual(warmEnd(12.4, 0, true), { status: true, text: "Ready: every model loaded in 12 s, so the first edit starts at once. Open a plate." });
  assert.deepEqual(warmEnd(12.4, 0, false), { status: false, text: "Model warm-up done in 12 s: every model loaded." }); // a plate opened or closed since
  const stopped = warmEnd(3, 1, true); // a close cancelled one job: its model is not loaded
  assert.equal(stopped.status, false);
  assert.match(stopped.text, /1 of its jobs did not finish/);
  assert.doesNotMatch(stopped.text, /every model loaded/);
});

test("SDR to HDR: on by default for an EXR plate, off for the others, its switch for every plate; relit, never; 16-bit blank plates; 30 fps at most", () => {
  const exr = { kind: "sequence", ext: ".EXR" }, png = { kind: "sequence", ext: ".png" }, mp4 = { kind: "video", ext: ".mp4" };
  assert.equal(hdrPlate(exr), true);
  assert.equal(hdrPlate(png), false);
  assert.equal(hdrPlate(mp4), false);
  assert.equal(wantsHdr(exr, ["paint", "erase"], true), true);
  assert.equal(wantsHdr(exr, ["paint"], false), false);
  assert.equal(wantsHdr(exr, ["paint", "light"], true), false); // a relight keeps the plate's own values
  assert.equal(wantsHdr(mp4, ["paint"], true), true, "switched on for a video plate, it runs");
  assert.equal(wantsHdr(mp4, ["paint"], false), false);
  assert.deepEqual([blankDepth("16"), blankDepth("8"), blankDepth("32"), blankDepth(undefined)], [16, 8, 8, 8]);
  assert.deepEqual([hdrFps(24), hdrFps(50), hdrFps(0)], [24, 30, 24]);
});

test("Esc does one thing at a time: the edit in progress, then the selection, then what generates", () => {
  assert.equal(escapeAction({ editing: true, selected: true, generating: true }), "discard");
  assert.equal(escapeAction({ editing: false, selected: true, generating: true }), "deselect");
  assert.equal(escapeAction({ editing: false, selected: false, generating: true }), "stop");
  assert.equal(escapeAction({ editing: false, selected: false, generating: false }), null);
});

import { dabAlpha, dabFlow, dabsAlong } from "../../web/logic.mjs";

test("Esc cancels a plate that is opening before anything else", () => {
  assert.equal(escapeAction({ opening: true, editing: true, selected: true, generating: true }), "cancelOpen");
  assert.equal(escapeAction({ editing: false, selected: false, generating: true }), "stop");
});

test("light dabs fall at a fixed spacing, however the stroke's points arrive", () => {
  const pts = [[0, 0, 10], [3, 0, 10], [40, 0, 10], [41, 0, 10], [100, 0, 10]], spacing = (r) => r * 0.25;
  const all = dabsAlong(pts, 0, spacing).dabs;
  let carry = 0, parts = [];
  for (let i = 0; i < pts.length; i++) { const got = dabsAlong(pts.slice(0, i + 1), i, spacing, carry); parts = parts.concat(got.dabs); carry = got.carry; }
  assert.deepEqual(parts, all); // drawn as the pointer moves or in one pass: the same dabs
  assert.deepEqual(all[0], [0, 0, 10]);
  assert.equal(all.length, 41); // every 2.5 px from 0 to 100
  for (let i = 1; i < all.length; i++) assert.ok(Math.abs(all[i][0] - all[i - 1][0] - 2.5) < 1e-9);
});

test("one light stroke adds its flow on its centre line, whatever the spacing", () => {
  for (const spacing of [0.25, 0.2, 0.5]) {
    let sum = 0;
    for (let k = -20; k <= 20; k++) sum += dabFlow(0.3, spacing) * dabAlpha(Math.abs(k * spacing));
    assert.ok(Math.abs(sum - 0.3) < 1e-9, `${spacing}: ${sum}`);
  }
  assert.equal(dabAlpha(0), 1);
  assert.equal(dabAlpha(1), 0);
  assert.ok(Math.abs(dabAlpha(0.375) - 0.675) < 1e-9);
});

import { donorFor } from "../../web/logic.mjs";

test("a bypass takes the frames of a render of more edits when the edits left out are far away", () => {
  const foot = (cells) => { const bits = new Uint8Array(16); for (const c of cells) bits[c] = 1; return { w: 4, h: 4, bits }; };
  const A = { id: 1, version: 1, tool: "paint", foot: foot([0, 1]) }, B = { id: 2, version: 1, tool: "paint", foot: foot([14, 15]) };
  const C = { id: 3, version: 1, tool: "erase", foot: foot([1, 2]) }, D = { id: 5, version: 1, tool: "paint", foot: foot([12]) };
  const L = { id: 4, version: 1, tool: "light", foot: foot([...Array(16).keys()]) };
  const r = (key, active, wanted = 1) => ({ key, active, wanted });
  assert.equal(donorFor([A], [r("AB", [A, B])]), "AB"); // far apart: either one can be left out
  assert.equal(donorFor([B], [r("AB", [A, B])]), "AB");
  assert.equal(donorFor([A], [r("AC", [A, C])]), null); // touching: rendered again
  assert.equal(donorFor([A], [r("AL", [A, L])]), null); // a light changes every pixel
  assert.equal(donorFor([L], [r("AL", [A, L])]), null);
  assert.equal(donorFor([A], [r("A", [A])]), null); // only a larger set
  assert.equal(donorFor([A], [r("AB2", [A, { ...B, version: 2 }]), r("ABx", [{ ...A, version: 2 }, B])]), "AB2"); // the same result of A
  assert.equal(donorFor([A], [r("ABD", [A, B, D], 5), r("AB", [A, B], 1)]), "AB"); // the fewest edits left out
  assert.equal(donorFor([A], [r("AB", [A, B], 1), r("AD", [A, D], 2)]), "AD"); // then the most recently shown
  assert.equal(donorFor([A], [r("AB", [A, { ...B, foot: null }])]), null); // no footprint: counted as near
});

import * as fsp from "node:fs";

test("a light's shade is an optional input of its edit, gone without shade strokes", () => {
  const wf = parseWorkflow(JSON.parse(fsp.readFileSync(new URL("../../web/workflows/edit.json", import.meta.url))));
  const find = (w, test) => Object.values(w.prompt).find(test);
  const relit = (w) => find(w, (n) => n.class_type === "PaintAPlate_RelightTransfer");
  const loader = (w, title) => find(w, (n) => n._meta?.title?.startsWith(title));
  const plain = fillWorkflow(wf, { caption: "x", seed: 1 }); // not a light: no relight, no shade, no light plan, and no error
  assert.equal(relit(plain), undefined);
  assert.equal(loader(plain, "Painted shade"), undefined);
  assert.equal(loader(plain, "Light plan"), undefined);
  const lit = fillWorkflow(wf, { caption: "x", seed: 1, relight: 1, plan: "p.png", shade: "s.png" });
  assert.ok(Array.isArray(relit(lit).inputs.shade)); // the shade strokes, darkened as painted
  assert.ok(Array.isArray(find(lit, (n) => n.class_type === "ReferenceMultiLatent").inputs["images.image1"])); // the light plan, Klein's second reference
  const bare = fillWorkflow(wf, { caption: "x", seed: 1, relight: 1, plan: "p.png" }); // a relight without shade strokes still runs
  assert.ok(relit(bare) && !("shade" in relit(bare).inputs));
  assert.equal(loader(bare, "Painted shade"), undefined);
});

import { viewerSpace, drawsDeep, fluidRun, passMovie, defaultDepth } from "../../web/logic.mjs";

test("an image sequence's 8-bit movies hold log values; playing, one kind of frame", () => {
  assert.equal(viewerSpace(["ACEScg", "ACEScct", "ACES2065-1"], "sRGB Encoded Rec.709 (sRGB)"), "ACEScct");
  assert.equal(viewerSpace(["Linear Rec.709"], "sRGB"), "sRGB");
  assert.equal(drawsDeep(false, false), true, "paused: the precise frame");
  assert.equal(drawsDeep(true, false), false, "playing while the precise frames arrive: the movie only");
  assert.equal(drawsDeep(true, true), true, "playing with every precise frame in: those only");
});

test("a fluid shot exports from its own folder; a blank plate is 16-bit when SDR to HDR can run", () => {
  assert.equal(fluidRun("output:paintaplate/p1/fluid_v2/hdr"), "paintaplate/p1/fluid_v2");
  assert.equal(fluidRun("paintaplate/p1/fluid_v2/plate/blank_960x512.mov"), "paintaplate/p1/fluid_v2");
  assert.equal(defaultDepth(true), 16);
  assert.equal(defaultDepth(false), 8);
});

test("the Render panel shows each finished pass that made a movie", () => {
  const r = { raw: "full.mp4", cleanRaw: "cleanfull.mp4", hdrMovie: "hdr.mp4", play: "view.mp4", playSpace: "ACEScct", review: "review.mp4",
    reviewFrames: "output:x/frames_#####_.exr" }, pv = { raw: "shot.mp4", comp: "comp.mp4", cleanRaw: "clean.mp4" };
  assert.deepEqual(passMovie("comp", r, pv), { url: "comp.mp4", space: "@model", frames: null });
  assert.deepEqual(passMovie("clean", r, pv), { url: "clean.mp4", space: "@model", frames: null });
  assert.deepEqual(passMovie("review", r, pv), { url: "view.mp4", space: "ACEScct", frames: "output:x/frames_#####_.exr" });
  assert.deepEqual(passMovie("review", { review: "review.mp4", reviewSpace: "Rec.1886" }, pv), { url: "review.mp4", space: "Rec.1886", frames: null });
  assert.deepEqual(passMovie("hdr", r, pv, { log: "ACEScct" }), { url: "hdr.mp4", space: "ACEScct", frames: null, framesSpace: null });
  assert.equal(passMovie("track", r, pv), null);
  assert.equal(passMovie("full", {}, pv), null);
});

test("Esc takes a pass on show back to the latest, after the selection and before a stop", () => {
  assert.equal(escapeAction({ editing: false, selected: false, pinned: true, generating: true }), "latest");
  assert.equal(escapeAction({ editing: false, selected: true, pinned: true, generating: true }), "deselect");
  assert.equal(escapeAction({ editing: false, selected: false, pinned: false, generating: true }), "stop");
});

test("a dropped link takes the nodes that only fed it: none is left feeding nothing", () => {
  const wf = workflow("review"), out = fillWorkflow(wf, { view_prefix: "", frames_prefix: "" });
  const used = new Set(Object.values(out.prompt).flatMap((n) => Object.values(n.inputs).filter(Array.isArray).map((v) => String(v[0]))));
  assert.deepEqual(Object.entries(out.prompt).filter(([id, n]) => !used.has(id) && !n._meta?.output).map(([, n]) => n.class_type), []);
  assert.ok(!out.prompt[wf.outputs.view] && fillWorkflow(wf, { view_prefix: "p/review/view" }).prompt[wf.outputs.view]);
});

import { lightPlanCaption, lightColors } from "../../web/logic.mjs";

test("a relight's request: the light plan's colours and words, the shade only when painted", () => {
  const warm = lightPlanCaption({ colors: ["#ffa040"], color: "#ffa040", words: "night outside" });
  assert.match(warm, /^Relight the first image with the light planned in the second image/);
  assert.match(warm, /with that colour \(warm orange\)\. Night outside\. Make the light source itself visible/);
  assert.doesNotMatch(warm, /deep shadow/);
  assert.match(lightPlanCaption({ colors: ["#ffa040", "#101010"], color: "#ffa040" }), /The black strokes mark areas that must fall into deep shadow\./);
  assert.equal(lightColors(["#ffa040", "#5aa0ff", "#ffa040"], "#ffd890").split(" and ").length, 2); // two colours, each named once
});

import { fluidPasses, dataSpace, MATTE_PASSES } from "../../web/logic.mjs";

test("the tracking steps and the export show their matte, grey, through the config's data colour space", () => {
  const r = { erased: { found: { movie_a: "erase.mp4" } }, full: { found: { movie_a: "erase.mp4", movie_b: "paint_full.mp4" } },
    exported: { matte: "export_matte.mp4" } }, pv = { painted: { found: { movie_b: "paint_640.mp4" } } };
  const spaces = { log: "ACEScct", data: "Raw" };
  assert.deepEqual(passMovie("erase", r, pv, spaces), { url: "erase.mp4", space: "Raw", frames: null });
  assert.deepEqual(passMovie("track", r, pv, spaces), { url: "paint_640.mp4", space: "Raw", frames: null });
  assert.deepEqual(passMovie("trackfull", r, pv, spaces), { url: "paint_full.mp4", space: "Raw", frames: null });
  assert.deepEqual(passMovie("export", r, pv, spaces), { url: "export_matte.mp4", space: "Raw", frames: null });
  assert.equal(passMovie("trackfull", {}, pv, spaces), null, "no full-size paint matte yet: no row to click");
  assert.equal(passMovie("erase", r, pv).space, "@model", "a config without a data space: the model space");
  assert.deepEqual([...MATTE_PASSES].sort(), ["erase", "export", "track", "trackfull"]);
  const h = { hdrMovie: "hdr.mp4", hdrFrames: "output:p/v1/full/hdr/f_#####_.exr" };
  assert.deepEqual(passMovie("hdr", h, pv, { log: "ACEScct", hdr: "ACES2065-1" }),
    { url: "hdr.mp4", space: "ACEScct", frames: "output:p/v1/full/hdr/f_#####_.exr", framesSpace: "ACES2065-1" }, "SDR to HDR's row: its EXR frames, as the review row has its own");
  assert.equal(passMovie("hdr", { hdrMovie: "hdr.mp4" }, pv, { log: "ACEScct", hdr: "ACES2065-1" }).framesSpace, null, "no frames: no space");
  assert.equal(dataSpace([{ name: "ACEScg", data: false }, { name: "Raw", data: true }]), "Raw");
  assert.equal(dataSpace([{ name: "sRGB", data: false }]), null);
});

test("a fluid shot's rows: its keyframes, its shot, and SDR to HDR for a 16-bit plate", () => {
  const sdr = { control: "c.mp4", preview: "p.mp4", hdr: false, movie: null }, hdr = { ...sdr, hdr: true, movie: "h.mp4" };
  assert.deepEqual(fluidPasses(sdr).map((x) => [x.id, x.label, x.url, x.space]),
    [["fluid_keys", "Fluid: keyframes", "c.mp4", "@model"], ["fluid_shot", "Fluid: shot", "p.mp4", "@model"]]);
  assert.deepEqual(fluidPasses(hdr, { log: "ACEScct" }).at(-1), { id: "fluid_hdr", label: "Fluid: SDR to HDR", url: "h.mp4", space: "ACEScct", frames: null, framesSpace: null });
  assert.deepEqual(fluidPasses({ ...hdr, hdrFrames: "output:f/hdr/f_#####_.exr" }, { log: "ACEScct", hdr: "ACES2065-1" }).at(-1).framesSpace, "ACES2065-1",
    "its EXR frames in their own space, for the viewer to draw and inspect");
  assert.deepEqual(fluidPasses(null), [], "no fluid shot made: no rows");
  assert.deepEqual(fluidPasses({ preview: "p.mp4" }).map((x) => x.id), ["fluid_shot"], "a shot made before its control movie existed");
});

import { plateDepth, hdrKey, hdrOfKey } from "../../web/logic.mjs";

test("new content at the plate's bit depth: one rule per kind of plate", () => {
  const kinds = { "8-bit MP4": [{ kind: "video", ext: ".mp4", pix_fmt: "yuv420p" }, 8, "png", false],
    "10-bit ProRes": [{ kind: "video", ext: ".mov", pix_fmt: "yuv422p10le" }, 10, "png16", false],
    "ProRes 4444": [{ kind: "video", ext: ".mov", pix_fmt: "yuv444p12le" }, 12, "png16", false],
    "8-bit PNG": [{ kind: "sequence", ext: ".png", pix_fmt: "rgb24" }, 8, "png", false],
    "16-bit PNG": [{ kind: "sequence", ext: ".png", pix_fmt: "rgb48be" }, 16, "png16", false],
    "16-bit TIFF with alpha": [{ kind: "sequence", ext: ".tif", pix_fmt: "rgba64le" }, 16, "png16", false],
    "10-bit DPX": [{ kind: "sequence", ext: ".dpx", pix_fmt: "gbrp10le" }, 10, "png16", false],
    "half EXR": [{ kind: "sequence", ext: ".exr", pix_fmt: "gbrpf16le" }, 16, "exr", true],
    "float TIFF": [{ kind: "sequence", ext: ".tif", pix_fmt: "rgbf32le" }, 32, "exr", true],
    "float DPX": [{ kind: "sequence", ext: ".dpx", pix_fmt: "gbrpf32le" }, 32, "exr", true],
    "float EXR": [{ kind: "sequence", ext: ".exr", pix_fmt: "gbrpf32le" }, 32, "exr", true] };
  for (const [name, [spec, bits, frames, hdr]] of Object.entries(kinds))
    assert.deepEqual(plateDepth(spec), { bits, float: hdr, frames, hdr }, name);
  assert.deepEqual(plateDepth(null), { bits: 8, float: false, frames: "png", hdr: false }, "no plate: the 8-bit rule");
});

test("the SDR-to-HDR switch away from the plate's default makes another render key", () => {
  assert.equal(hdrKey("1.1", true, true), "1.1");
  assert.equal(hdrKey("1.1", true, false), "1.1|sdr", "an EXR plate switched off, as before");
  assert.equal(hdrKey("1.1", false, true), "1.1|hdr", "a video plate switched on");
  assert.equal(hdrKey("1.1", false, false), "1.1");
  assert.deepEqual(["1.1", "1.1|sdr", "1.1|hdr"].map((k) => hdrOfKey(k, true)), [true, false, true]);
  assert.deepEqual(["1.1", "1.1|sdr", "1.1|hdr"].map((k) => hdrOfKey(k, false)), [false, false, true]);
});

import { exrResult, holdsHdr } from "../../web/logic.mjs";

test("SDR to HDR on a plate that cannot hold values above 1.0 makes its result an EXR sequence", () => {
  const mp4 = { kind: "video", ext: ".mp4", pix_fmt: "yuv420p" }, png16 = { kind: "sequence", ext: ".png", pix_fmt: "rgb48be" };
  const exr = { kind: "sequence", ext: ".exr", pix_fmt: "gbrpf16le" }, tif16 = { kind: "sequence", ext: ".tif", pix_fmt: "rgb48le" };
  const tifF = { kind: "sequence", ext: ".tif", pix_fmt: "rgbf32le" }, dpx10 = { kind: "sequence", ext: ".dpx", pix_fmt: "gbrp10le" };
  assert.deepEqual([exrResult(mp4, true), exrResult(png16, true), exrResult(exr, true), exrResult(mp4, false)], [true, true, false, false]);
  assert.equal(holdsHdr(tifF), true, "a float TIFF holds them in its own format");
  assert.equal(holdsHdr({ ...dpx10, pix_fmt: "gbrpf32le" }), true, "a float DPX too");
  assert.equal(holdsHdr(dpx10, 16.3), true, "a 10-bit DPX in a log encoding holds them through its curve");
  assert.equal(holdsHdr(tif16, 222.9), true, "a 16-bit TIFF in ACEScct too");
  assert.equal(holdsHdr(tif16, 1), false, "a 16-bit TIFF in sRGB does not: its result becomes an EXR sequence");
  assert.equal(holdsHdr(mp4, 100), true, "an HDR video (PQ) keeps them in its own file: no extra files (Adrien, 3 Nov)");
  assert.equal(holdsHdr({ kind: "video", ext: ".mov", pix_fmt: "yuv444p12le" }, 55.1), true, "a log video (LogC) too");
  assert.equal(holdsHdr(mp4, 1), false, "an SDR video does not: it warns first and delivers an EXR sequence");
  assert.deepEqual([exrResult(dpx10, true, 16.3), exrResult(tif16, true, 1)], [false, true]);
});

import { bigPlateWarning } from "../../web/logic.mjs";

test("a plate above 2K warns when it opens on a card under 48 GB", () => {
  const uhd = { width: 3840, height: 2160 }, hd = { width: 1920, height: 1080 }, dci = { width: 2048, height: 1080 };
  assert.match(bigPlateWarning(uhd, 32 * 2 ** 30), /3840 x 2160, above 2K, and this card has 32 GB/);
  assert.equal(bigPlateWarning(uhd, 47.5 * 2 ** 30), null, "a 48 GB card: no warning");
  assert.equal(bigPlateWarning(uhd, 95 * 2 ** 30), null, "a 96 GB card");
  assert.equal(bigPlateWarning(hd, 24 * 2 ** 30), null, "1920 wide is not above 2K");
  assert.equal(bigPlateWarning(dci, 24 * 2 ** 30), null, "2048 is 2K itself");
  assert.equal(bigPlateWarning(uhd, 0), null, "the card's memory not yet known: no warning");
  assert.match(bigPlateWarning({ width: 2160, height: 3840 }, 39.6 * 2 ** 30), /40 GB/, "a portrait 4K plate on a 40 GB card");
});

import { STEP_FLOWS, resultFlows } from "../../web/logic.mjs";

test("a render's record of its workflows (r.flows) names the models behind the result", () => {
  const ran = (...ids) => [...new Set(ids.flatMap((id) => STEP_FLOWS[id]))];
  assert.deepEqual(ran("erase", "clean", "comp", "cleanfull", "review"), ["matte", "clean", "comp", "cleanup", "review"]);
  assert.deepEqual(resultFlows({ tools: ["paint"], render: ran("shot", "track", "comp", "full", "trackfull", "review") }).sort(),
    ["comp", "edit", "matte", "prompt", "review", "shot"]);
  assert.ok(resultFlows({ tools: ["erase"], render: [] }).includes("snap"), "an erase: SAM's object search");
  assert.deepEqual(resultFlows({ fluid: true, fluidHdr: true }).sort(), ["fluid", "hdr"], "a fluid shot alone, through SDR to HDR");
  assert.ok(!resultFlows({ tools: ["paint"], render: ran("shot", "full", "review") }).includes("hdr"), "no SDR to HDR step ran: none listed");
  for (const id of Object.keys(STEP_FLOWS)) assert.ok(STEP_FLOWS[id].length > 0, id);
});

import { wantsHdrFor } from "../../web/logic.mjs";

test("SDR to HDR: on its own for a plate that holds values above 1.0, else only from Deliver's bit-depth pass", () => {
  const exr = { kind: "sequence", ext: ".exr", pix_fmt: "gbrpf16le" }, mp4 = { kind: "video", ext: ".mp4", pix_fmt: "yuv420p" };
  assert.equal(wantsHdrFor(exr, 1, false), true, "an EXR plate: on its own, no switch");
  assert.equal(wantsHdrFor(mp4, 100, false), true, "an HDR video (PQ): on its own");
  assert.equal(wantsHdrFor(mp4, 1, false), false, "an SDR video: off");
  assert.equal(wantsHdrFor(mp4, 1, true), true, "an SDR video with Deliver's bit-depth pass on");
});

// ---------- The viewer, round 1: a stop keeps the strokes ----------
import * as viewerRules from "../../web/logic.mjs";

test("Esc drops the strokes in progress first, then stops the edit being generated, which keeps its strokes", () => {
  const esc = viewerRules.escapeAction;
  assert.equal(esc({ running: true, editing: false, selected: true, generating: true }), "reopen");
  assert.equal(esc({ running: true, editing: true, selected: true, generating: true }), "discard"); // a new draft beside it goes first
  assert.equal(esc({ opening: true, running: true, editing: true, generating: true }), "cancelOpen");
  assert.equal(esc({ editing: false, selected: true, generating: true }), "deselect");
  assert.equal(esc({ editing: false, selected: false, generating: true }), "stop");
});

test("strokes replay in the order they were made; SAM's object comes last, cut by every rub", () => {
  const a = { tool: "paint" }, r = { tool: "rub" }, b = { tool: "paint" }, r2 = { tool: "rub" };
  assert.deepEqual(viewerRules.replayOrder([a, r, b]), [{ stroke: a }, { stroke: r }, { stroke: b }]); // b, painted over the rubbed place, stays
  assert.deepEqual(viewerRules.replayOrder([a, r, b, r2], true), [{ stroke: a }, { stroke: r }, { stroke: b }, { stroke: r2 }, { sam: true, cuts: [r, r2] }]);
  assert.deepEqual(viewerRules.replayOrder([], true), [{ sam: true, cuts: [] }]);
});

// ---------- The pipeline, round 1: the paint matte's report, the memory profile ----------
import { matteLargest } from "../../web/logic.mjs";

test("the paint matte's report: its largest size against the object, the frame, and a warning above 3 times", () => {
  assert.deepEqual(matteLargest("SAM 3.1 found the object on 121 of 121 frames; the largest matte is 1.2 times the object, on frame 31"), { ratio: 1.2, frame: 31, warn: false });
  assert.deepEqual(matteLargest("SAM 3.1 returned no mask: the first-frame mask holds on every frame; the largest matte is 60.0 times the object, on frame 0 (warning: above 3, check the composite on that frame)"), { ratio: 60, frame: 0, warn: true });
  assert.equal(matteLargest("SAM 3.1 found the object on 6 of 12 frames"), null, "a summary without the report");
  assert.equal(matteLargest(undefined), null);
});

import { readFileSync as readFlow } from "node:fs";
import { MEMORY, memoryProfile, fillWorkflow as fillFor, parseWorkflow as parseFor } from "../../web/logic.mjs";

test("the memory profile: small under 24 GB, medium from 24 GB, large from 60 GB, or the one asked for", () => {
  const gib = 2 ** 30;
  assert.equal(memoryProfile({ vram: 16 * gib, ram: 64 * gib }).name, "small", "the reference laptop, an RTX 4090 Laptop with 16 GB");
  assert.equal(memoryProfile({ vram: 23.99 * gib }).name, "medium", "a 24 GB card reports about 25.7e9 bytes");
  assert.equal(memoryProfile({ vram: 20e9 }).name, "small");
  assert.equal(memoryProfile({ vram: 32 * gib }).name, "medium");
  assert.equal(memoryProfile({ vram: 96 * gib }).name, "large");
  assert.equal(memoryProfile({}).name, "small", "no VRAM size: nothing loads early");
  assert.deepEqual(memoryProfile({ vram: 16 * gib }).warm, [], "small: no model loads before an action needs it");
  assert.deepEqual(memoryProfile({ vram: 16 * gib }).slots, { tile: 256, guide_tiled: true });
  assert.match(memoryProfile({ vram: 16 * gib, ram: 64 * gib }).why, /16 GB of VRAM, 64 GB of RAM/);
  assert.match(memoryProfile({ vram: 16 * gib }).does, /^Models load one at a time and LTX works in 256 px tiles, so each step takes longer/, "what a small card cannot do as fast is said in one sentence, in the profile's own line");
  assert.equal(memoryProfile({ vram: 17.2e9, ram: 65.5e9 }).why, "16 GB of VRAM, 61 GB of RAM", "bytes / 2**30, rounded: a 16 GB card reads 16 GB");
  assert.equal(memoryProfile({ vram: 32e9 }).why, "30 GB of VRAM", "no RAM size from ComfyUI: none is written");
  assert.deepEqual(memoryProfile({ vram: 32 * gib }).warm, ["edit", "prompt"]);
  assert.deepEqual(memoryProfile({ vram: 96 * gib }).warm, ["edit", "prompt", "warm"]);
  const forced = memoryProfile({ vram: 96 * gib, ram: 256 * gib, force: "small" });
  assert.equal(forced.name, "small");
  assert.match(forced.why, /asked for; with 96 GB of VRAM, 256 GB of RAM, the page would choose large/);
  assert.equal(memoryProfile({ vram: 96 * gib, force: "huge" }).name, "large", "an unknown name is not a profile");
  assert.equal(memoryProfile({ vram: 96 * gib, force: "toString" }).name, "large");
});

test("a memory profile changes slot values only: one set of workflows, tiles of 256 px and a tiled guide on a small card", () => {
  const flow = (name) => parseFor(JSON.parse(readFlow(new URL(`../../web/workflows/${name}.json`, import.meta.url), "utf8")));
  const nodes = (wf, cls) => Object.values(wf.prompt).filter((n) => n.class_type === cls);
  for (const name of ["clean", "cleanup", "shot", "fluid", "hdr"]) {
    const large = fillFor(flow(name), { ...MEMORY.large.slots }), small = fillFor(flow(name), { ...MEMORY.small.slots });
    assert.deepEqual(Object.keys(small.prompt), Object.keys(large.prompt), `${name}: the same nodes on every card`);
    for (const n of nodes(large, "VAEDecodeTiled")) assert.equal(n.inputs.tile_size, 512, name);
    for (const n of nodes(small, "VAEDecodeTiled")) assert.equal(n.inputs.tile_size, 256, name);
    for (const n of nodes(large, "LTXAddVideoICLoRAGuide")) assert.equal(n.inputs.use_tiled_encode, false, name);
    for (const n of nodes(small, "LTXAddVideoICLoRAGuide")) assert.equal(n.inputs.use_tiled_encode, true, name);
    assert.ok(nodes(small, "VAEDecodeTiled").length + nodes(small, "LTXAddVideoICLoRAGuide").length > 0, `${name} has a slot of the profile`);
  }
  for (const n of nodes(fillFor(flow("cleanup"), { ...MEMORY.small.slots }), "VAEEncodeTiled")) assert.equal(n.inputs.tile_size, 256);
});

// ---------- Viewer, round 1, second pass: edits are layers, and a stop stops everything ----------
import { editList, hiddenAbove, layersHint, stopHint } from "../../web/logic.mjs";

test("hiddenAbove: while an edit of History is changed, the made edits above it are hidden", () => {
  const made = { on: true, made: true }, off = { on: false, made: true }, fresh = { on: true, made: false };
  assert.deepEqual(hiddenAbove([made, made, made, made], 1), [2, 3]);
  assert.deepEqual(hiddenAbove([made, made, off, fresh, made], 1), [4]); // a bypassed edit and an edit without a result have nothing to hide
  assert.deepEqual(hiddenAbove([made, made, made], 2), []); // the edit on top hides nothing
  assert.deepEqual(hiddenAbove([made, made], -1), []); // a new edit, or none: every edit shows
  assert.deepEqual(hiddenAbove([made, off, made], 1), []); // a bypassed edit being changed hides nothing
});

test("layersHint and stopHint: the status line names the edits hidden, stopped and waiting", () => {
  assert.equal(editList([3]), "edit 3");
  assert.equal(editList([3, 4]), "edits 3 and 4");
  assert.equal(editList([3, 4, 5]), "edits 3, 4 and 5");
  assert.equal(layersHint(2, [3, 4]), "Edit 2 is being changed: edits 3 and 4 are hidden until it is generated.");
  assert.equal(layersHint(2, [3]), "Edit 2 is being changed: edit 3 is hidden until it is generated.");
  assert.equal(layersHint(2, []), "");
  assert.equal(stopHint({ edit: 2, waits: [3] }), "Stopped. Edit 2 keeps its strokes, words and seed. Edit 3 waits. Enter generates again, Ctrl+Enter tries another seed, Esc drops the strokes.");
  assert.equal(stopHint({ waits: [3, 4] }), "Stopped. Edits 3 and 4 wait. Enter goes on from where it stopped.");
  assert.equal(stopHint(), "Stopped. Enter goes on from where it stopped.");
});

// ---------- Viewer, round 1, second pass, turn 2: after Generate, an edit above waits for its own pass ----------
import { awaitingPass } from "../../web/logic.mjs";

test("awaitingPass: an edit above an edit made again waits for its own pass when it depends on it", () => {
  const foot = (...cells) => ({ w: 4, h: 1, bits: Uint8Array.from([0, 1, 2, 3].map((i) => (cells.includes(i) ? 1 : 0))) });
  const edit = (id, cells, more = {}) => ({ id, version: 1, tool: "paint", foot: foot(...cells), on: true, made: true, pending: false, basis: [], ...more });
  const a = edit(1, [0, 1]), b = edit(2, [1, 2], { basis: [a] }), c = edit(3, [3], { basis: [a, b] }), d = edit(4, [2], { basis: [a, b, c] });
  assert.deepEqual(awaitingPass([a, b, c, d]), []); // nothing is made again: every edit shows
  assert.deepEqual(awaitingPass([{ ...a, pending: true }, b, c]), [1]); // b overlaps a; c is far from both, so it stays
  assert.deepEqual(awaitingPass([{ ...a, pending: true }, b, c, d]), [1, 3]); // d overlaps b, which waits: it waits too
  assert.deepEqual(awaitingPass([{ ...a, version: 2 }, b, c]), [1]); // a has its new result: b waits until its own pass ends
  const light = edit(5, [3], { tool: "light", basis: [a, b, c, d] });
  assert.deepEqual(awaitingPass([a, b, { ...c, pending: true }, d, light]), [4]); // a light depends on every edit under it
});

// ---------- The orchestrator, 11 Nov: one family of models in memory at a time on the small profile ----------
test("every workflow has a family, and the small profile frees ComfyUI's memory when the family changes", async () => {
  const { FAMILY, freesBefore, memoryProfile } = await import("../../web/logic.mjs");
  const { readdirSync } = await import("node:fs");
  const names = readdirSync(new URL("../../web/workflows/", import.meta.url)).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5));
  assert.deepEqual(names.filter((n) => !FAMILY[n]), []);
  const small = memoryProfile({ vram: 17.2e9 }), large = memoryProfile({ vram: 100e9 });
  assert.equal(freesBefore(small, "shot", "matte"), true); // LTX and its text encoder leave before SAM tracks the paint
  assert.equal(freesBefore(small, "ingest", "prompt"), true); // the open's frames leave before the edit models load
  assert.equal(freesBefore(small, "prompt", "edit"), false); // the same family
  assert.equal(freesBefore(small, "clean", "cleanup"), false);
  assert.equal(freesBefore(small, null, "ingest"), false); // the first job: nothing to free
  assert.equal(freesBefore(large, "shot", "matte"), false);
});

test("a ComfyUI that stopped is said in plain words, with what to do", async () => {
  const { plainError } = await import("../../web/logic.mjs");
  assert.equal(plainError("ComfyUI stopped answering"), "ComfyUI stopped answering. Its terminal says why: most often the machine ran out of memory. Start ComfyUI again.");
  assert.equal(plainError("Upload failed: patch.png: No answer from ComfyUI"), "ComfyUI did not answer: it may be restarting, or the connection dropped.");
  assert.equal(plainError("Upload failed: patch.png"), "the browser could not send a picture to ComfyUI."); // ComfyUI answered, and refused the file
});

test("a larger card keeps its models, and frees ComfyUI's memory only when RAM is short for the job's frames", async () => {
  const { freesBefore, framesNeed, memoryProfile } = await import("../../web/logic.mjs");
  const large = memoryProfile({ vram: 100e9 }), need = framesNeed(1920, 1080, 121);
  assert.equal(Math.round(need / 2 ** 30), 26); // 8 copies of 2.8 GB, and 4 GB to work in
  assert.equal(freesBefore(large, "shot", "matte", { free: 120 * 2 ** 30, need }), false); // speed first
  assert.equal(freesBefore(large, "shot", "matte", { free: 10 * 2 ** 30, need }), true);
  assert.equal(freesBefore(large, "shot", "shot", { free: 1, need }), false); // the same family: its models are the job's
  assert.equal(freesBefore(memoryProfile({ vram: 17.2e9 }), "shot", "matte", { free: 120 * 2 ** 30, need }), true); // under 24 GB: always
});

test("the open counts 3 copies of the plate, and every other job 8", async () => {
  const { framesNeed, freesBefore, memoryProfile } = await import("../../web/logic.mjs");
  // 1.11.9 on 12 Nov: the open of horse.mp4 holds 2.8 copies of the plate at its peak on the laptop (9.1 GB), 1.9 on a pod
  const open = framesNeed(1920, 1080, 121, "ingest"), other = framesNeed(1920, 1080, 121, "review");
  assert.equal(Math.round(open / 2 ** 30), 12); // 3 copies of 2.8 GB, and 4 GB to work in
  assert.equal(other, framesNeed(1920, 1080, 121)); // 8 copies, as for a job without a name
  const large = memoryProfile({ vram: 100e9 }), free = 20 * 2 ** 30;
  assert.equal(freesBefore(large, "shot", "ingest", { free, need: open }), false); // 20 GB free: the open has room, nothing is freed
  assert.equal(freesBefore(large, "shot", "review", { free, need: other }), true);
});

test("the time left in a step follows the sampler's own pace, not the time the models took to load", async () => {
  const { stepLeft, remember, slower, timeKey } = await import("../../web/logic.mjs");
  // the laptop's preview shot of 11 Nov: 57.6 s in all, the sampler's first step of 8 ended 37 s in, then one step every 2 s
  assert.equal(stepLeft({ est: 42, run: 20 }), 22); // before the sampler starts: what is expected, less what has run
  assert.equal(stepLeft({ est: 42, run: 37, first: [37, 0.125], last: [37, 0.125] }), 5); // one step: no pace yet (the old rule said 259 s)
  const mid = stepLeft({ est: 42, run: 43, first: [37, 0.125], last: [43, 0.5], tail: 6 }); // 4 steps to go at 2 s, then the tail
  assert.ok(Math.abs(mid - 14) < 0.01, String(mid));
  assert.equal(stepLeft({ est: 42, run: 53, first: [37, 0.125], last: [51, 1], tail: 6 }), 4); // the sampling over: what is left of the tail
  assert.equal(stepLeft({ est: 42, run: 80, first: [37, 0.125], last: [51, 1], tail: 6 }), 1); // never less than a second
  assert.equal(stepLeft({ est: 42, run: 60 }), 4.2); // a step with no progress, past its estimate: a tenth of it
  assert.equal(slower("small", "full"), 2.98); // render_estimates.test.mjs holds the laptop's steps
  assert.equal(slower("large", "full"), 1);
  const key = timeKey("shot", [640, 352], 121, "small");
  assert.equal(key, "shot|640x352x121|small");
  let times = remember({}, key, { total: 57.6, lead: 37, tail: 6, at: 1 });
  times = remember(times, key, { total: 20, lead: 4, tail: 5, at: 2 }); // a second render, the models warm
  assert.deepEqual(times[key], { total: 38.8, lead: 20.5, tail: 5.5, at: 2 });
  for (let i = 0; i < 100; i++) times = remember(times, `k${i}`, { total: 1, lead: 1, tail: 0, at: 3 + i });
  assert.equal(Object.keys(times).length, 80); // the newest are kept
  assert.equal(times[key], undefined);
});

// ---------- The render workstream, wave 4 [cross]: a seed asked for in the address ----------
import { askedSeed } from "../../web/logic.mjs";

test("a seed asked for in the address is a whole number under 2^31, and anything else is not a seed", () => {
  assert.equal(askedSeed("1017942128"), 1017942128); // the laptop's erase of 12 Nov that left its object: the page had drawn this seed
  assert.equal(askedSeed("0"), 0);
  assert.equal(askedSeed("2147483647"), 2 ** 31 - 1); // the largest seed the page draws: (Math.random() * 2 ** 31) | 0
  for (const text of [null, "", "abc", "-1", "1.5", "1e3", " 7", "7 ", "2147483648", "99999999999"]) assert.equal(askedSeed(text), null, String(text));
});

// ---------- The render workstream, wave 4 [cross]: no job index when the address says ?index=0 ----------
import { plateIdentity } from "../../web/logic.mjs";
import { indexParts } from "../../web/comfy.mjs";

test("the plate's identity is its path, files, size and time, and there is none when the job index is off", () => {
  const st = { files: 1, size: 6898529, mtime: 1794517860.5 };
  assert.equal(plateIdentity("plates/horse.mp4", st), '["plates/horse.mp4",1,6898529,1794517860.5]');
  assert.equal(plateIdentity("plates/horse.mp4", null), null); // the plate could not be checked
  assert.equal(plateIdentity("plates/horse.mp4", st, false), null); // ?index=0
  assert.notEqual(indexParts("1.11.11", "a1b2", plateIdentity("plates/horse.mp4", st), { seed: 1017942128 }), null);
  assert.equal(indexParts("1.11.11", "a1b2", plateIdentity("plates/horse.mp4", st, false), { seed: 1017942128 }), null, "no key: the job is posted, and the index keeps nothing of it");
});

import { erasedShare, eraseLeft, leftHint } from "../../web/logic.mjs";

test("an erase that left its object: the share of the object that changed on the first frame, and what to do next", () => {
  const w = 16, h = 8;
  const rgba = (f) => { const d = new Uint8ClampedArray(w * h * 4); for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) d.set([...f(x, y), 255], (y * w + x) * 4); return d; };
  const mist = rgba(() => [150, 150, 150]);
  const before = rgba((x) => (x >= 4 && x < 12 ? [60, 40, 30] : [150, 150, 150])); // a dark barn, 8 pixels wide, in the mist
  const mask = rgba((x) => (x >= 2 && x < 14 ? [255, 255, 255] : [0, 0, 0])); // its mask, 2 pixels wider on each side
  assert.equal(erasedShare(before, before, mask, w, h), 0); // Klein answered with the frame as it was (12 Nov 2026)
  assert.equal(eraseLeft(0), true);
  // the same barn, softened (10 levels up and down from pixel to pixel) and 6 levels off, as Klein's fill can sit: unchanged
  const soft = rgba((x, y) => (x >= 4 && x < 12 ? [66 + ((x + y) % 2) * 20 - 10, 46, 36] : [156, 156, 156]));
  assert.equal(erasedShare(soft, before, mask, w, h), 0);
  assert.equal(erasedShare(mist, before, mask, w, h), 8 / 12); // the barn gone: its 8 columns of the mask's 12 changed
  assert.equal(eraseLeft(8 / 12), false);
  // a wire 1 pixel wide under a stroke 12 pixels wide: the cell that held it moves by 40 levels, a third of the mask
  const wire = rgba((x) => (x === 5 ? [40, 40, 40] : [200, 200, 200]));
  assert.equal(erasedShare(rgba(() => [200, 200, 200]), wire, mask, w, h), 4 / 12);
  assert.equal(erasedShare(mist, before, rgba(() => [0, 0, 0]), w, h), null); // no mask: nothing to judge, nothing is held back
  assert.equal(eraseLeft(null), false);
  assert.deepEqual([eraseLeft(0.019), eraseLeft(0.02)], [true, false]); // less than 2% of the object changed: it is still there
  assert.equal(leftHint(""), "Type its name in the prompt bar, then Generate.");
  assert.equal(leftHint("barn"), "Describe it with other words, then Generate, or press Ctrl+Enter for another seed.");
});
