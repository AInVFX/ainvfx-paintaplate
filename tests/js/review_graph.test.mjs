import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { parseWorkflow } from "../../web/logic.mjs";
import { editorGraph, sceneGraph } from "../../web/graph.mjs";

// The saved graph renders as Export does: Save Plate writes the result in the export's format (logic.exportFormat), and
// the graph's notes say which.
const WF = Object.fromEntries(["edit", "matte", "clean", "cleanup", "shot", "export", "hdr"].map((n) =>
  [n, parseWorkflow(JSON.parse(readFileSync(new URL(`../../web/workflows/${n}.json`, import.meta.url))))]));
const INFO = JSON.parse(readFileSync(new URL("./object_info.scene.json", import.meta.url))).nodes;
const plate = { path: "plates/shot.mp4", config: "ocio://studio-config-latest", cs: "sRGB Encoded Rec.709 (sRGB)", frames: 121, fps: 24,
  work: [1280, 704], prev: [768, 416], track: [960, 528], trackErase: [640, 352] };
const pass = { steps: 8, denoise: 1, grow: 16, feather: 6, sigma: 3 };
const edit = (tool, k) => ({ tool, seed: k, caption: `${tool} caption`, mask: `m${k}.png`, layer: tool === "erase" ? null : `l${k}.png`, quick: pass, full: pass });
const scene = (extra) => sceneGraph(WF, { plate, edits: [edit("erase", 1), edit("paint", 2)],
  render: { prompt: "Ripple", seed: 1, grow: 53, feather: 13, prefix: "paintaplate/x/graph", format: "ProRes 4444 XQ", ...extra }, about: { name: "shot" } });
const written = (g) => Object.values(g).filter((n) => n._meta.title.startsWith("OUTPUT · ") && n.class_type.startsWith("PaintAPlate_Save"))
  .map((n) => [n.class_type, n.inputs.filename_prefix]).sort();
const note = (g, name) => Object.values(g).find((n) => n._meta.title === `README · ${name}`)?.inputs.value ?? "";

test("the saved graph writes what Export writes, and its notes name the format", () => {
  const own = [["PaintAPlate_SaveFrames", "paintaplate/x/graph/matte/matte"], ["PaintAPlate_SavePlate", "paintaplate/x/graph/export"]];
  const sdr = scene({}), hdr = scene({ hdr: true });
  assert.deepEqual(written(sdr), own, "no SDR to HDR: Save Plate, and the matte");
  assert.deepEqual(written(hdr), own, "a plate that holds values above 1.0 keeps its own format");
  assert.equal(note(sdr, "SDR TO HDR"), "", "no SDR to HDR, no section");
  assert.doesNotMatch(note(hdr, "SDR TO HDR"), /EXR/);
  assert.match(note(hdr, "OUTPUT"), /Save Plate writes the result to output\/paintaplate\/x\/graph\/export as ProRes 4444 XQ/);
  assert.match(note(sdr, "How this graph works"), /It writes the result as ProRes 4444 XQ to output\/paintaplate\/x\/graph\/export/);
  assert.ok(editorGraph(hdr, INFO).nodes.length > 0, "the editor's format takes it: ComfyUI describes every node");
});
