// The X-ray shows the matte the composite of the size on show used (xray.xrayPlan): Fit to Plate's, aligned to the plate,
// which the comp and review jobs write as a grey movie. The tracking mattes stand in only until a composite exists.
import { test } from "node:test";
import assert from "node:assert/strict";
import { xrayPlan } from "../../web/xray.mjs";

const r = { erased: { found: { movie_a: "a" } }, full: { found: { movie_a: "a", movie_b: "bf" } }, compMatte: "rm" };
const pv = { mattes: { found: { movie_a: "a", movie_b: "bp" } }, compMatte: "pm" };

test("a composite's own matte comes before the tracking mattes, at the size on show", () => {
  assert.deepEqual(xrayPlan({ tools: ["paint", "erase"], r, pv, full: true }), { from: "full", urls: ["rm"] });
  assert.deepEqual(xrayPlan({ tools: ["paint", "erase"], r, pv, full: false }), { from: "preview", urls: ["pm"] });
});

test("the export's matte still comes first, and a Light edit still tints the whole frame", () => {
  assert.deepEqual(xrayPlan({ tools: ["paint"], r: { ...r, exported: { matte: "m" } }, pv, full: true }), { from: "export", urls: ["m"] });
  assert.deepEqual(xrayPlan({ tools: ["light", "paint"], r, pv, full: true }), { from: "light", urls: [] });
});

test("before the full-size composite, the full-size tracking mattes; before any composite, the preview's", () => {
  assert.deepEqual(xrayPlan({ tools: ["paint"], r: { ...r, compMatte: null }, pv, full: true }), { from: "tracking", urls: ["a", "bf"] });
  assert.deepEqual(xrayPlan({ tools: ["paint"], r, pv: { ...pv, compMatte: null }, full: false }), { from: "tracking", urls: ["a", "bp"] });
});
