// A History row's strokes on any frame: the keyframe that a click on the fluid shot's row goes to (logic.nearestKey).
import { test } from "node:test";
import assert from "node:assert/strict";
import { nearestKey } from "../../web/logic.mjs";

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
