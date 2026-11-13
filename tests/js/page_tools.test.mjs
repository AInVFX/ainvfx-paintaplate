// The page workstream's rule for the eraser's key (web/logic.mjs, eraserAfterKey). X held while a stroke is dragged rubs
// the stroke out, and the eraser goes back as it was when X comes up. A tap, shorter than 0.3 s with no stroke, switches it.
import { test } from "node:test";
import assert from "node:assert/strict";
import { eraserAfterKey, ERASER_TAP } from "../../web/logic.mjs";

test("a tap on X switches the eraser on, a second tap switches it off", () => {
  assert.equal(eraserAfterKey(false, 0.08, false), true);
  assert.equal(eraserAfterKey(true, 0.08, false), false);
});

test("X held while a stroke is dragged: the eraser goes back as it was, however short the press", () => {
  assert.equal(eraserAfterKey(false, 0.2, true), false);
  assert.equal(eraserAfterKey(false, 3, true), false);
  assert.equal(eraserAfterKey(true, 3, true), true);
});

test("a press of 0.3 s or more with no stroke changes nothing", () => {
  assert.equal(ERASER_TAP, 0.3);
  assert.equal(eraserAfterKey(false, ERASER_TAP, false), false);
  assert.equal(eraserAfterKey(true, 1.5, false), true);
});
