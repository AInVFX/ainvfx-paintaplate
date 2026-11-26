// A step's result as it is made: whether it plays by itself (logic.autoplays), and its line (logic.resultLine).
import { test } from "node:test";
import assert from "node:assert/strict";
import { autoplays, resultLine } from "../../web/logic.mjs";

const idle = { playing: false, painting: false, selected: false, keying: false, pinned: false, heldHere: false, halted: false };

test("a step's result plays by itself, and a player that plays goes on with the newest step", () => {
  assert.equal(autoplays(idle), true);
  assert.equal(autoplays({ ...idle, playing: true, pinned: true }), true);
  assert.equal(autoplays({ ...idle, playing: true, selected: true }), true);
});

test("it waits while the person paints, has an edit or the keyframes selected, looks at a pinned step, or paused by hand", () => {
  for (const k of ["painting", "selected", "keying", "pinned", "heldHere"]) assert.equal(autoplays({ ...idle, [k]: true }), false, k);
  assert.equal(autoplays({ ...idle, playing: true, halted: true }), false);
});

test("its lines, as approved", () => {
  assert.equal(resultLine("Fluid shot, preview", true, { follows: "The full-size fluid shot follows." }), "Fluid shot, preview: playing. The full-size fluid shot follows.");
  assert.equal(resultLine("Fluid shot, preview", false, { follows: "The full-size fluid shot follows." }), "Fluid shot, preview: ready. Press Space to play it. The full-size fluid shot follows.");
  assert.equal(resultLine("Shot, full size", true, { asMade: ", as LTX made it", follows: "The full-size composite follows." }), "Shot, full size: playing, as LTX made it. The full-size composite follows.");
  assert.equal(resultLine("Shot, full size", false, { asMade: ", as LTX made it", follows: "The full-size composite follows." }), "Shot, full size: ready, as LTX made it. Press Space to play it. The full-size composite follows.");
  assert.equal(resultLine("Composite, full size", true), "Composite, full size: playing.");
  assert.equal(resultLine("Composite, full size", false), "Composite, full size: ready. Press Space to play it.");
});
