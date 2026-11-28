// The editor graph's sizes against the ones ComfyUI draws
import { test } from "node:test";
import assert from "node:assert/strict";
import { editorGraph } from "../../web/graph.mjs";

const info = {
  PrimitiveStringMultiline: { input: { required: { value: ["STRING", { multiline: true }] } }, output: ["STRING"] },
  EmptyImage: { input: { required: { width: ["INT", { default: 512 }], height: ["INT", { default: 512 }] } }, output: ["IMAGE"] },
  ImageInvert: { input: { required: { image: ["IMAGE"] } }, output: ["IMAGE"] },
};
// ComfyUI 0.44.2 (frontend 1.57.6) sets each node it loads to the larger of its saved size and its own, and its own width
// holds the title: about 40 px plus 6.6 px a character
const drawn = (title) => 40 + 6.6 * title.length;

test("a node is planned at least as wide as ComfyUI draws its title, so the next column starts right of it", () => {
  const step = `EDIT 1 · Light "${"warm low sun from the right ".repeat(2).trim()}" · edit preview at 768 x 432`;
  const prompt = {
    1: { class_type: "PrimitiveStringMultiline", inputs: { value: "What this section does." }, _meta: { title: "README · EDIT 1" } },
    2: { class_type: "EmptyImage", inputs: { width: 64, height: 64 }, _meta: { title: `${step} · EmptyImage [width, height]` } },
    3: { class_type: "ImageInvert", inputs: { image: ["2", 0] }, _meta: { title: `${step} · ImageInvert` } },
  };
  const [a, b] = [2, 3].map((id) => editorGraph(prompt, info).nodes.find((n) => n.id === id));
  for (const n of [a, b]) assert.ok(n.size[0] >= drawn(n.title), `${n.title.length} characters: ${n.size[0]} px planned, about ${drawn(n.title)} px drawn`);
  assert.ok(a.pos[0] + drawn(a.title) < b.pos[0], "the next column starts right of the drawn title");
});
