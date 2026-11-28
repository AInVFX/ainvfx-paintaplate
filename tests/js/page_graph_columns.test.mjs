// The editor graph's columns: a node stands in the column before its first consumer in its section
import { test } from "node:test";
import assert from "node:assert/strict";
import { editorGraph } from "../../web/graph.mjs";

const info = {
  PrimitiveStringMultiline: { input: { required: { value: ["STRING", { multiline: true }] } }, output: ["STRING"] },
  EmptyImage: { input: { required: { width: ["INT", { default: 512 }] } }, output: ["IMAGE"] },
  Mix: { input: { required: { a: ["IMAGE"], b: ["IMAGE"] } }, output: ["IMAGE"] },
};

test("a node stands in the column before its first consumer, so its link stays short", () => {
  const page = {
    300: { class_type: "PrimitiveStringMultiline", inputs: { value: "A chain." }, _meta: { title: "README · C" } },
    301: { class_type: "EmptyImage", inputs: { width: 64 }, _meta: { title: "C · EmptyImage, the chain's start" } },
    302: { class_type: "Mix", inputs: { a: ["301", 0], b: ["301", 0] }, _meta: { title: "C · Mix 1" } },
    303: { class_type: "Mix", inputs: { a: ["302", 0], b: ["301", 0] }, _meta: { title: "C · Mix 2" } },
    304: { class_type: "Mix", inputs: { a: ["303", 0], b: ["305", 0] }, _meta: { title: "C · Mix 3" } },
    305: { class_type: "EmptyImage", inputs: { width: 32 }, _meta: { title: "C · EmptyImage, for Mix 3 only" } },
  };
  const x = new Map(editorGraph(page, info).nodes.map((n) => [n.id, n.pos[0]]));
  assert.equal(x.get(305), x.get(303), "the image for Mix 3 stands in the column of Mix 2, the one before Mix 3");
  assert.ok(x.get(301) < x.get(302), "the chain's start stays before Mix 1, its first consumer");
});
