import { test } from "node:test";
import assert from "node:assert/strict";
import { logLevel } from "../../web/logic.mjs";

// Follow Matte's summary: a headline, the warnings next, then one detail per line. A warning shows the log line in amber.
test("a matte's log line is amber when its summary holds a warning, whatever its words", () => {
  for (const warn of ["Warning: matte up to 31.1x the object at frame 67. Check the composite there.",
    "Warning: matte above 3x the object from frame 25 to 90 (up to 33.1x at frame 65). Check the composite there.",
    "Warning: matte 4.2x the object at frame 65. Check the composite there.",
    "Warning: object left its place at frame 49. Try another seed, other words or another stroke."])
    assert.equal(logLevel(`Paint matte (full): tracked on 106 of 121 frames.\n  ${warn}\n  Removed: SAM detections too far from the object, on 2 frames.`), "warn", warn);
  assert.equal(logLevel("Paint matte (full): tracked on 121 of 121 frames.\n  Flicker: pieces of the matte for 3 frames or fewer, on 5 frames (up to 59% of the matte at frame 53)."), "");
  assert.equal(logLevel("Clean matte: tracked on 121 of 121 frames."), "", "no warning line: nothing to flag");
});
