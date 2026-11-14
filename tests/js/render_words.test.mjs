// The render's lines name the graphics card « GPU », never « card »: the memory rule's lines in the page and the GPU report.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(`../../${path}`, import.meta.url), "utf8");

test("the memory rule's line says that the GPU holds one model family at a time", () => {
  const app = read("web/app.mjs");
  assert.match(app, /This GPU holds one model family at a time\./);
  assert.doesNotMatch(app, /This card holds/);
});

test("the GPU report names the GPU, never the card, where a person reads it", () => {
  const report = read("tests/gpu_matrix.py");
  assert.match(report, /none: the GPU decides/);
  assert.doesNotMatch(report, /the card (decides|gives)/);
});
