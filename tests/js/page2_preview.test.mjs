// A new preview size while a render makes a step: which step stops so that the preview at the new size comes first
// (logic.stopsForPreview).
import { test } from "node:test";
import assert from "node:assert/strict";
import { stopsForPreview } from "../../web/logic.mjs";

test("a full-size step and a preview at the old size stop for the preview at the new size", () => {
  assert.equal(stopsForPreview({ id: "fluidfull", final: true }, "full"), true);
  assert.equal(stopsForPreview({ id: "full", final: true }, "full"), true);
  assert.equal(stopsForPreview({ id: "fluid", preview: true }, "preview"), true);
  assert.equal(stopsForPreview({ id: "shot", preview: true }, "preview"), true);
});

test("the object tracked for Clean, a Finish step and the export go on", () => {
  assert.equal(stopsForPreview({ id: "erase" }, "full"), false);
  assert.equal(stopsForPreview({ id: "hdr", final: true }, "finish"), false);
  assert.equal(stopsForPreview({ id: "upcomp", final: true, up: true }, "finish"), false);
  assert.equal(stopsForPreview({ id: "export", final: true, onDemand: true }, "export"), false);
});
