// The page workstream's check that a saved editor graph carries the page's API graph (graph.editorGraph): tests/graph_live.py
// compares it with app.graphToPrompt() in ComfyUI's own editor. The README notes stay out: the editor draws them as
// MarkdownNote, which sends nothing.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parseWorkflow } from "../../web/logic.mjs";
import { editorGraph, sceneGraph } from "../../web/graph.mjs";

const load = (n) => parseWorkflow(JSON.parse(readFileSync(new URL(`../../web/workflows/${n}.json`, import.meta.url))));
const WF = Object.fromEntries(["edit", "matte", "clean", "cleanup", "shot", "export", "hdr"].map((n) => [n, load(n)]));
const INFO = JSON.parse(readFileSync(new URL("./object_info.scene.json", import.meta.url))).nodes;
const pass = { steps: 8, denoise: 1, grow: 16, feather: 6, sigma: 3 };
const edit = (tool, k) => ({ tool, seed: k, caption: `${tool} caption`, mask: `m${k}.png`, layer: tool === "erase" ? null : `l${k}.png`, quick: pass, full: pass });
const plate = { path: "plates/shot.mp4", config: "ocio://studio-config-latest", cs: "sRGB Encoded Rec.709 (sRGB)", frames: 121, fps: 24,
  work: [1280, 704], prev: [768, 416], track: [960, 528], trackErase: [640, 352] };
const render = { prompt: "Ripple", seed: 1, grow: 53, feather: 13, prefix: "paintaplate/x/graph" };

for (const hdr of [false, true]) test(`the saved graph carries the page's API graph, its README notes left out${hdr ? ", with SDR to HDR" : ""}`, () => {
  const api = sceneGraph(WF, { plate, edits: [edit("erase", 1), edit("paint", 2), edit("light", 3)], render: { ...render, hdr }, about: { version: "1.11.12", name: "shot" } });
  const file = JSON.parse(JSON.stringify(editorGraph(api, INFO))), kept = file.extra.paintaplate.prompt;
  const notes = file.nodes.filter((n) => n.type === "MarkdownNote").map((n) => String(n.id));
  assert.ok(notes.length > 1 && notes.every((id) => api[id]?.class_type === "PrimitiveStringMultiline"), "the README notes are the API graph's PrimitiveStringMultiline nodes");
  assert.deepEqual(Object.keys(kept).sort(), Object.keys(api).filter((id) => !notes.includes(id)).sort());
  assert.deepEqual(file.nodes.filter((n) => n.type !== "MarkdownNote").map((n) => String(n.id)).sort(), Object.keys(kept).sort());
  for (const [id, n] of Object.entries(kept)) assert.deepEqual([n.class_type, n.inputs], [api[id].class_type, api[id].inputs], id);
});
