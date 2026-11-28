// Tests of the check after an erase (web/logic.mjs: eraseCheck, objectLeft): a removed object
// passes; an object that stayed, or that Klein only recoloured, is left.
import { test } from "node:test";
import assert from "node:assert/strict";
import { bandBeyond, BEYOND, eraseCheck, objectLeft } from "../../web/logic.mjs";

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
  // recoloured: every value 40 levels up, its planks in place. A rule of 2% at 12 levels lets it through
  const recoloured = eraseCheck(frame((x, y) => barn(x, y).map((v) => v + 40)), before, mask, w, h);
  assert.ok(recoloured.changed > 0.9 && recoloured.edges > 0.85, JSON.stringify(recoloured));
  assert.equal(recoloured.left, true);
  assert.deepEqual(eraseCheck(before, before, frame(() => [0, 0, 0]), w, h), { changed: null, edges: null, left: false }); // no mask
});

test("the probe's results on horse.mp4: what went passes; what stayed, and the half-changed tree, are left", () => {
  // [share of the object moved by more than 24 levels, correlation of its edges before and after]
  const went = [[0.53, 0.75], [0.78, 0.71], [0.77, -0.03], [0.58, 0.74], [0.74, 0.03], [0.73, 0.03], [0.74, 0.03]];
  const stayed = [[0, 0.98], [0.01, 0.98], [0, 0.93], [0, 0.97], [0.17, 0.62]];
  for (const [changed, edges] of went) assert.equal(objectLeft({ changed, edges }), false, `${changed}, ${edges}`);
  for (const [changed, edges] of stayed) assert.equal(objectLeft({ changed, edges }), true, `${changed}, ${edges}`);
});

test("the band beyond the object: the mask grown as a square by the reach, without the mask, never past the frame", () => {
  const w = 8, h = 6, mask = new Uint8ClampedArray(w * h * 4), on = [];
  mask.fill(255, 2 * w * 4, (2 * w + 1) * 4); // one pixel, at x 0 and y 2
  const band = bandBeyond(mask, w, h, 1);
  for (let i = 0; i < w * h; i++) if (band[i * 4] === 255) on.push([i % w, Math.floor(i / w)]);
  assert.deepEqual(on, [[0, 1], [1, 1], [1, 2], [0, 3], [1, 3]]);
});

test("an erase that changed the whole area around its object is held back; one that kept it passes", () => {
  const W = 40, H = 20, grey = (v) => new Uint8ClampedArray(W * H * 4).fill(v), mask = grey(0), inside = grey(100);
  for (let y = 5; y < 15; y++) for (let x = 15; x < 25; x++) { mask.fill(255, (y * W + x) * 4, (y * W + x) * 4 + 4); inside.fill(160, (y * W + x) * 4, (y * W + x) * 4 + 3); }
  const kept = eraseCheck(inside, grey(100), mask, W, H, 4), took = eraseCheck(grey(160), grey(100), mask, W, H, 4);
  assert.deepEqual([kept.why, kept.beyond, took.why, took.beyond], [null, 0, "beyond", 1]);
  assert.deepEqual(Object.keys(eraseCheck(inside, grey(100), mask, W, H)), ["changed", "edges", "left"]); // no reach: the object alone
});
