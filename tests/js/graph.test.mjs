import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parseWorkflow } from "../../web/logic.mjs";
import { sceneGraph } from "../../web/graph.mjs";

const WF = Object.fromEntries(["edit", "matte", "clean", "cleanup", "shot", "export"].map((n) =>
  [n, parseWorkflow(JSON.parse(readFileSync(new URL(`../../web/workflows/${n}.json`, import.meta.url))))]));
const plate = { path: "plates/shot.mp4", config: "ocio://studio-config-latest", cs: "sRGB Encoded Rec.709 (sRGB)", frames: 121, work: [1280, 704], prev: [768, 416], track: [960, 528], trackErase: [640, 352] };
const pass = { steps: 8, denoise: 1, grow: 16, feather: 6, sigma: 3 };
const edit = (tool, k) => ({ tool, seed: k, caption: `${tool} caption`, mask: `m${k}.png`, layer: tool === "erase" ? null : `l${k}.png`, quick: pass, full: pass });
const render = { prompt: "Ripple", seed: 1, grow: 53, feather: 13, prefix: "paintaplate/x/graph" };
const count = (g, cls) => Object.values(g).filter((n) => n.class_type === cls).length;

function linked(g) { // every link points at a node of the graph
  for (const [id, node] of Object.entries(g)) for (const [k, v] of Object.entries(node.inputs))
    if (Array.isArray(v)) assert.ok(g[v[0]], `${id}.${k} points at a missing ${v[0]}`);
}

test("a scene is one prompt: files only for the plate and the strokes, frames between steps by link, each model loaded once", () => {
  const g = sceneGraph(WF, { plate, edits: [edit("erase", 1), edit("paint", 2), edit("light", 3)], render });
  linked(g);
  const files = Object.values(g).filter((n) => ["LoadImage", "LoadImageMask"].includes(n.class_type)).map((n) => n.inputs.image).sort();
  assert.deepEqual(files, ["l2.png", "l3.png", "m1.png", "m2.png", "m3.png"]);
  assert.ok(Object.values(g).every((n) => n.class_type !== "PaintAPlate_LoadPlate" || n.inputs.path === plate.path));
  assert.equal(count(g, "PaintAPlate_LoadPlate"), 1); // the plate decodes once
  assert.equal(count(g, "UNETLoader"), 2); // Klein and LTX 2.5
  assert.equal(count(g, "SaveImage"), 0);
  assert.equal(count(g, "PaintAPlate_SaveFrames"), 1); // the export's matte; the frames handed between steps are links
  assert.equal(count(g, "PaintAPlate_SavePlate"), 1);
  assert.equal(count(g, "SAM3_VideoTrack"), 2); // the erase on the plate, the paint on the shot
  const captions = Object.values(g).filter((n) => n.class_type === "CLIPTextEncode").map((n) => n.inputs.text);
  for (const c of ["erase caption", "paint caption", "light caption"]) assert.ok(captions.includes(c), c);
});

test("an erase alone needs no Ripple pass, a relight alone no tracking and no matte", () => {
  const erase = sceneGraph(WF, { plate, edits: [edit("erase", 1)], render });
  linked(erase);
  assert.equal(count(erase, "LTXVInpaintPreprocess"), 1);
  assert.ok(!Object.values(erase).some((n) => n.inputs.lora_name === "LTX25_Ripple_v11.safetensors"));
  const light = sceneGraph(WF, { plate, edits: [edit("light", 1)], render });
  linked(light);
  assert.equal(count(light, "SAM3_VideoTrack"), 0);
  assert.equal(count(light, "SaveImage"), 0);
  assert.equal(count(light, "PaintAPlate_SaveFrames"), 0); // a relight alone: no matte to save
  assert.equal(Object.values(light).find((n) => n.class_type === "PaintAPlate_SavePlate").inputs.keep_untouched, false);
});

