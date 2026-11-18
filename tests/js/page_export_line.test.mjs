// The status line once the export is written: one full stop, whether the writer's summary brings its own or not.
import { test } from "node:test";
import assert from "node:assert/strict";
import { exportDone } from "../../web/logic.mjs";

test("the Export line ends with one full stop when the summary's first line has its own", () => {
  assert.equal(exportDone("Save Plate: 1 file written to /out/paintaplate/a/v1/export.\nFirst files: export.mp4."),
    "Export: done, in ComfyUI's output folder: Save Plate: 1 file written to /out/paintaplate/a/v1/export.");
});

test("the Export line ends with one full stop when the summary has none", () => {
  assert.equal(exportDone("121 half-float EXR frames in ACES2065-1, in paintaplate/a/v1/hdr"),
    "Export: done, in ComfyUI's output folder: 121 half-float EXR frames in ACES2065-1, in paintaplate/a/v1/hdr.");
});

test("the Export line stands with no summary", () => {
  assert.equal(exportDone(""), "Export: done, in ComfyUI's output folder.");
  assert.equal(exportDone(undefined), "Export: done, in ComfyUI's output folder.");
});
