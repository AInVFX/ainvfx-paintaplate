// A History row's strokes on any frame: the keyframe that a click on the fluid shot's row goes to (logic.nearestKey), and
// the wipe's name for a row's strokes (logic.strokesLabel).
import { test } from "node:test";
import assert from "node:assert/strict";
import { nearestKey, strokesLabel } from "../../web/logic.mjs";

test("a click on the fluid shot's row goes to its keyframe nearest the frame displayed", () => {
  assert.equal(nearestKey([0, 16], 12), 16);
  assert.equal(nearestKey([0, 16], 4), 0);
  assert.equal(nearestKey([16, 0, 32], 30), 32);
  assert.equal(nearestKey([16], 0), 16);
});

test("two keyframes as near: the earlier one; no keyframe: none", () => {
  assert.equal(nearestKey([16, 0], 8), 0);
  assert.equal(nearestKey([], 5), null);
});

test("the wipe names a row's strokes by its tool and number, and a fluid shot's as keyframes", () => {
  assert.equal(strokesLabel("Paint", 2, false), "Paint 2, strokes");
  assert.equal(strokesLabel("Fluid", 1, true), "Fluid 1, keyframes");
});
