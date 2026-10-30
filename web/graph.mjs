// One ComfyUI workflow for a whole scene: the workflows the page runs, joined by links instead of files, so the scene
// opens in ComfyUI and keeps working there. Laid out for a person who takes it over: numbered sections in the order they
// run, each opening with a README note. Pure functions over workflows parsed by logic.mjs, tested in Node.

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
    const slots = [...new Set(Object.values(node._meta?.slots ?? {}))].filter((s) => !(s in links)); // the values the page sets here
    nodes[id(nid)] = { class_type: node.class_type, inputs, _meta: { title: `${tag}: ${node._meta?.title ?? node.class_type}`, ...(slots.length ? { slots } : {}) } };
  }
  const saved = {};
  for (const [name, nid] of Object.entries(w.outputs)) {
    saved[name] = nodes[id(nid)]?.inputs.images ?? null;
    if (drop.includes(name)) delete nodes[id(nid)];
  }
  return { nodes, saved };
}

// One prompt from the parts, identical nodes shared: each model loads once, the plate decodes once. `onShare(kept, gone)`
// hears of each node folded into an identical one.
export function merge(parts, onShare = () => {}) {
  const prompt = Object.assign({}, ...parts);
  for (let shared = true; shared;) {
    shared = false;
    const first = new Map(), moved = new Map();
    for (const [nid, node] of Object.entries(prompt)) {
      if (OUTPUTS.has(node.class_type)) continue;
      const key = node.class_type + JSON.stringify(node.inputs);
      if (first.has(key)) { onShare(first.get(key), nid); moved.set(nid, first.get(key)); delete prompt[nid]; } else first.set(key, nid);
    }
    for (const node of Object.values(prompt)) for (const [k, v] of Object.entries(node.inputs))
      if (Array.isArray(v) && moved.has(v[0])) { node.inputs[k] = [moved.get(v[0]), v[1]]; shared = true; }
  }
  return prompt;
}

// ---------- The graph laid out for a person ----------
// ComfyUI places the nodes of an API workflow itself, so the ids and the titles carry the structure. Each section takes a
// hundred of ids (the plate 200, the first edit 400) and opens with a README note: core Primitive String Multiline, which
// no node reads, so it never runs. Every title starts with its section; the values the page set show in brackets. Model
// loaders go in MODELS, whichever step first used them, as one loader serves every step.
const INPUT_LOADERS = new Set(["LoadImage", "LoadImageMask", "PaintAPlate_LoadPlate"]);
const isModel = (n) => /Loader/.test(n.class_type) && !INPUT_LOADERS.has(n.class_type);
const modelName = (n) => n.inputs.unet_name ?? n.inputs.ckpt_name ?? n.inputs.clip_name ?? n.inputs.vae_name ?? n.inputs.lora_name ??
  n.inputs.model_name ?? n.inputs.text_encoder ?? "";

export function organise(prompt, where, sections) { // sections: [key, name, README text], in the order they run
  const index = new Map(sections.map(([key], i) => [key, i])), members = sections.map(() => []);
  for (const [id, n] of Object.entries(prompt)) members[index.get(isModel(n) ? "models" : where[id]?.sec) ?? index.get("input")].push(id);
  const ids = new Map(), placed = [];
  let base = 100;
  sections.forEach(([key, name, text], i) => {
    if (!members[i].length && i > 0) return; // a section with no node has no README either
    placed.push([String(base), { class_type: "PrimitiveStringMultiline", inputs: { value: text }, _meta: { title: `README · ${name}` } }]);
    members[i].forEach((id, j) => { ids.set(id, String(base + 1 + j)); placed.push([id, name]); });
    base += Math.ceil((members[i].length + 1) / 100) * 100;
  });
  const out = {};
  for (const [id, item] of placed) {
    if (typeof item !== "string") { out[id] = item; continue; }
    const n = prompt[id], label = isModel(n) ? [n.class_type, modelName(n)].filter(Boolean).join(" · ") : where[id]?.label ?? n._meta.title;
    const inputs = Object.fromEntries(Object.entries(n.inputs).map(([k, v]) => [k, Array.isArray(v) ? [ids.get(v[0]), v[1]] : v]));
    out[ids.get(id)] = { class_type: n.class_type, inputs,
      _meta: { title: `${item} · ${label}${n._meta.slots ? ` [${n._meta.slots.join(", ")}]` : ""}` } };
  }
  return out;
}