test("an erase renders at half size, then 2 steps at full size from it, with the scene's prompt", () => {
  const g = sceneGraph(WF, { plate, edits: [edit("erase", 1)], render: { ...render, erasePrompt: "A wet street at night." } });
  linked(g);
  const start = Object.values(g).find((n) => n.class_type === "PaintAPlate_CompositeFrames"); // stage 2's start, made one frame at a time
  assert.match(start._meta.title, /Stage 1 inside the blocks, the plate around them/);
  assert.equal(g[start.inputs.source[0]].class_type, "VAEDecode", "stage 1's frames reach stage 2 by link");
  assert.deepEqual([start.inputs.width, start.inputs.height], plate.work, "stage 2 starts at the working size");
  const scaled = Object.values(g).filter((n) => n._meta.title.startsWith("CLEAN PLATE PASS · stage 1 at 640 x 352") && n.class_type === "ImageScale" && n.inputs.width === 640);
  assert.equal(scaled.length, 1, "stage 1 runs at half of 1280 x 704");
  const sigmas = Object.values(g).filter((n) => n.class_type === "ManualSigmas").map((n) => n.inputs.sigmas).sort();
  assert.deepEqual(sigmas, ["0.725, 0.421875, 0.0", "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"]);
  assert.equal(Object.values(g).filter((n) => n.class_type === "CLIPTextEncode" && n.inputs.text === "A wet street at night.").length, 1);
});

test("the graph reads by sections: numbered ids, a README note opening each, the section and the values set in every title", () => {
  const g = sceneGraph(WF, { plate, edits: [{ ...edit("erase", 1), words: "red umbrella" }, edit("paint", 2), edit("light", 3)], render,
    about: { version: "1.0.0", name: "shot" } });
  linked(g);
  const ids = Object.keys(g), notes = Object.entries(g).filter(([, n]) => n.class_type === "PrimitiveStringMultiline");
  assert.ok(ids.every((id) => /^[1-9]\d*$/.test(id)), "numeric ids");
  assert.deepEqual(notes.map(([id, n]) => [Number(id) % 100, n._meta.title]).slice(0, 4),
    [[0, "README · How this graph works"], [0, "README · INPUT"], [0, "README · MODELS"], [0, 'README · EDIT 1 · Clean "red umbrella"']]);
  assert.deepEqual(notes.map(([, n]) => n._meta.title).slice(4),
    ["README · EDIT 2 · Paint", "README · EDIT 3 · Light", "README · OBJECT TRACKING", "README · CLEAN PLATE PASS", "README · SHOT", "README · PAINT TRACKING", "README · OUTPUT"]);
  const read = new Set(Object.values(g).flatMap((n) => Object.values(n.inputs).filter(Array.isArray).map((v) => v[0])));
  assert.ok(notes.every(([id]) => !read.has(id)), "no node reads a README note, so none runs");
  let section = "";
  for (const [id, n] of Object.entries(g)) { // in id order, every node sits under the README of its own section
    if (n.class_type === "PrimitiveStringMultiline") { section = n._meta.title.slice("README · ".length); continue; }
    assert.ok(n._meta.title.startsWith(`${section} · `), `${id}: ${n._meta.title} under ${section}`);
  }
  const overview = g[notes[0][0]].inputs.value;
  for (const s of ["AInVFX Paint a plate 1.0.0", "plates/shot.mp4", "output/paintaplate/x/graph/export", 'Edit 1: Clean "red umbrella", seed 1.'])
    assert.ok(overview.includes(s), s);
  const titled = (cls) => Object.values(g).filter((n) => n.class_type === cls).map((n) => n._meta.title);
  assert.ok(titled("UNETLoader").every((t) => t.startsWith("MODELS · UNETLoader · ")), "a loader serves every step, from MODELS");
  assert.ok(titled("CLIPTextEncode").some((t) => t.startsWith("SHOT · ") && t.endsWith("[prompt]")), "the shot's prompt is named");
  assert.ok(titled("CLIPTextEncode").some((t) => t === 'EDIT 1 · Clean "red umbrella" · both passes · Caption [caption]'), "an edit's caption, one node for its two passes");
});

// ---------- The page workstream, wave 3: the scene in the editor's own format ----------
import { editorGraph, widgetsOf } from "../../web/graph.mjs";

const INFO = JSON.parse(readFileSync(new URL("./object_info.scene.json", import.meta.url))).nodes; // what /object_info says: tests/js/object_info.scene.json
const WF_HDR = { ...WF, hdr: parseWorkflow(JSON.parse(readFileSync(new URL("../../web/workflows/hdr.json", import.meta.url)))) };
const scene = (hdr = false) => sceneGraph(WF_HDR, { plate: { ...plate, fps: 24 }, edits: [edit("erase", 1), edit("paint", 2), edit("light", 3)], render: { ...render, hdr }, about: { version: "1.11.9", name: "shot" } });
const rect = (n) => [n.pos[0], n.pos[1] - 30, n.pos[0] + n.size[0], n.pos[1] + n.size[1]]; // with its title bar
const cut = (a, b) => Math.min(a[2], b[2]) > Math.max(a[0], b[0]) && Math.min(a[3], b[3]) > Math.max(a[1], b[1]);
const inside = (a, b) => a[0] <= b[0] && a[1] <= b[1] && a[2] >= b[2] && a[3] >= b[3];
const box = (g) => [g.bounding[0], g.bounding[1], g.bounding[0] + g.bounding[2], g.bounding[1] + g.bounding[3]];

