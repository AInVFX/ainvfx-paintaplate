// Tests of what Klein's prompt writer gets and gives for an erase stroke with no words (web/logic.mjs: corePixels, boxOf,
// coreBox, removedNames, dimOutside): the box cut to the object's core, the names of the objects that an answer removes,
// and the frame with all but the object dimmed that the writer gets for a second look.
import { test } from "node:test";
import assert from "node:assert/strict";
import { join } from "node:path";
import { boxOf, coreBox, corePixels, erasesPaint, reconcile, removedNames, DIM, dimOutside } from "../../web/logic.mjs";
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

test("real masks: the tree's box, cut to its core, holds the barn's roof", { skip: !process.env.PAINTAPLATE_FIXTURES && "PAINTAPLATE_FIXTURES is not set" }, () => {
  // SAM 3.1's masks of horse.mp4's first frame at 768 x 432: the tree under a stroke with no words, and the barn by its name
  const dir = join(process.env.PAINTAPLATE_FIXTURES, "edit_check");
  const bits = (name) => { const { w, h, data } = png(join(dir, `${name}.png`)), m = new Uint8Array(w * h); for (let i = 0; i < w * h; i++) m[i] = data[i * 4] > 127 ? 1 : 0; return m; };
  const w = 768, h = 432, tree = bits("probe14_tree_mask"), barn = bits("probe14_barn_mask");
  const core = corePixels({ painted: new Uint8Array(w * h), masks: [tree], w, h }), box = boxOf(core, w, h);
  assert.deepEqual(box, [218, 759, 431, 902]); // the box the writer gets
  const [roof, area] = inside(barn, box, w, h);
  assert.ok(roof > 0.15 * area, `${roof} of ${area}`);
  // the barn's roof inside the box: on the frame itself, the writer's answer can remove the barn (app.prepare looks again)
});

test("the dimmed frame: every pixel outside the object at 30% of its light, rounded down; the object and the alpha stay", () => {
  const rgba = Uint8ClampedArray.from([255, 128, 7, 255, 255, 128, 7, 128, 200, 101, 9, 255]), bits = Uint8Array.from([1, 0, 0]);
  assert.equal(DIM, 0.3);
  assert.deepEqual([...dimOutside(rgba, bits)], [255, 128, 7, 255, 76, 38, 2, 128, 60, 30, 2, 255]);
  assert.deepEqual([...rgba.slice(4, 8)], [255, 128, 7, 128]); // a new array: the frame itself stays
});

test("real frame: outside the barn's mask, about 30% of the light; inside, the frame itself", { skip: !process.env.PAINTAPLATE_FIXTURES && "PAINTAPLATE_FIXTURES is not set" }, () => {
  // horse.mp4's first frame at 768 x 432 and SAM 3.1's mask of its barn, as the writer's second look gets them
  const dir = join(process.env.PAINTAPLATE_FIXTURES, "edit_check"), f = png(join(dir, "probe14_frame.png")), m = png(join(dir, "probe14_barn_mask.png"));
  assert.deepEqual([m.w, m.h], [f.w, f.h]);
  const bits = new Uint8Array(f.w * f.h).map((_, i) => (m.data[i * 4] > 127 ? 1 : 0)), out = dimOutside(f.data, bits);
  let inSame = true, lit = 0, dim = 0, n = 0;
  for (let i = 0; i < bits.length; i++) for (let c = 0; c < 3; c++) {
    const j = i * 4 + c;
    if (bits[i]) inSame &&= out[j] === f.data[j]; else { lit += f.data[j]; dim += out[j]; n++; }
  }
  assert.ok(inSame && n > 0 && n < 3 * bits.length, "the barn's pixels stay as they are");
  assert.ok(dim / lit > 0.28 && dim / lit <= 0.3, `${(dim / lit).toFixed(4)} of the light outside the barn`);
});
