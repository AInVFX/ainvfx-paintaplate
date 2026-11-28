// The editor graph's rows: a section longer than 8 columns continues on a new row, and each of its rows opens with a station
import { test } from "node:test";
import assert from "node:assert/strict";
import { editorGraph } from "../../web/graph.mjs";

const info = {
  PrimitiveStringMultiline: { input: { required: { value: ["STRING", { multiline: true }] } }, output: ["STRING"] },
  EmptyImage: { input: { required: { width: ["INT", { default: 512 }] } }, output: ["IMAGE"] },
  Mix: { input: { required: { a: ["IMAGE"], b: ["IMAGE"] } }, output: ["IMAGE"] },
};
// section A makes an image; section B is a chain of 12 Mix nodes, each taking the chain and A's image
const page = {
  100: { class_type: "PrimitiveStringMultiline", inputs: { value: "The image." }, _meta: { title: "README · A" } },
  101: { class_type: "EmptyImage", inputs: { width: 64 }, _meta: { title: "A · EmptyImage" } },
  200: { class_type: "PrimitiveStringMultiline", inputs: { value: "The chain." }, _meta: { title: "README · B" } },
};
for (let k = 1; k <= 12; k++) page[200 + k] = { class_type: "Mix", inputs: { a: [String(k === 1 ? 101 : 199 + k), 0], b: ["101", 0] }, _meta: { title: `B · Mix ${k}` } };
const g = editorGraph(page, info), byId = new Map(g.nodes.map((n) => [n.id, n])), link = new Map(g.links.map((l) => [l[0], l]));
const rect = (n) => [n.pos[0], n.pos[1] - 30, n.pos[0] + n.size[0], n.pos[1] + n.size[1]]; // with a title bar, as graph_live counts it
const source = (n, name) => { // the node and slot an input takes its value from, through any Reroute
  let l = link.get(n.inputs.find((i) => i.name === name).link);
  while (byId.get(l[1]).type === "Reroute") l = link.get(byId.get(l[1]).inputs[0].link);
  return [String(l[1]), l[2]];
};

test("a section longer than 8 columns continues on a new row, below the first and from its left", () => {
  const first = [201, 202, 203, 204, 205, 206, 207, 208].map((id) => byId.get(id)), second = [209, 210, 211, 212].map((id) => byId.get(id));
  assert.ok(second.every((n) => rect(n)[1] > Math.max(...first.map((m) => rect(m)[3]))), "the second row lies below the first");
  assert.ok(second[0].pos[0] < first[1].pos[0], "the second row starts at the left");
});

test("each row of that section opens with one Reroute per value from outside that two or more of its inputs take, and every node still takes its own value", () => {
  const reroutes = g.nodes.filter((n) => n.type === "Reroute");
  assert.equal(reroutes.length, 2, "A's image, once in each row; the chain, which only Mix 9 takes, links straight");
  assert.equal(link.get(byId.get(209).inputs.find((i) => i.name === "a").link)[1], 208, "Mix 9 takes Mix 8 straight from the row above");
  for (const r of reroutes) assert.ok(r.outputs[0].links.every((id) => byId.get(link.get(id)[3]).pos[0] > r.pos[0] + r.size[0]), "a station feeds the nodes at its right");
  for (let k = 1; k <= 12; k++) for (const name of ["a", "b"]) assert.deepEqual(source(byId.get(200 + k), name), page[200 + k].inputs[name], `Mix ${k}.${name}`);
  assert.equal(g.last_node_id, Math.max(...g.nodes.map((n) => n.id)));
  assert.equal(g.last_link_id, g.links.length);
});

test("in rows, no node stands over another, and the section's group holds them all", () => {
  for (let i = 0; i < g.nodes.length; i++) for (let j = i + 1; j < g.nodes.length; j++) {
    const [a, b] = [rect(g.nodes[i]), rect(g.nodes[j])];
    assert.ok(!(Math.min(a[2], b[2]) > Math.max(a[0], b[0]) && Math.min(a[3], b[3]) > Math.max(a[1], b[1])), `${g.nodes[i].id} over ${g.nodes[j].id}`);
  }
  const [x, y, w, h] = g.groups[1].bounding;
  for (const r of g.nodes.filter((n) => n.id >= 200).map(rect)) assert.ok(r[0] >= x && r[1] >= y && r[2] <= x + w && r[3] <= y + h);
});
