// The confirmation once the export is written: a headline for the HUD and the status line, then the writer's summary as
// detail lines, each with one full stop, whether the summary brings its own or not.
import { test } from "node:test";
import assert from "node:assert/strict";
import { exportDone } from "../../web/logic.mjs";

test("the Export line is a headline, then each line of the summary two spaces in", () => {
  assert.equal(exportDone("Save Plate: 1 file written to /out/paintaplate/a/v1/export.\n  First files: export.mp4."),
    "Export: done, in ComfyUI's output folder.\n  Save Plate: 1 file written to /out/paintaplate/a/v1/export.\n  First files: export.mp4.");
});

test("a detail line ends with one full stop when the summary has none", () => {
  assert.equal(exportDone("121 half-float EXR frames in ACES2065-1, in paintaplate/a/v1/hdr"),
    "Export: done, in ComfyUI's output folder.\n  121 half-float EXR frames in ACES2065-1, in paintaplate/a/v1/hdr.");
});

test("the Export line stands with no summary", () => {
  assert.equal(exportDone(""), "Export: done, in ComfyUI's output folder.");
  assert.equal(exportDone(undefined), "Export: done, in ComfyUI's output folder.");
});
