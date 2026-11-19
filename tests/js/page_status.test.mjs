// Tests of the status line (logic.statusOf): a fault shows there with its word and its colour, and
// the next line that succeeds replaces it; bookkeeping stays in the log.
import assert from "node:assert/strict";
import { test } from "node:test";
import { statusOf } from "../../web/logic.mjs";

test("an error or a warning reaches the status line with its word, in its colour", () => {
  const oom = "Error: Shot, preview failed: the GPU ran out of memory.";
  assert.deepEqual(statusOf(oom), { text: oom, level: "error" });
  const matte = "Render v1: Track the paint, full size: done in 12.0 s.\n  Warning: matte above 3x the object from frame 25 to 90 (up to 33.1x at frame 65). Check the composite there.";
  assert.deepEqual(statusOf(matte), { text: "Warning: matte above 3x the object from frame 25 to 90 (up to 33.1x at frame 65). Check the composite there.", level: "warn" });
});

test("the next line that succeeds replaces a fault that is over, in the normal colour", () => {
  assert.deepEqual(statusOf("Cache memory: 2 GB.", "error"), { text: "Cache memory: 2 GB.", level: "" });
  assert.deepEqual(statusOf("Edit 1: done in 10.3 s.\n  Seed 259831255.", "warn"), { text: "Edit 1: done in 10.3 s.", level: "" });
});

test("with no fault on show, the log leaves the status line to the code that makes each event", () => {
  assert.equal(statusOf("Edit 1: done in 10.3 s.", ""), null);
  assert.equal(statusOf("Render v1: 1 edit (Light 1), seed 259831255, shot preview off."), null);
});

test("bookkeeping never replaces a fault", () => {
  assert.equal(statusOf("Frame cache: 2 GB (set in View > Cache memory), 121 of 121 frames at 1472 x 828.", "error"), null);
  assert.equal(statusOf("Viewer: wipe, Plate against First frame.", "warn"), null);
  assert.equal(statusOf("Played 121 frames in 2.42 s: 49.6 fps of 50, 0 late, 0 skipped", "error"), null);
});
