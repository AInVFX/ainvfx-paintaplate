// The edit workstream's tests of the prompt writer's box once the writer names another object than the one under an erase
// stroke with no words (web/logic.mjs: removedNames, boxWithout, corePixels, boxOf): SAM 3.1 finds that object by the
// writer's name for it, and the box leaves it out.
import { test } from "node:test";
import assert from "node:assert/strict";
import { join } from "node:path";
import { boxOf, boxWithout, coreBox, corePixels, erasesPaint, reconcile, removedNames } from "../../web/logic.mjs";
import { png } from "./edit_png.mjs";

const rect = (w, h, x0, y0, x1, y1) => {
  const m = new Uint8Array(w * h);
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) m[y * w + x] = 1;
  return m;
};
const or = (...ms) => ms.reduce((a, m) => a.map((v, i) => v | m[i]));
const inside = (m, box, w, h) => { // the pixels of `m` in `box`, and the box's own pixels
  const [y0, x0, y1, x1] = [box[0] * h, box[1] * w, box[2] * h, box[3] * w].map((v) => Math.round(v / 1000));
  let n = 0;
  for (let y = y0; y < y1; y++) for (let x = x0; x < x1; x++) n += m[y * w + x];
  return [n, (y1 - y0) * (x1 - x0)];
};

// The answer of Klein's prompt writer for a stroke on the tree of horse.mp4, with no words: it removes the barn below it.
const locked = [{ id: "obj_1", from: "ref_image_0", src_bbox: [218, 759, 431, 902], tgt_bbox: null, desc: "the object to remove" }];
const BARN = "Remove the distant barn <barn_1> in the upper-right background completely, including its roof, walls, and any " +
  "shadow or reflection it casts. Keep the horse, fence, vegetation, and every other region exactly unchanged. " +
  '[{"id": "barn_1", "from": "ref_image_0", "src_bbox": [365, 800, 431, 999], "tgt_bbox": null, "desc": "A distant ' +
  'rectangular farm barn with dark muted walls and a broad pale blue-gray corrugated metal roof."}]';

test("the objects an answer removes, apart from the locked ones, by the names SAM 3.1 reads", () => {
  const made = reconcile(BARN, locked), w = 96, h = 54, bits = new Uint8Array(w * h);
  for (let y = 12; y <= 22; y++) for (let x = 74; x <= 86; x++) bits[y * w + x] = 1; // the stroke on the tree
  assert.equal(erasesPaint(made, locked, { bits, w, h }), false); // refused: the barn holds none of the paint
  assert.deepEqual(removedNames(made, locked), ["barn"]);
  const two = 'Remove the old_car <old_car_2> and the sign <sign_1>. [{"id": "old_car_2", "from": "ref_image_0", "src_bbox": ' +
    '[1, 2, 300, 400], "tgt_bbox": null, "desc": "a car"}, {"id": "sign_1", "from": "ref_image_0", "src_bbox": [5, 6, 70, 80], ' +
    '"tgt_bbox": null, "desc": "a sign"}, {"id": "sky_1", "from": "ref_image_0", "src_bbox": [0, 0, 300, 1000], ' +
    '"tgt_bbox": [0, 0, 300, 1000], "desc": "the sky"}]';
  assert.deepEqual(removedNames(two), ["old car", "sign"]); // a row kept in the result (a target box) is not removed
  assert.deepEqual(removedNames(reconcile("Remove the object <obj_1>.", locked), locked), []); // the locked object itself
  assert.deepEqual(removedNames(""), []);
});

test("the object's core and its box: coreBox is the box of corePixels", () => {
  const w = 40, h = 20, barn = rect(w, h, 20, 6, 40, 12), nose = rect(w, h, 14, 9, 20, 12), painted = rect(w, h, 26, 8, 38, 9);
  const masks = [or(barn, nose), or(barn, nose), barn, barn, barn];
  assert.deepEqual(boxOf(corePixels({ painted, masks, w, h }), w, h), coreBox({ painted, masks, w, h }));
  assert.deepEqual(boxOf(corePixels({ painted, masks, w, h }), w, h), [300, 500, 600, 1000]);
  assert.equal(boxOf(new Uint8Array(w * h), w, h), null);
});

test("the box leaves out the other object and keeps the most of the object", () => {
  const w = 40, h = 20, tree = or(rect(w, h, 10, 2, 26, 12), rect(w, h, 16, 12, 20, 16)); // branches, then a trunk
  const barn = rect(w, h, 4, 13, 40, 18), core = corePixels({ painted: new Uint8Array(w * h), masks: [tree], w, h });
  const box = boxOf(core, w, h);
  assert.deepEqual(box, [100, 250, 800, 650]); // it holds the barn's roof on both sides of the trunk
  assert.deepEqual(boxWithout({ box, keep: core, other: barn, w, h }), [100, 250, 650, 650]); // above the roof
  assert.equal(boxWithout({ box, keep: core, other: rect(w, h, 30, 0, 40, 20), w, h }), null); // already outside the box
  const three = or(rect(w, h, 0, 0, 8, 20), rect(w, h, 16, 0, 24, 20), rect(w, h, 32, 0, 40, 20)); // no box without the
  const between = or(rect(w, h, 8, 0, 16, 20), rect(w, h, 24, 0, 32, 20)); // other holds half of the object
  assert.equal(boxWithout({ box: [0, 0, 1000, 1000], keep: three, other: between, w, h }), null);
});

test("real masks: the tree's box leaves out the barn's roof", { skip: !process.env.PAINTAPLATE_FIXTURES && "PAINTAPLATE_FIXTURES is not set" }, () => {
  // SAM 3.1's masks of horse.mp4's first frame at 768 x 432: the tree under a stroke with no words, and the barn by its name
  const dir = join(process.env.PAINTAPLATE_FIXTURES, "edit_check");
  const bits = (name) => { const { w, h, data } = png(join(dir, `${name}.png`)), m = new Uint8Array(w * h); for (let i = 0; i < w * h; i++) m[i] = data[i * 4] > 127 ? 1 : 0; return m; };
  const w = 768, h = 432, tree = bits("probe14_tree_mask"), barn = bits("probe14_barn_mask");
  const core = corePixels({ painted: new Uint8Array(w * h), masks: [tree], w, h }), box = boxOf(core, w, h);
  assert.deepEqual(box, [218, 759, 431, 902]); // the box the writer got, which holds the barn's roof
  const [roof, area] = inside(barn, box, w, h);
  assert.ok(roof > 0.15 * area, `${roof} of ${area}`);
  const cut = boxWithout({ box, keep: core, other: barn, w, h });
  const [left, cutArea] = inside(barn, cut, w, h), [kept] = inside(tree, cut, w, h), [all] = inside(tree, box, w, h);
  assert.ok(left <= 0.02 * cutArea && kept >= 0.5 * all, `${JSON.stringify(cut)}: ${left} of ${cutArea} barn, ${kept} of ${all} tree`);
  assert.deepEqual(cut, [218, 759, 377, 902]); // the rows above the roof: 1% barn, 87% of the tree
});
