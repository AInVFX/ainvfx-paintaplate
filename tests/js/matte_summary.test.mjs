import { test } from "node:test";
import assert from "node:assert/strict";
import { matteLargest } from "../../web/logic.mjs";

// Follow Matte's summary since wave 7 (M8): a headline, the warning next when there is one, then one detail per line.
test("the matte summary's warning: the largest matte against the object, and its frame", () => {
  const warned = "tracked on 106 of 121 frames.\n  Warning: matte up to 31.1x the object at frame 67. Check the composite there.\n  Removed: SAM detections too far from the object, on 2 frames.";
  assert.deepEqual(matteLargest(warned), { ratio: 31.1, frame: 67, warn: true });
  assert.deepEqual(matteLargest("tracked on 0 of 6 frames.\n  Warning: matte up to 60.0x the object at frame 0. Check the composite there.\n  Held: first-frame mask, on every frame."), { ratio: 60, frame: 0, warn: true });
  assert.equal(matteLargest("tracked on 121 of 121 frames."), null, "no warning line: nothing to flag");
  assert.equal(matteLargest(undefined), null);
});