function posted(file) { // what the editor's Run posts: a widget's value by its name, a link by its input's name; a note is no node of a prompt
  const link = new Map(file.links.map((l) => [l[0], l])), out = {};
  for (const n of file.nodes) {
    if (n.type === "MarkdownNote") continue;
    const inputs = {};
    widgetsOf(INFO[n.type]).forEach((w, i) => { if (w.name !== undefined) inputs[w.name] = n.widgets_values[i]; });
    for (const i of n.inputs) if (i.link !== null) inputs[i.name] = [String(link.get(i.link)[1]), link.get(i.link)[2]];
    out[n.id] = { class_type: n.type, inputs };
  }
  return out;
}

test("the editor's format: one group per section in run order, a note at the head of each, every node of the scene", () => {
  const api = scene(), file = editorGraph(api, INFO);
  assert.equal(file.version, 0.4);
  const readmes = Object.values(api).filter((n) => n.class_type === "PrimitiveStringMultiline");
  assert.deepEqual(file.groups.map((g) => g.title), ["README", ...readmes.slice(1).map((n) => n._meta.title.slice(9))]);
  assert.deepEqual(file.groups.map((g) => g.title).filter((t) => !t.startsWith("EDIT ")), ["README", "INPUT", "MODELS", "OBJECT TRACKING", "CLEAN PLATE PASS", "SHOT", "PAINT TRACKING", "OUTPUT"]);
  const notes = file.nodes.filter((n) => n.type === "MarkdownNote");
  assert.equal(notes.length, file.groups.length);
  const held = file.nodes.filter((n) => !api[n.id]); // the editor's own String (Multiline) nodes: one per text of a widget that declares dynamicPrompts
  assert.ok(held.length && held.every((n) => n.type === "PrimitiveStringMultiline"));
  assert.equal(file.nodes.length - held.length, Object.keys(api).length); // each README is a note, every other node is itself
  assert.ok(file.nodes.every((n) => !api[n.id] || n.type === "MarkdownNote" || (n.type === api[n.id].class_type && n.title === api[n.id]._meta.title)), "the titles are kept");
  assert.match(notes[0].widgets_values[0], /AInVFX Paint a plate 1\.11\.9: the scene of shot/);
  const edit1 = notes.find((n) => n.title === "README · EDIT 1 · Clean").widgets_values[0];
  assert.match(edit1, /\*\*Values the page set\*\*/);
  assert.match(edit1, /- both passes · Caption: text "erase caption"/); // the note names the value, the node's title its slot
  assert.equal(file.last_node_id, Math.max(...file.nodes.map((n) => n.id)));
});

for (const hdr of [false, true]) test(`the editor's format${hdr ? ", with SDR to HDR" : ""}: no node over another, every node inside its group, and in a group the links run from left to right`, () => {
  const api = scene(hdr), file = editorGraph(api, INFO), groups = file.groups.map(box);
  assert.equal(file.groups.some((g) => g.title === "SDR TO HDR"), hdr);
  const home = (n) => groups.findIndex((g) => inside(g, rect(n)));
  for (let i = 0; i < file.nodes.length; i++) {
    assert.ok(home(file.nodes[i]) >= 0, `${file.nodes[i].title} lies in a group`);
    for (let j = i + 1; j < file.nodes.length; j++) assert.ok(!cut(rect(file.nodes[i]), rect(file.nodes[j])), `${file.nodes[i].title} over ${file.nodes[j].title}`);
  }
  for (let i = 1; i < groups.length; i++) assert.ok(groups[i][1] > groups[i - 1][3], "the groups follow each other from top to bottom, apart");
  const byId = new Map(file.nodes.map((n) => [n.id, n]));
  for (const n of file.nodes.filter((x) => x.type === "MarkdownNote")) // the note is the first thing of its group, at its left
    assert.ok(file.nodes.every((o) => o === n || home(o) !== home(n) || o.pos[0] > n.pos[0] + n.size[0]), `${n.title} opens its group`);
  for (const [, from, , to] of file.links) if (home(byId.get(from)) === home(byId.get(to)))
    assert.ok(byId.get(from).pos[0] + byId.get(from).size[0] < byId.get(to).pos[0], `${byId.get(from).title} feeds ${byId.get(to).title} from its left`);
});

