// Finish's graph (graph.finishGraph): each job as the page posted it, value for value, its paths under the graphs' folder
// (graphPath), and each file a job reads behind an order gate that waits for the images the job before it saved.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { fillWorkflow, parseWorkflow } from "../../web/logic.mjs";
import { editorGraph, finishGraph, graphPath } from "../../web/graph.mjs";

const read = (f) => readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
const WF = Object.fromEntries(["hdr", "hdr_comp", "upscale", "upscale_export"].map((n) => [n, parseWorkflow(JSON.parse(read(`web/workflows/${n}.json`)))]));
const INFO = JSON.parse(read("tests/js/object_info.scene.json")).nodes;
const FOLDER = "paintaplate/ab12/graph", HOME = "paintaplate/ab12/upscale/0a1b2c3d", OUT = "paintaplate/ab12/v1/hdr/upscale/1024x640/out";
const READERS = { PaintAPlate_LoadPlate: "path", PaintAPlate_JoinWindows: "folder" };
const window = (i) => ({ name: "upscale", step: "upplate", label: "Plate, HDR, upscaled", values: { shot: "output:paintaplate/ab12/v1/hdr/plate", max_frames: 17,
  resize_method: "bicubic", first: 8 * i, count: 9, width: 1024, height: 640, color_space: "ACES2065-1", color_fix: "lab", format: "exr", seed: 42, config: "ocio://x",
  under: "", under_space: "ACES2065-1", matte: "", comp_prefix: "", matte_prefix: "", share: 0, chunk_frames: 9, chunk_overlap: 1, prefix: `${HOME}/w00${i}/f` } });
const JOBS = [
  { name: "hdr", step: "hdr", label: "Plate, HDR", values: { path: "plates/desk.mp4", color_space: "sRGB", config: "ocio://x", max_frames: 17, width: 512, height: 320,
    plate_width: 512, plate_height: 320, fps: 24, cond_fps: 24, prefix: "paintaplate/ab12/v1/hdr/plate/f", video_prefix: "paintaplate/ab12/v1/hdr/plate_movie", view_space: "ACEScct", movie_fps: 24 } },
  window(0), window(1),
  { name: "upscale_export", step: "upplate", label: "Plate, HDR, upscaled", values: { shot: "output:paintaplate/ab12/v1/hdr/plate", frames: `output:${HOME}`, max_frames: 17,
    prefix: `${OUT}/plate`, counts: "9,9", share: 1, config: "ocio://x", color_space: "ACES2065-1", movie_space: "ACEScct", video_prefix: "paintaplate/ab12/v1/hdr/upscale/1024x640/movie/plate" } },
];
const graph = () => finishGraph(WF, { jobs: JOBS, folder: FOLDER, about: { name: "desk" } });
const ofJob = (g, k) => Object.entries(g).filter(([, n]) => n._meta.title.includes(` · job ${k} · `) && !n._meta.title.includes("order gate"));

test("a path of a render's folder, or of a Finish folder a plate's renders share, moves under the graphs' folder; others stay", () => {
  assert.equal(graphPath("output:paintaplate/ab12/v3/hdr/plate", FOLDER), "output:paintaplate/ab12/graph/hdr/plate");
  assert.equal(graphPath(`${HOME}/w000/f`, FOLDER), "paintaplate/ab12/graph/upscale/0a1b2c3d/w000/f");
  assert.equal(graphPath("output:paintaplate/zz99/v12/export/desk.mov", FOLDER), "output:paintaplate/ab12/graph/export/desk.mov", "a job taken from the index keeps its own folder");
  for (const v of ["plates/desk.mp4", "paintaplate/up/1a2b.png", "lab", 42]) assert.equal(graphPath(v, FOLDER), v);
});

test("every job of the page is in the graph value for value, its paths moved; nothing else is, but the order gates", () => {
  const g = graph(), sign = (n, gated) => `${n.class_type} ${JSON.stringify(Object.entries(n.inputs).sort().map(([k, v]) =>
    [k, Array.isArray(v) || (gated && READERS[n.class_type] === k) ? "link" : v]))}`;
  const want = new Set(JOBS.flatMap((job, k) => Object.values(fillWorkflow(WF[job.name], Object.fromEntries(Object.entries(job.values).map(([key, v]) => [key, graphPath(v, FOLDER)])))
    .prompt).map((n) => sign(n, k > 0))));
  const have = new Set(Object.values(g).filter((n) => n.class_type !== "PrimitiveStringMultiline" && !n._meta.title.includes("order gate")).map((n) => sign(n, false)));
  assert.deepEqual([...have].sort(), [...want].sort());
});

test("each file a job reads waits behind a gate for every image the job before it saved; the first job's files need none", () => {
  const g = graph(), byId = (link) => g[link[0]];
  for (const [, n] of ofJob(g, 1)) if (READERS[n.class_type]) assert.equal(typeof n.inputs[READERS[n.class_type]], "string", "the first job reads its files at once");
  for (let k = 2; k <= JOBS.length; k++) {
    const saved = ofJob(g, k - 1).filter(([, n]) => n.class_type.startsWith("PaintAPlate_Save")).map(([, n]) => JSON.stringify(n.inputs.images)).sort();
    const readers = ofJob(g, k).filter(([, n]) => READERS[n.class_type]);
    assert.ok(readers.length && saved.length, `job ${k}: readers and the saves before them`);
    for (const [, n] of readers) {
      const sw = byId(n.inputs[READERS[n.class_type]]), math = byId(sw.inputs.switch), value = byId(sw.inputs.on_true);
      assert.equal(sw.class_type, "ComfySwitchNode");
      assert.deepEqual(sw.inputs.on_false, sw.inputs.on_true, "the same value either way: the gate changes when, never what");
      assert.equal(value.class_type, "PrimitiveString");
      assert.equal(math.class_type, "ComfyMathExpression");
      const sizes = Object.entries(math.inputs).filter(([key]) => key.startsWith("values.")).map(([, link]) => byId(link));
      assert.ok(sizes.every((s) => s.class_type === "GetImageSize"));
      assert.deepEqual(sizes.map((s) => JSON.stringify(s.inputs.image)).sort(), saved, `job ${k} waits for each image job ${k - 1} saved`);
      assert.equal(math.inputs.expression, sizes.length > 1 ? `min(${"abcdefghijklmnopqrstuvwxyz".slice(0, sizes.length).split("").join(", ")}) > 0` : "a > 0");
    }
  }
  const join = ofJob(g, JOBS.length).find(([, n]) => n.class_type === "PaintAPlate_JoinWindows")[1];
  assert.equal(byId(byId(join.inputs.folder).inputs.on_true).inputs.value, `output:${FOLDER}/upscale/0a1b2c3d`, "the join reads the windows where they are written");
});

test("the editor's format takes Finish's graph, and its README says what runs, in which order, and why the gates", () => {
  const g = graph(), editor = editorGraph(g, INFO);
  assert.ok(editor.nodes.length > Object.keys(g).length - 10, "every node is described");
  const readme = Object.values(g).find((n) => n._meta.title === "README · How this graph works").inputs.value;
  assert.ok(readme.includes("Plate, HDR, then Plate, HDR, upscaled") && readme.includes(`output/${FOLDER}`) && readme.includes("If/Else Switch"), readme);
});
