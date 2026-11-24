// The scene's ComfyUI graph posts the paint matte as the page does: the strategy the paints share, and the name request
// made from their words.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { nameRequest, parseWorkflow } from "../../web/logic.mjs";
import { sceneGraph } from "../../web/graph.mjs";

const WF = Object.fromEntries(["edit", "matte", "clean", "cleanup", "shot", "export", "fluid", "hdr"].map((n) =>
  [n, parseWorkflow(JSON.parse(readFileSync(new URL(`../../web/workflows/${n}.json`, import.meta.url))))]));
const plate = { path: "plates/shot.mp4", config: "ocio://studio-config-latest", cs: "sRGB Encoded Rec.709 (sRGB)", frames: 121, work: [1280, 704], prev: [768, 416], track: [960, 528], trackErase: [640, 352] };
const pass = { steps: 8, denoise: 1, grow: 16, feather: 6, sigma: 3 };
const render = { prompt: "Ripple", seed: 1, grow: 53, feather: 13, prefix: "paintaplate/x/graph" };
const edit = (tool, k, more = {}) => ({ tool, seed: k, caption: `${tool} caption`, mask: `m${k}.png`, layer: tool === "erase" ? null : `l${k}.png`, quick: pass, full: pass, ...more });
const nodes = (g, cls) => Object.values(g).filter((n) => n.class_type === cls);

test("the scene graph's paint matte runs the widest strategy of its paints, and names what they painted", () => {
  const g = sceneGraph(WF, { plate, render, edits: [edit("paint", 1, { words: "a red fire", matte: "Object" }), edit("paint", 2, { words: "smoke", matte: "Whole shot" }), edit("light", 3)] });
  assert.deepEqual(nodes(g, "PaintAPlate_FollowMatte").map((n) => n.inputs.strategy), ["Whole shot"]);
  assert.ok(nodes(g, "TextGenerate").some((n) => n.inputs.prompt === nameRequest("paint", ["a red fire", "smoke"])));
});

test("a paint with no strategy, as in an older scene, runs Auto in the graph", () => {
  const g = sceneGraph(WF, { plate, render, edits: [edit("paint", 1, { words: "a red fire" })] });
  assert.deepEqual(nodes(g, "PaintAPlate_FollowMatte").map((n) => n.inputs.strategy), ["Auto"]);
});
