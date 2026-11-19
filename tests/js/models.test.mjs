import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { modelsBehind, workflowFiles } from "../../web/models.mjs";

const registry = JSON.parse(readFileSync(new URL("../../web/models.json", import.meta.url)));
const prompt = (name) => JSON.parse(readFileSync(new URL(`../../web/workflows/${name}.json`, import.meta.url))).prompt ??
  JSON.parse(readFileSync(new URL(`../../web/workflows/${name}.json`, import.meta.url)));

test("a workflow's model files come from its loaders", () => {
  assert.ok(workflowFiles(prompt("edit")).has("flux3-image-klein-int8-convrot.safetensors"));
  assert.ok(workflowFiles(prompt("fluid")).has("ainvfx-fluid.safetensors"));
});
