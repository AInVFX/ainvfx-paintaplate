// The scene's ComfyUI graphs as a list (logic.graphRows, graph.orderText): each graph's row in the zip and its label in the
// download's lines, and the sentences of its README on the graphs around it, for one, two and three graphs. The fluid
// shot's graph and the edits' graph carry those sentences, and the edits' graph reads the file the fluid shot's writes.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { graphImageName, graphRows, parseWorkflow } from "../../web/logic.mjs";
import { fluidGraph, orderText, sceneGraph } from "../../web/graph.mjs";

const read = (f) => readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
const WF = Object.fromEntries(["edit", "matte", "clean", "cleanup", "shot", "export", "hdr", "fluid"].map((n) => [n, parseWorkflow(JSON.parse(read(`web/workflows/${n}.json`)))]));
const FILES = ["desk_fluid_shot_comfyui_graph.json", "desk_edits_comfyui_graph.json", "desk_finish_comfyui_graph.json"];
const WRITES = [{ what: "the fluid shot", path: "output:paintaplate/7/graph/plate/blank.mov" }, { what: "the composite", path: "output:paintaplate/7/graph/export" }, {}];
const list = (n) => FILES.slice(0, n).map((file, i) => ({ file, ...WRITES[i] }));
const readme = (api) => Object.values(api).find((n) => n._meta.title === "README · How this graph works").inputs.value;

test("one graph keeps the row comfyui_graph; several are named after what each makes, and their labels give the order", () => {
  assert.deepEqual(graphRows(["edits"]), [{ kind: "edits", row: "comfyui_graph", label: "ComfyUI graph" }]);
  assert.deepEqual(graphRows(["fluid_shot", "edits"]).map((x) => [x.row, x.label]),
    [["fluid_shot_comfyui_graph", "ComfyUI graph 1 of 2, fluid shot"], ["edits_comfyui_graph", "ComfyUI graph 2 of 2, edits"]]);
  assert.deepEqual(graphRows(["fluid_shot", "edits", "finish"]).map((x) => [x.row, x.label]), [["fluid_shot_comfyui_graph", "ComfyUI graph 1 of 3, fluid shot"],
    ["edits_comfyui_graph", "ComfyUI graph 2 of 3, edits"], ["finish_comfyui_graph", "ComfyUI graph 3 of 3, Finish"]]);
});

test("each README says what to run before its graph and after it, read from the list's neighbours", () => {
  assert.equal(orderText(list(1), 0), "", "one graph: nothing before it, nothing after it");
  const first = "Then run desk_edits_comfyui_graph.json. It reads the fluid shot, which this graph writes.";
  const second = "First run desk_fluid_shot_comfyui_graph.json. It writes the fluid shot, output:paintaplate/7/graph/plate/blank.mov, which this graph reads.";
  assert.deepEqual([0, 1].map((at) => orderText(list(2), at)), [first, second]);
  assert.deepEqual([0, 1, 2].map((at) => orderText(list(3), at)), [first,
    `${second} Then run desk_finish_comfyui_graph.json. It reads the composite, which this graph writes.`,
    "First run desk_edits_comfyui_graph.json. It writes the composite, output:paintaplate/7/graph/export, which this graph reads."]);
});

test("the fluid shot's graph and the edits' graph carry those sentences; the edits' graph reads the fluid shot the first one writes", () => {
  const plate = { path: "output:paintaplate/7/graph/plate/blank.mov", config: "ocio://studio-config-latest", cs: "sRGB Encoded Rec.709 (sRGB)", frames: 17, fps: 24,
    work: [512, 320], prev: [512, 320], track: [512, 320], trackErase: [512, 320], size: [512, 320] };
  const pass = { steps: 8, denoise: 1, grow: 16, feather: 6, sigma: 3 };
  const fluid = fluidGraph(WF, { chain: { list: list(2), at: 0 }, plate: { ...plate, path: "plates/blank.mov" },
    fluid: { keys: [{ frame: 0, image: graphImageName("desk", 1, "keyframe", "1".repeat(32)) }], prompt: "smoke", seed: 3, hdr: false, prefix: "paintaplate/7/graph" } });
  const edits = sceneGraph(WF, { chain: { list: list(2), at: 1 }, plate, edits: [{ tool: "paint", seed: 1, caption: "c", words: "a red ball", quick: pass, full: pass,
    mask: graphImageName("desk", 1, "mask", "2".repeat(32)), layer: graphImageName("desk", 1, "strokes", "3".repeat(32)) }],
    render: { format: "ProRes 4444 XQ", prompt: "Ripple", seed: 1, grow: 20, feather: 6, prefix: "paintaplate/7/graph" } });
  assert.ok(readme(fluid).includes(orderText(list(2), 0)) && !readme(fluid).includes("First run"), readme(fluid));
  assert.ok(readme(edits).includes(orderText(list(2), 1)) && !readme(edits).includes("Then run"), readme(edits));
  assert.ok(!readme(edits).includes("the plate to the same path"), "the plate comes from the graph before: no copy of it to make");
  const saved = Object.values(fluid).find((n) => n.class_type === "PaintAPlate_SavePlate").inputs.filename_prefix;
  const loaded = Object.values(edits).find((n) => n.class_type === "PaintAPlate_LoadPlate").inputs.path;
  assert.equal(`output:${saved}/blank.mov`, loaded, "Save Plate names the movie after the blank plate, in the folder its prefix names");
  const first = Object.values(fluid).find((n) => n.class_type === "SaveImage").inputs.filename_prefix;
  assert.ok(first.startsWith("paintaplate/7/graph/"), `the first frame stays under the graphs' folder: ${first}`);
});