const TOOLS = { erase: "Erase", paint: "Paint", light: "Light" };
const by = ([w, h]) => `${w} x ${h}`;
const quoted = (words) => (words ? ` "${words.length > 40 ? `${words.slice(0, 39)}…` : words}"` : "");

// The scene as one prompt. Each edit brings its mask and, for paint and light, its strokes as images already in ComfyUI's
// input folder, its caption, seed and the settings of its two Klein passes. The passes chain as the page layers them; the
// erases alone make the erase pass's first frame; the render runs at full size, as the export does: the erase pass in two stages.
export function sceneGraph(WF, { plate, edits, render, about = {} }) {
  const parts = [], where = {};
  let sec = "input";
  const add = (inst, stage = "") => { // an instance of a workflow, in the section at work, its step named after the workflow's node
    for (const [id, n] of Object.entries(inst.nodes)) where[id] = { sec, label: stage + n._meta.title.slice(n._meta.title.indexOf(": ") + 2) };
    parts.push(inst.nodes);
    return inst.saved;
  };
  const node = (id, cls, inputs, k = 0) => (where[id] = { sec, label: id.replace(/^edit \d+ /, "") },
    parts.push({ [id]: { class_type: cls, inputs, _meta: { title: id } } }), [id, k]);
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
    sec = `edit${k + 1}`;
    const t = `edit ${k + 1}`, mask = node(`${t} mask`, "LoadImageMask", { image: e.mask, channel: "red" });
    const ref = e.layer ? over(`${t} reference`, frame, node(`${t} strokes`, "LoadImage", { image: e.layer }),
      node(`${t} strokes alpha`, "InvertMask", { mask: [`${t} strokes`, 1] })) : frame;
    const qBase = scale(`${t} base at 768`, frame, plate.prev), qRef = e.layer ? scale(`${t} reference at 768`, ref, plate.prev) : qBase;
    const quick = add(instantiate(WF.edit, `${t} quick`, { caption: e.caption, seed: e.seed, ...e.quick },
      { base: qBase, reference: qRef, start: e.tool === "light" ? qBase : qRef, mask: scaleMask(`${t} mask at 768`, mask, plate.prev) }, { drop: EDIT_OUT }),
      `quick pass at ${by(plate.prev)} · `);
    const start = scale(`${t} start`, quick.result, plate.work);
    const full = add(instantiate(WF.edit, `${t} full`, { caption: e.caption, seed: e.seed, ...e.full, relight: e.tool === "light" ? 1 : 0,
      level: e.tool === "erase" }, { base: frame, reference: e.tool === "erase" ? start : ref, start, mask }, { drop: EDIT_OUT }),
      `full size at ${by(plate.work)} · `);
    frame = e.tool === "light" ? full.relit : full.result;
    if (e.tool === "light") return;
    const patch = node(`${t} patch`, "SplitImageWithAlpha", { image: full.patch }), alpha = node(`${t} patch alpha`, "InvertMask", { mask: [`${t} patch`, 1] });
    if (e.tool === "erase") { erasedFrame = over(`${t} on the erased frame`, erasedFrame, patch, alpha); erased.push(mask); }
    else painted.push(alpha);
  });

  let erasedMatte = null, made = null, paintMatte = null;
  const low = stageOne(plate.work);
  if (erased.length) {
    sec = "eraseTrack";
    erasedMatte = add(instantiate(WF.matte, "erase tracking", { ...common, width: plate.trackErase[0], height: plate.trackErase[1],
      prefix: out("matte_a/m") }, { mask: union("erased area", erased, plate.trackErase) }, { drop })).frames;
    // the erase pass in Lightricks' two stages, as the page renders it: half the working size, then 2 steps at full size
    const values = { ...common, seed: render.seed, prompt: render.erasePrompt ?? "" };
    sec = "erasePass";
    const half = add(instantiate(WF.clean, "erase pass at half size", { ...values, width: low[0], height: low[1], prefix: out("clean_half/f"),
      video_prefix: out("clean_half") }, { hole: erasedMatte, hero: erasedFrame }, { drop }), `stage 1 at ${by(low)} · `).frames;
    made = add(instantiate(WF.cleanup, "erase pass", { ...values, width: plate.work[0], height: plate.work[1], prefix: out("clean/f"),
      video_prefix: out("clean") }, { hole: erasedMatte, hero: erasedFrame, low: half }, { drop }), `stage 2 at ${by(plate.work)} · `).frames;
  }
  const clean = !!made;
  sec = "shot";
  if (edits.some((e) => e.tool !== "erase")) made = add(instantiate(WF.shot, "shot", { ...common, ...(made ? { color_space: "@model" } : {}),
    width: plate.work[0], height: plate.work[1], seed: render.seed, prompt: render.prompt, prefix: out("shot/f"), video_prefix: out("raw") },
    { hero: frame, ...(made ? { path: made } : {}) }, { drop })).frames;
  sec = "paintTrack";
  if (painted.length) paintMatte = add(instantiate(WF.matte, "paint tracking", { ...common, color_space: "@model", width: plate.track[0],
    height: plate.track[1], prefix: out("matte_b/m") }, { path: made, mask: union("painted area", painted, plate.track) }, { drop })).frames;
  const relight = edits.some((e) => e.tool === "light"), a = erasedMatte ?? paintMatte, fps = plate.fps ?? 24;
  sec = "hdr";
  const hdr = render.hdr && made ? add(instantiate(WF.hdr, "SDR to HDR", { config: plate.config, max_frames: plate.frames, fps: Math.round(fps),
    cond_fps: Math.min(30, fps), prefix: out("hdr/f") }, { path: made }, { drop: ["hdr"] })).hdr : null;
  sec = "output";
  add(instantiate(WF.export, "export", { ...common, relight, keep_untouched: !relight, grow: render.grow, feather: render.feather,
    hdr_grow: render.grow + render.feather, prefix: out("export"), matte_prefix: out("matte/matte") },
    { shot: made, ...(hdr ? { hdr } : {}), ...(a ? { matte_a: a, matte_b: paintMatte ?? erasedMatte } : {}) }));
  const files = `output/${render.prefix}`, n = edits.length, painting = edits.filter((e) => e.tool === "paint").length;
  const sections = [
    ["readme", "How this graph works", [`AInVFX Paint a plate${about.version ? ` ${about.version}` : ""}: the scene of ${about.name ?? plate.path}, as one ComfyUI workflow.`,
      [`It makes ${n} edit${n === 1 ? "" : "s"} on frame 0, then renders them through the whole shot at full size, as Paint a plate's Export does:`,
        ...edits.map((e, k) => `- Edit ${k + 1}: ${TOOLS[e.tool]}${quoted(e.words)}, seed ${e.seed}.`)].join("\n"),
      `To run it, press Run. It reads the plate, ${plate.path}, from ComfyUI's input folder, and each edit's mask and strokes from input/paintaplate/up, where Paint a plate put them when it saved this graph. It writes the result in the plate's own format to ${files}/export, and its matte to ${files}/matte.`,
      "To read it: each section takes a hundred node ids and opens with a README note like this one, and every node title starts with its section. Brackets list the values Paint a plate set on a node. Model loaders sit in MODELS, shared by every step.",
      "To change an edit: in its section, change the node marked [caption] or [seed], then Run. The edits after it, and the render, follow."].join("\n\n")],
    ["input", "INPUT", `The plate. Load Plate reads ${plate.path}${plate.frames ? `, ${plate.frames} frames` : ""}${plate.fps ? ` at ${plate.fps} fps` : ""}. Color Space turns it from ${plate.cs} into the sRGB the models work in. Frame 0, scaled to ${by(plate.work)}, is the frame the edits paint on.\n\nOut: the plate, every frame, and frame 0.`],
    ["models", "MODELS", "The models, each loaded once and shared by every step that uses it: FLUX 3 Image Klein, its text encoder and VAE for the edits; LTX 2.5, Gemma, its VAEs and IC-LoRAs for the passes; SAM 3.1 for the tracking."],
    ...edits.map((e, k) => [`edit${k + 1}`, `EDIT ${k + 1} · ${TOOLS[e.tool]}${quoted(e.words)}`, [
      `${TOOLS[e.tool]}${quoted(e.words)}, seed ${e.seed}. Klein makes a quick pass at ${by(plate.prev)} in ${e.quick?.steps ?? "its"} steps, then the full size at ${by(plate.work)} in ${e.full?.steps ?? "its"} steps from it. Its caption is the node marked [caption].`,
      `In: ${k ? `the frame EDIT ${k} made` : "frame 0"}, its mask (${e.mask})${e.layer ? ` and its strokes (${e.layer})` : ""}, from input/paintaplate/up.`,
      `Out: ${{ erase: "the frame without the object, for the next edit, and the patch the erase pass starts from.", paint: "the frame with the addition, for the next edit, and the area PAINT TRACKING follows.", light: "the relit frame, for the next edit and the shot." }[e.tool]}`].join("\n\n")]),
    ["eraseTrack", "ERASE TRACKING", `SAM 3.1 follows the erased area${erased.length > 1 ? "s" : ""} through the plate at ${by(plate.trackErase)}, and Follow Matte keeps the matte on the object.\n\nIn: the plate and the erase masks. Out: the erase matte, every frame.`],
    ["erasePass", "ERASE PASS", `Lightricks' in-outpainting IC-LoRA on LTX 2.5 regenerates the erased area on every frame, in two stages: ${by(low)}, then 2 steps at ${by(plate.work)} from it. The prompt describes the scene as it stays, with the erased objects never named.\n\nIn: the plate, the erase matte and frame 0 with every erase. Out: the clean plate, every frame.`],
    ["shot", "SHOT", `LTX 2.5 with WepeNerd's Ripple IC-LoRA carries the edited frame 0 through the shot, over ${clean ? "the clean plate" : "the plate"}, seed ${render.seed}. Its prompt is the node marked [prompt].\n\nIn: the edited frame 0 and ${clean ? "the clean plate" : "the plate"}. Out: the shot, every frame.`],
    ["paintTrack", "PAINT TRACKING", `SAM 3.1 follows the painted area${painting > 1 ? "s" : ""} through the shot at ${by(plate.track)}, and Follow Matte adds what the shot changed near it.\n\nIn: the shot and the painted areas. Out: the paint matte, every frame.`],
    ["hdr", "SDR TO HDR", "Lightricks' SDR-to-HDR IC-LoRA turns the shot into scene-linear values for an EXR plate.\n\nIn: the shot. Out: the HDR shot, every frame."],
    ["output", "OUTPUT", `Fit to Plate puts the shot over the plate inside the mattes, grown by ${render.grow} px and feathered by ${render.feather} px, and matches its colour at their edge${relight ? "; Relight Transfer carries the new light over the plate" : ""}. Save Plate writes the result to ${files}/export in the plate's own format${relight ? "" : ", every pixel outside the mattes the plate's own"}, and the matte to ${files}/matte.\n\nIn: the plate, the shot and the mattes. Out: the files.`],
  ];
  const shared = (kept, gone) => { // one node serving both passes of an edit, or both stages of the erase pass, says so
    const [sa, ...ra] = (where[kept]?.label ?? "").split(" · "), [, ...rb] = (where[gone]?.label ?? "").split(" · ");
    if (where[kept] && ra.length && ra.join(" · ") === rb.join(" · ") && where[kept].label !== where[gone].label)
      where[kept].label = `${sa.startsWith("stage") ? "both stages" : "both passes"} · ${ra.join(" · ")}`;
  };
  return organise(merge(parts, shared), where, sections);
}
