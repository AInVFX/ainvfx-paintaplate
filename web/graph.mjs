// One ComfyUI workflow for a whole scene: the workflows the page runs, joined by links instead of files, so the scene
// opens in ComfyUI and keeps working there. Pure functions over workflows parsed by logic.mjs, tested in Node.

import { fillWorkflow, stageOne } from "./logic.mjs";

const LOADERS = new Set(["LoadImage", "LoadImageMask", "PaintAPlate_LoadPlate"]); // the nodes a link can stand in for
const EDIT_OUT = ["result", "patch", "relit"]; // an edit's saved images: inside one scene, links carry them
const OUTPUTS = new Set(["SaveImage", "PreviewImage", "SaveVideo", "PreviewAny", "PaintAPlate_SavePlate", "PaintAPlate_SaveFrames"]); // never shared

// One workflow under ids prefixed with `tag`: its slots filled with `values`, and the loader on each slot of `links` replaced
// by that link. A plate loader replaced this way takes its spec, frame rate and frame count from the `plate` node. Output
// nodes named in `drop` go (frames the next step now gets by link). Returns the nodes and, per output, the image it saved.
export function instantiate(wf, tag, values, links = {}, { plate = "plate", drop = [] } = {}) {
  // a linked slot counts as filled, so the optional links it feeds stay (its loader goes below)
  const w = fillWorkflow(wf, { ...values, ...Object.fromEntries(Object.keys(links).map((s) => [s, `link:${s}`])) });
  const swap = new Map(), gone = new Set();
  for (const [slot, link] of Object.entries(links)) for (const [nid] of w.slots[slot] ?? []) {
    const cls = w.prompt[nid]?.class_type;
    if (!LOADERS.has(cls)) throw new Error(`${tag}: slot ${slot} is not on a loader`);
    gone.add(nid);
    swap.set(`${nid}:0`, link);
    if (cls === "PaintAPlate_LoadPlate") for (const k of [2, 3, 4, 5]) swap.set(`${nid}:${k}`, [plate, k]);
  }
  const id = (n) => `${tag}: ${n}`, nodes = {};
  for (const [nid, node] of Object.entries(w.prompt)) {
    if (gone.has(nid)) continue;
    const inputs = Object.fromEntries(Object.entries(node.inputs).map(([k, v]) =>
      [k, Array.isArray(v) ? swap.get(`${v[0]}:${v[1]}`) ?? [id(v[0]), v[1]] : v]));
    nodes[id(nid)] = { class_type: node.class_type, inputs, _meta: { title: `${tag}: ${node._meta?.title ?? node.class_type}` } };
  }
  const saved = {};
  for (const [name, nid] of Object.entries(w.outputs)) {
    saved[name] = nodes[id(nid)]?.inputs.images ?? null;
    if (drop.includes(name)) delete nodes[id(nid)];
  }
  return { nodes, saved };
}

// One prompt from the parts, identical nodes shared: each model loads once, the plate decodes once.
export function merge(parts) {
  const prompt = Object.assign({}, ...parts);
  for (let shared = true; shared;) {
    shared = false;
    const first = new Map(), moved = new Map();
    for (const [nid, node] of Object.entries(prompt)) {
      if (OUTPUTS.has(node.class_type)) continue;
      const key = node.class_type + JSON.stringify(node.inputs);
      if (first.has(key)) { moved.set(nid, first.get(key)); delete prompt[nid]; } else first.set(key, nid);
    }
    for (const node of Object.values(prompt)) for (const [k, v] of Object.entries(node.inputs))
      if (Array.isArray(v) && moved.has(v[0])) { node.inputs[k] = [moved.get(v[0]), v[1]]; shared = true; }
  }
  return prompt;
}

