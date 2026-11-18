// Tests that SDR to HDR asks for the node classes its workflow holds (logic.workflowClasses):
// the page turns SDR to HDR on when every class of web/workflows/hdr.json is present in ComfyUI.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { workflowClasses } from "../../web/logic.mjs";

test("workflowClasses lists each node class once, sorted", () => {
  assert.deepEqual(workflowClasses({ 1: { class_type: "B" }, 2: { class_type: "A" }, 3: { class_type: "B" }, note: "text" }), ["A", "B"]);
});

test("the classes of hdr.json are the ones the SDR to HDR check asks for", () => {
  const hdr = workflowClasses(JSON.parse(readFileSync(new URL("../../web/workflows/hdr.json", import.meta.url), "utf8")));
  assert.ok(hdr.includes("VAEComputeDtype") && hdr.includes("LTXVLoadConditioning"), hdr.join(", "));
  assert.ok(!hdr.includes("LTXVVAEForceFloat32") && !hdr.includes("LTXVHDRDecodePostprocess"), hdr.join(", "));
});
