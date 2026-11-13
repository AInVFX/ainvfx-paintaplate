// The edit workstream's tests of the box the prompt writer gets for an erase with no words (web/logic.mjs: coreBox,
// writerBoxes), with the laptop's answers of 12 and 13 November 2026 for a stroke on the barn of horse.mp4.
import { test } from "node:test";
import assert from "node:assert/strict";
import { coreBox, writerBoxes, erasesPaint, reconcile, upsampleRequest } from "../../web/logic.mjs";

const w = 40, h = 20;
const rect = (x0, y0, x1, y1) => {
  const m = new Uint8Array(w * h);
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) m[y * w + x] = 1;
  return m;
};
const or = (...ms) => ms.reduce((a, m) => a.map((v, i) => v | m[i]));

test("the core box holds the stroke and what most of SAM's masks agree on, with no margin", () => {
  const barn = rect(20, 6, 40, 12), nose = rect(14, 9, 20, 12), painted = rect(26, 8, 38, 9);
  // two of five masks take in the horse's nose, as on 12 Nov 2026: it stays out
  assert.deepEqual(coreBox({ painted, masks: [or(barn, nose), or(barn, nose), barn, barn, barn], w, h }), [300, 500, 600, 1000]);
  // two of three masks hold it: most of them, so it stays in
  assert.deepEqual(coreBox({ painted, masks: [or(barn, nose), or(barn, nose), barn], w, h }), [300, 350, 600, 1000]);
  assert.deepEqual(coreBox({ painted, masks: [], w, h }), [400, 650, 450, 950]); // no mask: the stroke alone
  assert.equal(coreBox({ painted: new Uint8Array(w * h), masks: [], w, h }), null);
});

test("an erase with no words, painted in one part, gets its core box; otherwise one box per painted part", () => {
  const core = [368, 732, 479, 1000], parts = [[362, 721, 490, 1000]], bbox = [366, 730, 483, 1000];
  assert.deepEqual(writerBoxes({ tool: "erase", words: "", parts, core, bbox }), { bbox: core, boxes: [core] });
  assert.deepEqual(writerBoxes({ tool: "erase", words: "  ", parts, core, bbox }), { bbox: core, boxes: [core] });
  assert.deepEqual(writerBoxes({ tool: "erase", words: "the barn", parts, core, bbox }), { bbox, boxes: parts });
  const two = [[1, 2, 300, 400], [500, 600, 700, 800]]; // a truss and a crane: one box each, as on 28 Oct
  assert.deepEqual(writerBoxes({ tool: "erase", words: "", parts: two, core, bbox }), { bbox, boxes: two });
  assert.deepEqual(writerBoxes({ tool: "erase", words: "", parts, core: null, bbox }), { bbox, boxes: parts });
  assert.deepEqual(writerBoxes({ tool: "paint", words: "", parts: null, core, bbox }), { bbox, boxes: null });
});

test("the core box's answer of 13 Nov is kept; the answer of 12 Nov to the box around SAM's whole union is refused", () => {
  const W = 96, H = 54, bits = new Uint8Array(W * H); // the paint on the page's grid: the barn, x 0.73 to 1, y 0.37 to 0.49
  for (let y = 20; y <= 26; y++) for (let x = 70; x <= 95; x++) bits[y * W + x] = 1;
  const paint = { bits, w: W, h: H };
  const tight = upsampleRequest({ tool: "erase", words: "", ...writerBoxes({ tool: "erase", words: "", parts: [[362, 721, 490, 1000]],
    core: [368, 732, 479, 1000], bbox: [366, 730, 483, 1000] }) });
  assert.deepEqual(tight.locked.map((r) => r.src_bbox), [[368, 732, 479, 1000]]);
  const barn = "Remove the distant barn <barn_1> in the upper-right background completely, including its roof, walls, and any " +
    "associated shadow or reflection. Keep the horse, fence, vegetation, and every other region exactly unchanged. " +
    '[{"id": "barn_1", "from": "ref_image_0", "src_bbox": [368, 803, 479, 1000], "tgt_bbox": null, "desc": "A distant dark farm barn"}]';
  assert.equal(erasesPaint(reconcile(barn, tight.locked), tight.locked, paint), true);
  const wide = upsampleRequest({ tool: "erase", words: "", bbox: [366, 730, 483, 1000], boxes: [[362, 721, 490, 1000]] });
  const horse = "Remove the horse <horse_1> completely, including its bridle, tack, cast shadow, and reconstruct the unobstructed " +
    'background <background_1>. [{"id": "horse_1", "from": "ref_image_0", "src_bbox": [226, 280, 958, 716], "tgt_bbox": null, ' +
    '"desc": "a bay horse"}, {"id": "background_1", "from": "target", "src_bbox": null, "tgt_bbox": [300, 280, 958, 1000], "desc": "the meadow"}]';
  assert.equal(erasesPaint(reconcile(horse, wide.locked), wide.locked, paint), false);
});
