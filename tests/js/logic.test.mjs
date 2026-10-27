// The page's pure rules (web/logic.mjs), run by `node --test tests/js` (tests/test_web.py runs it too).
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { caption, dependsOnChange, fillWorkflow, fitSize, frameUse, gb, parseWorkflow, secs } from "../../web/logic.mjs";

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
  const shot = workflow("shot");
  const bare = fillWorkflow(shot, { path: "plate.mp4" });
  assert.equal(classes(bare).filter((c) => c === "PaintAPlate_LoadPlate").length, 1); // no erase matte loader
  const fill = Object.values(bare.prompt).find((n) => n.class_type === "PaintAPlate_FillMatte");
  assert.equal(fill.inputs.mask, undefined); // frames pass through untouched
  assert.equal(classes(fillWorkflow(shot, { path: "plate.mp4", hole: "output:m" })).filter((c) => c === "PaintAPlate_LoadPlate").length, 2);
  const relight = fillWorkflow(workflow("export"), { path: "plate.exr", shot: "output:s", relight: true });
  assert.equal(Object.values(relight.prompt).some((n) => n._meta?.output === "matte"), false); // no matte to save
  assert.equal(shot.prompt[shot.slots.path[0][0]].inputs.path, ""); // filling copies: the parsed workflow stays as saved
});

test("every workflow names the outputs and the progress node the page reads", () => {
  const wanted = { ingest: ["hero", "proxy", "spec"], prompt: ["text"], edit: ["patch", "relit", "result"],
    snap: ["named", "point_0", "point_1", "point_2", "point_3", "point_4"], clean: ["frames", "video"], shot: ["frames", "video"],
    matte: ["frames"], comp: ["video"], export: ["export", "matte", "review"], warm: ["frame"] };
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
