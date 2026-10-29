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
  const node = (title) => Object.entries(g).find(([, n]) => n._meta.title.endsWith(title));
  const [, up] = node("Stage 1 at full size");
  assert.equal(g[up.inputs.image[0]].class_type, "VAEDecode", "stage 1's frames reach stage 2 by link");
  assert.equal(up.inputs.width[0] !== undefined ? g[up.inputs.width[0]].class_type : "", "GetImageSize");
  const scaled = Object.values(g).filter((n) => n._meta.title.startsWith("erase pass at half size") && n.class_type === "ImageScale" && n.inputs.width === 640);
  assert.equal(scaled.length, 1, "stage 1 runs at half of 1280 x 704");
  const sigmas = Object.values(g).filter((n) => n.class_type === "ManualSigmas").map((n) => n.inputs.sigmas).sort();
  assert.deepEqual(sigmas, ["0.725, 0.421875, 0.0", "1.0, 0.99375, 0.9875, 0.98125, 0.975, 0.909375, 0.725, 0.421875, 0.0"]);
  assert.equal(Object.values(g).filter((n) => n.class_type === "CLIPTextEncode" && n.inputs.text === "A wet street at night.").length, 1);
});
