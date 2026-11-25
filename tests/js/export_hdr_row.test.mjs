// SDR to HDR's frames in an export: the row « HDR », in hdr/, for what the files hold. Over a fluid shot, where SDR to HDR
// runs after the composite, the edits keep their rows and the composite's movie keeps the composite's name.
import test from "node:test";
import assert from "node:assert/strict";
import { downloadLines, exportWords, EXR_FRAMES } from "../../web/logic.mjs";

const STEPS = { comp: "Composite, full size", shot: "Shot, full size", up: "SDR to HDR, upscaled" }; // the Render panel's names, as the page gives them

test("SDR to HDR's frames are the row « HDR », in hdr/: the plate alone, a relit result, the edits over a fluid shot", () => {
  for (const args of [{ kind: "plate", exr: true }, { kind: "relit", exr: true }, { kind: "edits", exr: true, last: true }]) {
    const w = exportWords({ ...args, steps: STEPS });
    assert.equal(w.rows.export.label, "HDR", args.kind);
    assert.equal(w.rows.export.detail, EXR_FRAMES);
    assert.equal(w.zip.hdr, "hdr");
  }
});

test("over a fluid shot with SDR to HDR on, the edits keep their rows, and the composite's movie keeps the composite's name", () => {
  const w = exportWords({ kind: "edits", exr: true, last: true, steps: STEPS });
  assert.deepEqual([w.rows.review.shown, w.rows.matte.shown, w.rows.shot.shown], [true, true, true]);
  assert.equal(w.zip.review, "composite_full_size");
  assert.equal(downloadLines("smoke_v2.zip", ["hdr", "matte", "review"], w.rows), "Download: smoke_v2.zip.\n  HDR.\n  Matte.\n  Composite, full size, as a movie.");
});

test("Upscale's set of SDR to HDR's frames is « HDR, upscaled », in hdr_upscaled/", () => {
  const w = exportWords({ kind: "plate", exr: true, upHdr: true, steps: STEPS });
  assert.equal(w.rows.upscaled.label, "HDR, upscaled");
  assert.equal(w.zip.up.export, "hdr_upscaled");
});