// The scene as one prompt. Each edit brings its mask and, for paint and light, its strokes as images already in ComfyUI's
// input folder, its caption, seed and the settings of its two Klein passes. The passes chain as the page layers them; the
// erases alone make the erase pass's first frame; the render runs at full size, as the export does: the erase pass in two stages.
export function sceneGraph(WF, { plate, edits, render }) {
  const parts = [], add = (inst) => (parts.push(inst.nodes), inst.saved);
  const node = (id, cls, inputs, k = 0) => (parts.push({ [id]: { class_type: cls, inputs, _meta: { title: id } } }), [id, k]);
  const scale = (id, image, [width, height]) => node(id, "ImageScale", { image, upscale_method: "lanczos", width, height, crop: "disabled" });
  const scaleMask = (id, mask, size) => node(id, "ImageToMask", { image: scale(`${id}, image`, node(`${id}, as image`, "MaskToImage", { mask }), size), channel: "red" });
  const over = (id, destination, source, mask) => node(id, "ImageCompositeMasked", { destination, source, x: 0, y: 0, resize_source: false, mask });
  const union = (id, masks, size) => scaleMask(id, masks.slice(1).reduce((a, m, i) =>
    node(`${id} ${i + 2}`, "MaskComposite", { destination: a, source: m, x: 0, y: 0, operation: "add" }), masks[0]), size);
  const common = { path: plate.path, config: plate.config, color_space: plate.cs, max_frames: plate.frames }, out = (s) => `${render.prefix}/${s}`, drop = ["frames"];

  node("plate", "PaintAPlate_LoadPlate", { path: plate.path, max_frames: plate.frames, pad_8n1: true });
  const model = node("plate in the model space", "PaintAPlate_ColorSpace", { image: ["plate", 0], config: plate.config, source: plate.cs, destination: "@model" });
  let frame = scale("first frame", node("frame 0", "ImageFromBatch", { image: model, batch_index: 0, length: 1 }), plate.work), erasedFrame = frame;
  const erased = [], painted = [];
  edits.forEach((e, k) => {
    const t = `edit ${k + 1}`, mask = node(`${t} mask`, "LoadImageMask", { image: e.mask, channel: "red" });
    const ref = e.layer ? over(`${t} reference`, frame, node(`${t} strokes`, "LoadImage", { image: e.layer }),
      node(`${t} strokes alpha`, "InvertMask", { mask: [`${t} strokes`, 1] })) : frame;
    const qBase = scale(`${t} base at 768`, frame, plate.prev), qRef = e.layer ? scale(`${t} reference at 768`, ref, plate.prev) : qBase;
    const quick = add(instantiate(WF.edit, `${t} quick`, { caption: e.caption, seed: e.seed, ...e.quick },
      { base: qBase, reference: qRef, start: e.tool === "light" ? qBase : qRef, mask: scaleMask(`${t} mask at 768`, mask, plate.prev) }, { drop: EDIT_OUT }));
    const start = scale(`${t} start`, quick.result, plate.work);
    const full = add(instantiate(WF.edit, `${t} full`, { caption: e.caption, seed: e.seed, ...e.full, relight: e.tool === "light" ? 1 : 0,
      level: e.tool === "erase" }, { base: frame, reference: e.tool === "erase" ? start : ref, start, mask }, { drop: EDIT_OUT }));
    frame = e.tool === "light" ? full.relit : full.result;
    if (e.tool === "light") return;
    const patch = node(`${t} patch`, "SplitImageWithAlpha", { image: full.patch }), alpha = node(`${t} patch alpha`, "InvertMask", { mask: [`${t} patch`, 1] });
    if (e.tool === "erase") { erasedFrame = over(`${t} on the erased frame`, erasedFrame, patch, alpha); erased.push(mask); }
    else painted.push(alpha);
  });

  let erasedMatte = null, made = null, paintMatte = null;
  if (erased.length) {
    erasedMatte = add(instantiate(WF.matte, "erase tracking", { ...common, width: plate.trackErase[0], height: plate.trackErase[1],
      prefix: out("matte_a/m") }, { mask: union("erased area", erased, plate.trackErase) }, { drop })).frames;
    // the erase pass in Lightricks' two stages, as the page renders it: half the working size, then 2 steps at full size
    const low = stageOne(plate.work), values = { ...common, seed: render.seed, prompt: render.erasePrompt ?? "" };
    const half = add(instantiate(WF.clean, "erase pass at half size", { ...values, width: low[0], height: low[1], prefix: out("clean_half/f"),
      video_prefix: out("clean_half") }, { hole: erasedMatte, hero: erasedFrame }, { drop })).frames;
    made = add(instantiate(WF.cleanup, "erase pass", { ...values, width: plate.work[0], height: plate.work[1], prefix: out("clean/f"),
      video_prefix: out("clean") }, { hole: erasedMatte, hero: erasedFrame, low: half }, { drop })).frames;
  }
  if (edits.some((e) => e.tool !== "erase")) made = add(instantiate(WF.shot, "shot", { ...common, ...(made ? { color_space: "@model" } : {}),
    width: plate.work[0], height: plate.work[1], seed: render.seed, prompt: render.prompt, prefix: out("shot/f"), video_prefix: out("raw") },
    { hero: frame, ...(made ? { path: made } : {}) }, { drop })).frames;
  if (painted.length) paintMatte = add(instantiate(WF.matte, "paint tracking", { ...common, color_space: "@model", width: plate.track[0],
    height: plate.track[1], prefix: out("matte_b/m") }, { path: made, mask: union("painted area", painted, plate.track) }, { drop })).frames;
  const relight = edits.some((e) => e.tool === "light"), a = erasedMatte ?? paintMatte;
  add(instantiate(WF.export, "export", { ...common, relight, keep_untouched: !relight, grow: render.grow, feather: render.feather,
    prefix: out("export"), matte_prefix: out("matte/matte") },
    { shot: made, ...(a ? { matte_a: a, matte_b: paintMatte ?? erasedMatte } : {}) }));
  return merge(parts);
}
