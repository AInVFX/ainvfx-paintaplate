// The edit workstream's tests of the check after an erase (web/logic.mjs: eraseCheck, objectLeft): a removed object
// passes; an object that stayed, or that Klein only recoloured as it did the barn on 12 November 2026, is left.
import { test } from "node:test";
import assert from "node:assert/strict";
import { eraseCheck, objectLeft } from "../../web/logic.mjs";

const w = 64, h = 32;
const frame = (fn) => {
  const a = new Uint8ClampedArray(w * h * 4);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) a.set([...fn(x, y), 255], (y * w + x) * 4);
  return a;
};
const inside = (x, y) => x >= 16 && x < 48 && y >= 8 && y < 24;
const sky = (x, y) => [150 + y, 140 + y, 130 + y];
const barn = (x, y) => (inside(x, y) ? ((x >> 2) % 2 ? [60, 70, 90] : [170, 180, 200]) : sky(x, y)); // planks on a sky
const mask = frame((x, y) => (inside(x, y) ? [255, 255, 255] : [0, 0, 0]));
const before = frame(barn);

test("an object that went passes; one that stayed, or that was only recoloured, is left", () => {
  const gone = eraseCheck(frame(sky), before, mask, w, h);
  assert.equal(gone.left, false, JSON.stringify(gone));
  assert.equal(eraseCheck(before, before, mask, w, h).left, true);
  // recoloured: every value 40 levels up, its planks in place. The rule of 12 Nov (2% at 12 levels) let it through
  const recoloured = eraseCheck(frame((x, y) => barn(x, y).map((v) => v + 40)), before, mask, w, h);
  assert.ok(recoloured.changed > 0.9 && recoloured.edges > 0.85, JSON.stringify(recoloured));
  assert.equal(recoloured.left, true);
  assert.deepEqual(eraseCheck(before, before, frame(() => [0, 0, 0]), w, h), { changed: null, edges: null, left: false }); // no mask
});

test("the probe's results on horse.mp4 (13 Nov 2026): what went passes; what stayed, and the half-changed tree, are left", () => {
  // [share of the object moved by more than 24 levels, correlation of its edges before and after]
  const went = [[0.53, 0.75], [0.78, 0.71], [0.77, -0.03], [0.58, 0.74], [0.74, 0.03], [0.73, 0.03], [0.74, 0.03]];
  const stayed = [[0, 0.98], [0.01, 0.98], [0, 0.93], [0, 0.97], [0.17, 0.62]];
  for (const [changed, edges] of went) assert.equal(objectLeft({ changed, edges }), false, `${changed}, ${edges}`);
  for (const [changed, edges] of stayed) assert.equal(objectLeft({ changed, edges }), true, `${changed}, ${edges}`);
});
