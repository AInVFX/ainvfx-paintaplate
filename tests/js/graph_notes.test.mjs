// The graph's notes are true, and stay true (graph.sceneGraph, graph.fluidGraph). A note that names a section, a node by its
// display name, a marked value, a file or a word of the page in « » names one that its graph, or the page, has.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { graphImageName, parseWorkflow } from "../../web/logic.mjs";
import { fluidGraph, sceneGraph } from "../../web/graph.mjs";

const read = (f) => readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
const load = (n) => parseWorkflow(JSON.parse(read(`web/workflows/${n}.json`)));
const WF = Object.fromEntries(["edit", "matte", "clean", "cleanup", "shot", "export", "hdr", "fluid"].map((n) => [n, load(n)]));
const PAGE = read("web/paintaplate.html") + read("web/app.mjs"); // the words a person reads on the page
const NODES = [...new Map([...read("nodes.py").matchAll(/node_id="(PaintAPlate_\w+)",\s*display_name="([^"]+)"/g)] // a node's display name, with and without
  .flatMap(([, cls, name]) => [[name, cls], [name.replace(/ \(.*\)$/, ""), cls]]))]; // its note in brackets, each once
const SECTIONS = [...new Set([...read("web/graph.mjs").matchAll(/\["\w+", "([A-Z][A-Z0-9 ]*[A-Z0-9])"/g)].map((m) => m[1]))] // every section a graph opens
  .sort((a, b) => b.length - a.length); // the longest first: SHOT is not read inside FLUID SHOT

// What a graph's notes name that the graph or the page does not have
export function stale(api) {
  const nodes = Object.values(api), titles = nodes.map((n) => n._meta.title);
  const sections = new Set(titles.map((t) => t.split(" · ")[0]));
  const marks = new Set(titles.flatMap((t) => (t.match(/\[([^\]]+)\]$/)?.[1] ?? "").split(", ")));
  const classes = new Set(nodes.map((n) => n.class_type));
  const files = new Set(nodes.flatMap((n) => [n.inputs?.image, ...(n.class_type === "PaintAPlate_KeyframeVideo" ? JSON.parse(n.inputs.keys || "[]").map((k) => k.image) : [])]));
  const problems = [];
  for (const n of nodes.filter((x) => x.class_type === "PrimitiveStringMultiline")) {
    let text = Object.values(n.inputs).find((v) => typeof v === "string");
    const say = (what) => problems.push(`${n._meta.title}: ${what}`);
    for (const m of text.matchAll(/\bEDIT (\d+)\b/g)) if (!sections.has(`EDIT ${m[1]}`)) say(`section EDIT ${m[1]}`);
    for (const s of SECTIONS) {
      const at = new RegExp(`(?<![A-Za-z])${s}(?![A-Za-z])`, "g");
      if (at.test(text) && !sections.has(s)) say(`section ${s}`);
      text = text.replace(at, ""); // read once: a shorter section inside it is not named
    }
    const all = Object.values(n.inputs).find((v) => typeof v === "string");
    for (const [name, cls] of NODES) if (new RegExp(`(?<![A-Za-z])${name.replace(/[()]/g, "\\$&")}(?![A-Za-z])`).test(all) && !classes.has(cls)) say(`node ${name}`);
    for (const m of all.matchAll(/\[([a-z_ ]+)\]/g)) if (!marks.has(m[1])) say(`mark [${m[1]}]`);
    for (const f of all.match(/[\w.-]+\.png/g) ?? []) if (!files.has(f)) say(`file ${f}`);
    for (const m of all.matchAll(/«\s*([^»]+?)\s*»/g)) if (!PAGE.includes(m[1])) say(`the page's « ${m[1]} »`);
  }
  return problems;
}

const pass = { steps: 8, denoise: 1, grow: 16, feather: 6, sigma: 3 };
const plate = { path: "plates/horse.mp4", config: "ocio://studio-config-latest", cs: "sRGB Encoded Rec.709 (sRGB)", frames: 121, fps: 24,
  work: [1280, 704], prev: [768, 416], track: [960, 528], trackErase: [640, 352] };
const render = { format: "ProRes 4444 XQ", prompt: "Ripple", seed: 1, grow: 53, feather: 13, prefix: "paintaplate/x/graph" };
const image = (k, kind) => graphImageName("horse", k, kind, `${k}${kind}`.padEnd(32, "0"));
const edit = (tool, k) => ({ tool, seed: k, caption: `${tool} caption`, words: `${tool} words`, quick: pass, full: pass, mask: image(k, "mask"),
  layer: tool === "paint" ? image(k, "strokes") : null });
const scene = (tools, more = {}) => sceneGraph(WF, { plate, edits: tools.map((t, i) => edit(t, i + 1)), render: { ...render, ...more }, about: { name: "horse" } });
const fluid = () => fluidGraph(WF, { plate: { path: "output:paintaplate/blank/b.mov", config: plate.config, frames: 17, fps: 25, size: [960, 512] },
  fluid: { keys: [{ frame: 0, image: graphImageName("smoke", 1, "keyframe", "1".padEnd(32, "0")) }], prompt: "smoke", seed: 3, prefix: "paintaplate/blank/f" },
  about: { name: "smoke" } });
const notes = (api) => Object.values(api).filter((n) => n.class_type === "PrimitiveStringMultiline").map((n) => Object.values(n.inputs).find((v) => typeof v === "string"));

test("every note of a scene's graph names what the graph and the page have: each tool, SDR to HDR, Upscale", () => {
  for (const api of [scene(["erase", "paint", "light"], { hdr: true }), scene(["paint"]), scene(["erase"]), scene(["light"], { hdr: true })]) {
    assert.deepEqual(stale(api), []);
  }
});

test("every note of a fluid shot's graph names what the graph and the page have", () => {
  assert.deepEqual(stale(fluid()), []);
});

test("a note that names what its graph or the page lacks is caught", () => {
  const api = scene(["paint"]);
  const readme = Object.values(api).find((n) => n.class_type === "PrimitiveStringMultiline");
  const key = Object.keys(readme.inputs).find((k) => typeof readme.inputs[k] === "string");
  readme.inputs[key] += " Keyframe Video, FLUID SHOT, EDIT 4, [keyframes], gone.png and « Nothing of the page ».";
  assert.deepEqual(stale(api).map((p) => p.slice(p.indexOf(": ") + 2)).sort(),
    ["file gone.png", "mark [keyframes]", "node Keyframe Video", "section EDIT 4", "section FLUID SHOT", "the page's « Nothing of the page »"]);
});

test("the notes take their words from the page: « Text prompt », SAM's answers; Finish's steps are another graph's", () => {
  const all = notes(scene(["erase", "paint", "light"], { hdr: true })).join("\n");
  assert.ok(all.includes("Its « Text prompt » is the node marked [caption].") && !/\bcaption is\b/.test(all));
  assert.ok(all.includes("Follow Matte judges SAM's answers") && !all.includes("Follow Matte keeps the matte on the object"));
  assert.ok(!all.includes("Upscale") && !all.includes("Finish"), "the list's notes say which graph runs Finish's steps (orderText)");
  assert.ok(!notes(fluid()).join("\n").includes("SDR to HDR"), "the fluid shot's graph makes the fluid shot only");
});
