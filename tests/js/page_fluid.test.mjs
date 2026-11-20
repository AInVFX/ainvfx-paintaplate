import test from "node:test";
import assert from "node:assert/strict";
import { keyframeSlotLine } from "../../web/logic.mjs";

test("a fluid keyframe moved to the nearest frame it can sit on: the HUD names the first frame and the plate's own number", () => {
  assert.equal(keyframeSlotLine(9), "Keyframes snap to the first frame, the last frame or every 8 frames between: frame 9.");
  assert.equal(keyframeSlotLine(1001), "Keyframes snap to the first frame, the last frame or every 8 frames between: frame 1001.");
});
