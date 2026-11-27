// Export's words where there is no edit, and the graph tick's detail for the scene's graphs (logic.exportWords): the Plate
// tick names what the plate is, and the graph tick says how many workflows the zip holds.
import assert from "node:assert/strict";
import test from "node:test";
import { exportWords } from "../../web/logic.mjs";

test("the Plate tick names the plate itself, or the fluid shot, where there is no edit; the plate under the edits where there are", () => {
  const detail = (kind, bytes = 0) => exportWords({ kind, bytes }).elements.plate.detail;
  assert.deepEqual(["plate", "upscaled", "fluid", "edits", "relit"].map((k) => detail(k)),
    ["the plate itself", "the plate itself", "the fluid shot", "the plate under the edits", "the plate under the edits"]);
  assert.equal(detail("plate", 2.5e9), "the plate itself, 2.50 GB");
});

test("the graph tick says what its workflows make, and how many run one after the other", () => {
  const detail = (graphs) => exportWords({ kind: "edits", graphs }).elements.graph.detail;
  assert.equal(detail(["edits"]), "the scene as one ComfyUI workflow, with its source images");
  assert.equal(detail(["finish"]), "Finish's steps as one ComfyUI workflow");
  assert.equal(detail(["fluid_shot"]), "the fluid shot as one ComfyUI workflow, with its source images");
  assert.equal(detail(["fluid_shot", "edits", "finish"]), "the scene as 3 ComfyUI workflows, run one after the other, with their source images");
});
