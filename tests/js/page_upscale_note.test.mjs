// Finish > Upscale: the note under its size list gives the time on this GPU, and the row asks no question as it turns on.
import assert from "node:assert/strict";
import { test } from "node:test";
import { FINISH, upscaleNote } from "../../web/logic.mjs";

test("the note gives whole minutes on this GPU, one at least", () => {
  assert.equal(upscaleNote(1360), "About 23 min on this GPU.");
  assert.equal(upscaleNote(2748), "About 46 min on this GPU.");
  assert.equal(upscaleNote(20), "About 1 min on this GPU.");
});

test("Upscale turns on with no question; SDR to HDR keeps its own", () => {
  assert.equal(FINISH.find((o) => o.id === "upscale").name, "Upscale");
  assert.equal(FINISH.find((o) => o.id === "upscale").ask, undefined);
  assert.equal(typeof FINISH.find((o) => o.id === "hdr").ask, "string");
});