for (const hdr of [false, true]) test(`the editor's format${hdr ? ", with SDR to HDR" : ""}: the links are whole, and Run posts the nodes of the API graph, value for value`, () => {
  const api = scene(hdr), file = editorGraph(api, INFO), byId = new Map(file.nodes.map((n) => [n.id, n]));
  assert.equal(file.last_link_id, file.links.length);
  for (const [id, from, slot, to, input, type] of file.links) {
    assert.ok(byId.get(from).outputs[slot].links.includes(id), `link ${id} leaves ${byId.get(from).title}`);
    assert.equal(byId.get(to).inputs[input].link, id, `link ${id} enters ${byId.get(to).title}`);
    assert.equal(byId.get(from).outputs[slot].type, type);
  }
  const back = posted(file), extra = new Set();
  for (const [id, n] of Object.entries(back)) if (!api[id]) { // a text that the editor holds reaches the input it feeds as it is
    assert.equal(n.class_type, "PrimitiveStringMultiline");
    for (const m of Object.values(back)) for (const [k, v] of Object.entries(m.inputs)) if (Array.isArray(v) && String(v[0]) === id) m.inputs[k] = n.inputs.value;
    delete back[id];
  }
  for (const [id, n] of Object.entries(api)) {
    if (n.class_type === "PrimitiveStringMultiline") { assert.equal(back[id], undefined); continue; }
    assert.equal(back[id].class_type, n.class_type);
    for (const [k, v] of Object.entries(n.inputs)) assert.deepEqual(back[id].inputs[k], v, `${n._meta.title}: ${k}`);
    for (const k of Object.keys(back[id].inputs)) if (!(k in n.inputs)) extra.add(`${n.class_type}.${k}`);
  }
  // the editor also posts the optional inputs the API graph leaves to the node, at their default: these, and no other
  const LEFT = ["PaintAPlate_LivePreview.transfer", "PaintAPlate_RelightTransfer.shade_density", "PaintAPlate_SaveFrames.format", "PaintAPlate_SaveFrames.fps", "PaintAPlate_SaveMovie.config", "PaintAPlate_SaveMovie.crf",
    "PaintAPlate_SaveMovie.destination", "PaintAPlate_SaveMovie.frames", "PaintAPlate_SaveMovie.largest_size", "PaintAPlate_SaveMovie.source"];
  assert.deepEqual([...extra].filter((k) => !LEFT.includes(k)), []);
});

test("a node's widgets: a seed keeps its control, an image upload its button, a widget a link feeds keeps its place", () => {
  assert.deepEqual(widgetsOf(INFO.KSampler).map((w) => w.name ?? w.value), ["seed", "fixed", "steps", "cfg", "sampler_name", "scheduler", "denoise"]);
  assert.deepEqual(widgetsOf(INFO.RandomNoise).map((w) => w.name ?? w.value), ["noise_seed", "fixed"]);
  assert.deepEqual(widgetsOf(INFO.LoadImage).map((w) => w.name ?? w.value), ["image", "image"]); // the file, then the upload button
  assert.deepEqual(widgetsOf(INFO.LoadImageMask).map((w) => w.name ?? w.value), ["image", "channel", "image"]); // the button comes after the required inputs
  const dynamic = { input: { required: { video: ["VIDEO", {}], filename_prefix: ["STRING", {}], format: ["COMFY_DYNAMICCOMBO_V3", {}] } } }; // a V3 combo that brings an input of its own
  assert.deepEqual(widgetsOf(dynamic, { filename_prefix: "v", format: "mp4", "format.codec": "h264" }).map((w) => w.name ?? w.value), ["filename_prefix", "format", "format.codec"]);
  const api = scene(), file = editorGraph(api, INFO);
  const linked = file.nodes.find((n) => n.type === "ImageScale" && n.inputs.some((i) => i.widget)); // its width comes by link
  assert.ok(linked && linked.widgets_values.length === 4 && linked.inputs.filter((i) => i.widget).every((i) => i.link !== null), "a linked widget keeps a value in its place, and its link");
  assert.throws(() => editorGraph(api, { ...INFO, KSamplerSelect: undefined }), /ComfyUI does not know the node KSamplerSelect/);
});
