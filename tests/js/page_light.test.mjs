// The page workstream's check of the eraser on a Light edit (logic.rubDabs): soft dabs with the light brush's own profile,
// so paint, erase and the same paint again leave one paint, with no edge.
import assert from "node:assert/strict";
import { test } from "node:test";
import { dabAlpha, dabFlow, dabsAlong, dabsBox, rubDabs } from "../../web/logic.mjs";

const W = 160, H = 96, SPACING = 0.25, FLOW = 0.3, SPREAD = 1.6; // the light brush's numbers (LIGHT in web/app.mjs)
const box = { x: 0, y: 0, w: W, h: H };
const layer = (alpha = 0) => { const px = new Uint8ClampedArray(W * H * 4); for (let i = 3; i < px.length; i += 4) px[i] = alpha; return px; };
const dabsOf = (points) => dabsAlong(points.map(([x, y, r]) => [x, y, r * SPREAD]), 0, (r) => r * SPACING).dabs;
const alphas = (px) => px.filter((_, i) => i % 4 === 3);
const paint = (px, dabs) => { // the brush's dabs as the canvas lays them with "lighter": one colour, so only alpha adds up, rounded at each dab
  const a = dabFlow(FLOW, SPACING);
  for (const [cx, cy, r] of dabs) for (let y = 0; y < H; y++) for (let x = 0; x < W; x++) {
    const k = dabAlpha(Math.hypot(x + 0.5 - cx, y + 0.5 - cy) / r);
    if (k > 0) px[(y * W + x) * 4 + 3] += 255 * a * k;
  }
};
const erase = (px, dabs) => rubDabs(px, box, dabs, dabFlow(1, SPACING));

test("paint, erase and the same paint again leave one paint: the eraser takes the light away with the brush's profile", () => {
  const dabs = dabsOf([[20, 40, 12], [70, 52, 12], [140, 48, 12]]), once = layer(), px = layer();
  paint(once, dabs); paint(px, dabs); erase(px, dabs);
  assert.equal(Math.max(...alphas(px)), 0, "one pass of the eraser takes away all the light of one pass of the brush");
  paint(px, dabs);
  assert.deepEqual(alphas(px), alphas(once));
  erase(px, dabs); paint(px, dabs); erase(px, dabs); paint(px, dabs);
  assert.deepEqual(alphas(px), alphas(once), "paint, erase, paint, erase and paint again: still one paint");
});

test("the eraser's edge is soft: it takes about all the light on its centre line, and less towards its edge", () => {
  const px = layer(255);
  erase(px, dabsOf([[0, 48, 12], [W, 48, 12]]));
  const column = Array.from({ length: 30 }, (_, d) => px[((48 + d) * W + 80) * 4 + 3]); // from the centre line down
  assert.ok(column[0] <= 3, `about all of it on the centre line: ${column[0]}`);
  assert.equal(column[29], 255, "beyond the dabs' reach the light stays");
  assert.ok(column.every((v, i) => i === 0 || v >= column[i - 1]), `it rises from the centre line: ${column}`);
  assert.ok(new Set(column.filter((v) => v > 0 && v < 255)).size >= 8, `with many steps between none and all: ${column}`);
});

test("dabsBox: the pixels the dabs reach, inside the layer", () => {
  assert.deepEqual(dabsBox([[10.5, 20, 4], [30, 22, 6]], 100, 50), { x: 6, y: 16, w: 30, h: 12 });
  assert.deepEqual(dabsBox([[-3, -3, 4]], 100, 50), { x: 0, y: 0, w: 1, h: 1 });
  assert.equal(dabsBox([[200, 20, 4]], 100, 50), null);
  assert.equal(dabsBox([], 100, 50), null);
});
