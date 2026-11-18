// The frame cache's plan when only its budget changes (frames.cachePlan with a size per source): the frames keep their
// size, so a larger budget fits more of them and drops none, and a smaller one fits fewer.
import { test } from "node:test";
import assert from "node:assert/strict";
import { cachePlan } from "../../web/frames.mjs";

const fit = [1700, 956], movie = [1920, 1080];
const first = cachePlan({ budget: 2e9, frames: 121, fit, sources: [{ id: "shot", movie, show: true }] }).shot;
const keep = (budget, more = []) => cachePlan({ budget, frames: 121, fit, sources: [{ id: "shot", movie, show: true, size: [first.width, first.height] }, ...more] });

test("a larger budget keeps the frame size and every frame", () => {
  const big = keep(4e9).shot;
  assert.deepEqual([big.width, big.height, big.fits], [first.width, first.height, 121]);
});

test("a smaller budget keeps the frame size: fewer of its frames fit", () => {
  const small = keep(655e6).shot;
  assert.deepEqual([small.width, small.height], [first.width, first.height]);
  assert.equal(small.fits, Math.floor(655e6 / (first.width * first.height * 4)));
  assert.ok(small.budget <= 655e6);
});

test("with no size, a smaller budget still makes the frames smaller so that all fit, as a new plate or view gets", () => {
  const fresh = cachePlan({ budget: 655e6, frames: 121, fit, sources: [{ id: "shot", movie, show: true }] }).shot;
  assert.ok(fresh.width < first.width && fresh.fits === 121, JSON.stringify(fresh));
});

test("a source with a size and one without share the budget as before: the one on show first", () => {
  const both = keep(1e9, [{ id: "plate", movie, show: false }]);
  assert.equal(both.shot.width, first.width);
  assert.ok(both.shot.budget + both.plate.budget <= 1e9);
});
