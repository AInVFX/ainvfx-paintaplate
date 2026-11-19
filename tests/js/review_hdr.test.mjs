import { test } from "node:test";
import assert from "node:assert/strict";
import { hdrAfterComposite, wantsHdr } from "../../web/logic.mjs";

// A Light edit with SDR to HDR on: on a plate whose format holds nothing above 1.0, SDR to HDR runs on the relit composite
// (hdrAfterComposite) and not on the shot (wantsHdr), so the new light comes back in HDR; a plate that holds values above 1.0
// keeps them under the relight, and neither runs.
const mp4 = { kind: "video", sample: "u8" }, exr = { kind: "sequence", ext: ".exr", sample: "f16" };
test("SDR to HDR with a Light edit: on the relit composite for an SDR plate, never on the shot", () => {
  assert.equal(hdrAfterComposite(mp4, ["light"], true), true, "a video plate: the relit composite goes through SDR to HDR");
  assert.equal(hdrAfterComposite(mp4, ["paint", "light"], true), true, "with a paint too: the whole composite");
  assert.equal(wantsHdr(mp4, ["paint", "light"], true), false, "and not on the shot");
  assert.equal(hdrAfterComposite(mp4, ["paint"], true), false, "no Light edit: SDR to HDR stays on the shot");
  assert.equal(wantsHdr(mp4, ["paint"], true), true);
  assert.equal(hdrAfterComposite(mp4, ["light"], false), false, "SDR to HDR off: neither");
  assert.equal(hdrAfterComposite(mp4, ["light"], true, 100), false, "a video that decodes above 1.0 (PQ) keeps its own values under the relight");
  assert.equal(hdrAfterComposite(null, ["light"], true), false);
});
