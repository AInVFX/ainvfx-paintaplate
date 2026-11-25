import assert from "node:assert/strict";
import test from "node:test";
import { exportWords, missingLine, outputPath, zipRows } from "../../web/logic.mjs";

// Export names every file of its zip as the page knows it from the job that made it, so a step reused from another render
// reaches the zip; a part asked for with no file stops Export with a line that names it, in the dialog's words.
const STEPS = { comp: "Composite, full size", shot: "Shot, full size", up: "Composite, upscaled" };

test("a view address names its file in ComfyUI's output folder", () => {
  assert.equal(outputPath("/view?filename=raw_00001_.mp4&subfolder=paintaplate%2Fp%2Fv2%2Ffull&type=output"), "output:paintaplate/p/v2/full/raw_00001_.mp4");
  assert.equal(outputPath("/view?filename=a.png&subfolder=&type=output"), "output:a.png");
  assert.equal(outputPath("/view?filename=a.png&subfolder=x&type=temp"), null);
  assert.equal(outputPath(undefined), null);
});

test("each part asked has its name in the zip, its row's label and its file, or null", () => {
  const words = exportWords({ kind: "edits", steps: STEPS, spec: { kind: "video" } });
  const rows = zipRows(["export", "shot", "upscaled", "upmatte"], words, { export: "output:x/export/desk.mov", shot: "output:x/full/raw.mp4", upscaled: "output:x/up/export" });
  assert.deepEqual(rows, [["export", "composite_full_size", "Composite, full size", "output:x/export/desk.mov"], ["shot", "shot_full_size", "Shot, full size", "output:x/full/raw.mp4"],
    ["upscaled", "composite_upscaled", "Composite, upscaled", "output:x/up/export"], ["upmatte", "matte_upscaled", "Matte, upscaled", null]]);
});

test("the line names every part with no file", () => {
  assert.equal(missingLine(["Shot, full size"]), "Error: Export stopped: Shot, full size has no file on disk.");
  assert.equal(missingLine(["Shot, full size", "Matte", "Composite, upscaled"]), "Error: Export stopped: Shot, full size, Matte and Composite, upscaled have no file on disk.");
});
