import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { modelsBehind, workflowFiles, workflowsFor } from "../../web/models.mjs";

const registry = JSON.parse(readFileSync(new URL("../../web/models.json", import.meta.url)));
const prompt = (name) => JSON.parse(readFileSync(new URL(`../../web/workflows/${name}.json`, import.meta.url))).prompt ??
  JSON.parse(readFileSync(new URL(`../../web/workflows/${name}.json`, import.meta.url)));

test("a workflow's model files come from its loaders", () => {
  assert.ok(workflowFiles(prompt("edit")).has("flux3-image-klein-int8-convrot.safetensors"));
  assert.ok(workflowFiles(prompt("fluid")).has("ainvfx-fluid.safetensors"));
});

test("the models behind a result follow its edits", () => {
  const ids = (w) => modelsBehind(registry, w, prompt).map((m) => m.id);
  const fluid = ids(workflowsFor({ fluid: true }));
  assert.ok(fluid.includes("fluid") && fluid.includes("ltx") && !fluid.includes("klein") && !fluid.includes("sam"));
  const erase = ids(workflowsFor({ tools: ["erase"] }));
  assert.ok(["klein", "klein-upsampler", "sam", "inoutpaint", "ltx"].every((i) => erase.includes(i)) && !erase.includes("ripple"));
  const paint = ids(workflowsFor({ tools: ["paint"], hdr: true }));
  assert.ok(paint.includes("ripple") && paint.includes("hdr") && !paint.includes("inoutpaint"));
  assert.deepEqual(workflowsFor({}), []);
});
