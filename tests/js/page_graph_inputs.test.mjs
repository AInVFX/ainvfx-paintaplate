// Tests of what a scene's ComfyUI graph needs on disk (graph.sceneGraph, logic.graphImageName).
// ComfyUI's editor (frontend 1.59) marks a core image loader's file as missing when the file is not in the loader's list as the
// editor read it when it opened (ComfyUI_frontend, missingMediaScan.ts). Paint a plate uploads a graph's images when it saves
// the graph, often after the editor opened, so the graph reads each image by its name with Load Plate, whose path is no list.
// The images stay at the top of the input folder, where the README says they must be.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { graphImageName, parseWorkflow } from "../../web/logic.mjs";
import { sceneGraph } from "../../web/graph.mjs";

const load = (n) => parseWorkflow(JSON.parse(readFileSync(new URL(`../../web/workflows/${n}.json`, import.meta.url))));
const WF = Object.fromEntries(["edit", "matte", "clean", "cleanup", "shot", "export"].map((n) => [n, load(n)]));
const pass = { steps: 8, denoise: 1, grow: 16, feather: 6, sigma: 3 };
const plate = { path: "plates/horse.mp4", config: "ocio://studio-config-latest", cs: "sRGB Encoded Rec.709 (sRGB)", frames: 121, fps: 24,
  work: [1280, 704], prev: [768, 416], track: [960, 528], trackErase: [640, 352] };
const render = { prompt: "Ripple", seed: 1, grow: 53, feather: 13, prefix: "paintaplate/x/graph" };
const image = (k, kind) => graphImageName("horse", k, kind, `${k}${kind}`.padEnd(32, "0"));
const edit = (tool, k) => ({ tool, seed: k, caption: `${tool} caption`, quick: pass, full: pass, mask: image(k, "mask"),
  layer: tool === "paint" ? image(k, "strokes") : null });

test("an image of the graph is named after the plate, the edit and what it holds, and sits at the top of the input folder", () => {
  assert.equal(graphImageName("horse", 1, "mask", "a64a59080b03a6baa8d9aaef75719cfc"), "horse_e1_mask_a64a5908.png");
  assert.equal(graphImageName("my plate.v2", 2, "strokes", "4d19b271e717"), "my_plate_v2_e2_strokes_4d19b271.png");
  assert.equal(graphImageName("shots/a b", 3, "strokes", "0123456789"), "shots_a_b_e3_strokes_01234567.png");
});

test("every image is read by its name at the top of the input folder, by no core loader, and the README names each file", () => {
  const edits = [edit("erase", 1), edit("paint", 2), edit("light", 3)];
  const api = sceneGraph(WF, { plate, edits, render, about: { version: "1.11.13", name: "horse" } });
  assert.ok(Object.values(api).every((n) => !["LoadImage", "LoadImageMask"].includes(n.class_type)), "no core image loader");
  const read = Object.values(api).filter((n) => n.class_type === "PaintAPlate_LoadPlate" && n.inputs.path !== plate.path).map((n) => n.inputs.path);
  const files = edits.flatMap((e) => [e.mask, e.layer].filter(Boolean));
  assert.deepEqual([...new Set(read)].sort(), [...files].sort());
  assert.ok(read.every((name) => !name.includes("/")), `no image in a subfolder of input: ${read}`);
  const readme = Object.values(Object.values(api).find((n) => n.class_type === "PrimitiveStringMultiline").inputs).find((v) => typeof v === "string");
  const must = readme.split("\n\n").find((p) => p.startsWith("To run it"));
  assert.ok(must.includes("must be in ComfyUI's input folder") && must.includes(plate.path) && files.every((f) => must.includes(f)), must);
});
