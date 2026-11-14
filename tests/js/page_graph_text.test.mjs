// The editor graph and the texts that ComfyUI's editor rewrites when it queues
import { test } from "node:test";
import assert from "node:assert/strict";
import { editorGraph } from "../../web/graph.mjs";

const info = {
  PrimitiveStringMultiline: { input: { required: { value: ["STRING", { multiline: true }] } }, output: ["STRING"] },
  CLIPTextEncode: { input: { required: { text: ["STRING", { multiline: true, dynamicPrompts: true }], clip: ["CLIP"] } }, output: ["CONDITIONING"] },
  Label: { input: { required: { label: ["STRING", { multiline: true }] } }, output: ["STRING"] },
};
const graph = (cls, input, value) => editorGraph({
  1: { class_type: "PrimitiveStringMultiline", inputs: { value: "What this section does." }, _meta: { title: "README · EDIT 1" } },
  2: { class_type: cls, inputs: { [input]: value }, _meta: { title: `EDIT 1 · Clean · both passes · Caption [${input}]` } },
}, info);
const text = 'Remove the barn. [{"id": "barn_1", "desc": "a barn"}] // {kept|whole}';

test("a widget that declares dynamicPrompts takes its text from a String (Multiline) node, which the editor sends unchanged", () => {
  const g = graph("CLIPTextEncode", "text", text), encode = g.nodes.find((n) => n.id === 2);
  const link = g.links.find((l) => l[0] === encode.inputs.find((i) => i.name === "text")?.link);
  assert.ok(link, "the text input is fed by a link");
  const holder = g.nodes.find((n) => n.id === link[1]);
  assert.equal(holder.type, "PrimitiveStringMultiline");
  assert.deepEqual(holder.widgets_values, [text]);
  assert.ok(!encode.widgets_values.includes(text), "the encoder's own widget does not hold the text");
  assert.ok(holder.title.startsWith("EDIT 1 · ") && holder.id > 2, "a new node, in the section of the node it feeds");
  assert.equal(g.extra.paintaplate.prompt[2].inputs.text, text, "the page's API graph keeps the text as a value");
  assert.equal(g.last_node_id, holder.id);
});

test("a text in a widget that declares no dynamicPrompts stays the widget's value", () => {
  const g = graph("Label", "label", text);
  assert.deepEqual(g.nodes.find((n) => n.id === 2).widgets_values, [text]);
  assert.ok(!g.nodes.some((n) => n.type === "PrimitiveStringMultiline"));
});
