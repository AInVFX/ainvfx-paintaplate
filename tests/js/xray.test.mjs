import { test } from "node:test";
import assert from "node:assert/strict";
import { XRAY_ALPHA, alphaFromBytes, alphaFromHalfs, halfToFloat, tintPixels, xrayPlan } from "../../web/xray.mjs";

const r = { erased: { found: { movie_a: "a" } }, full: { found: { movie_a: "a", movie_b: "bf" } }, exported: null };
const pv = { mattes: { found: { movie_a: "a", movie_b: "bp" } } };

test("the X-ray's mattes: a light edit tints the whole frame, the export's matte once made, else the size on show", () => {
  assert.deepEqual(xrayPlan({ tools: [] }), { from: "none", urls: [] });
  assert.deepEqual(xrayPlan({ tools: ["paint", "light"], r, pv, full: true }), { from: "light", urls: [] });
  assert.deepEqual(xrayPlan({ tools: ["paint", "erase"], r, pv, full: true }), { from: "full", urls: ["a", "bf"] });
  assert.deepEqual(xrayPlan({ tools: ["paint", "erase"], r, pv, full: false }), { from: "preview", urls: ["a", "bp"] });
  assert.deepEqual(xrayPlan({ tools: ["paint"], r: { ...r, exported: { matte: "m" } }, pv, full: false }), { from: "export", urls: ["m"] });
  assert.deepEqual(xrayPlan({ tools: ["erase"], r: { erased: r.erased }, pv: null, full: true }), { from: "preview", urls: ["a"] }); // no full-size mattes yet
  assert.deepEqual(xrayPlan({ tools: ["paint"], r: {}, pv: null }), { from: "none", urls: [] });
});

test("a grey matte becomes the tint's opacity, from half floats or bytes, the union of the mattes", () => {
  assert.equal(halfToFloat(0x3c00), 1); assert.equal(halfToFloat(0x3800), 0.5); assert.equal(halfToFloat(0xc400), -4);
  assert.deepEqual([...alphaFromHalfs(new Uint16Array([0x3c00, 0x3c00, 0x3c00, 0x3800, 0x3800, 0x3800, 0xbc00, 0, 0]))], [255, 128, 0]);
  assert.deepEqual([...alphaFromBytes(new Uint8ClampedArray([255, 255, 255, 255, 0, 0, 0, 255]))], [255, 0]);
  const px = tintPixels([new Uint8ClampedArray([255, 0, 10]), new Uint8ClampedArray([0, 0, 200])], 3, [1, 2, 3]);
  assert.deepEqual([...px], [1, 2, 3, Math.round(255 * XRAY_ALPHA), 1, 2, 3, 0, 1, 2, 3, Math.round(200 * XRAY_ALPHA)]);
});
