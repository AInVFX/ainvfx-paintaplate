// AInVFX PaintAPlate: one viewer to play a plate, paint edits on its first frame and watch the edited shot.
// The page runs on the ComfyUI server that serves it. Every step is a workflow from ./workflows, run by comfy.mjs;
// pure rules live in logic.mjs (tested in Node), canvas helpers in canvas.mjs, the frame cache in frames.mjs.

import { bounds, blob, canvas, loadImage, snap, whiteOf } from "./canvas.mjs";
import { WF, cancel, connect, loadWorkflows, objectInfo, onLog, onNotice, outputFile, outputFiles, outputText, post, run, upload, viewUrl } from "./comfy.mjs";
import { FrameCache } from "./frames.mjs";
import { sceneGraph } from "./graph.mjs";
import { CHANNEL_NAMES, DISPLAY, FLUID, PARAMS, blankSpec, caption, changedMask, clampParam, fluidPrompt, keySlots, moveKey, nearKeys, snapKey, dark, dependsOnChange, displayActive, displayLabel, displayMatrix, displayTransfer, fitSize,
  erasePrompt, erasesPaint, formatParam, gb, levelFill, paintBoxes, pickObjects, plainError, previewSize, previewSizes, reconcile, secs, shotPrompt, splitTable, stageOne,
  strokeTarget, toolEndsEdit, upsampleRequest } from "./logic.mjs";

const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];
const Q = new URLSearchParams(location.search);

// ---------- Tuning: every number that sets a size, a delay or a budget ----------
// FLUX 3 Image Klein: a quick pass at EDIT_SIDE, then a full-size pass that refines it with a light denoise
const QUICK = { steps: 16, denoise: 1, feather: 6, sigma: 3 }; // 16: the official distilled setting, 1.8 s at 768 on an RTX PRO 6000
const FULL = { steps: +Q.get("refine") || 8, denoise: 0.35, feather: 12, sigma: 6 };
const CACHE_MB = +Q.get("cache") || 384; // decoded frames kept per video: about 180 frames at 960 x 544
const WORK_SIDE = 1920, EDIT_SIDE = 768, TRACK_SIDE = 960; // long sides: full-size edits, quick edits, SAM tracking
// the erase matte only places the erase pass's box, grown by 1/24 of the width: 640 is enough, at half the time of 960
const ERASE_TRACK_SIDE = 640;
const LIVE = { every: 2, vram: 24e9 }; // the live preview while LTX samples: every other step, on cards with room for its tiny decoder
const WARM_ALL_VRAM = 60e9; // bytes of GPU memory above which LTX 2.5 is loaded at start too: every model then stays loaded
const PREVIEW_CAP = 640; // the preview size by default: Fast. The menu is built per plate (logic.previewSizes)
const PREFETCH_MS = 500; // quiet time after a keystroke before the prompt writer starts on the new words
const UNDO_MAX = 60; // steps kept for undo
const PAINT_GRID = 96; // cells across the frame for an erase's locked boxes and the check of its caption (logic.paintBoxes, erasesPaint)
// An edit mask grows by the frame width over this: 27 px at 1280, enough for the object's edge. At 24 an erase reached
// what stood next to the object, and Klein sometimes took it too (a head under an umbrella, one seed in five).
const EDIT_GROW = 48;
const PAINT_ZONE = 10; // paint may change the frame within the width over this of its strokes: room for an explosion and its glow
const ZONE_SOFT = { feather: 31, sigma: 10 }; // the zone's edge: Blur Image's largest radius and sigma
const WIPE_GRAB = 14; // CSS px on each side of the wipe line where a press moves the wipe instead of painting
const COMPOSITE_GROW = { erase: 24, other: 160 }, COMPOSITE_FEATHER = 96; // the composite's matte edge, same rule
// The paint matte also takes what the shot changed by 0.1 or more within 1/16 of the width of SAM's matte (Follow Matte):
// a flame or a car that SAM drops mid-shot stays in the composite. The matte starts from the first-frame pixels the edit
// changed by more than `seed` (0 to 255), not from the whole paint zone
const FOLLOW = { zone: 1 / 16, threshold: 0.1, seed: 24 };
const IDLE_MS = 300; // after Generate, a bypass, a removal or an undo, the render starts this soon
const RESULTS_KEPT = 8; // results kept per edit, by the strokes, words, seed and switch that made them: undo gets them back at once
const WORKFLOWS = ["ingest", "prompt", "edit", "snap", "clean", "cleanup", "shot", "matte", "comp", "export", "warm", "fluid"];
const BACKGROUND = ["clean", "shot", "matte", "comp", "export"]; // job kinds a new stroke cancels
const UPSAMPLER = {}; // Black Forest Labs' system prompts for Klein's upsampler (upsampler.json): table and plain
const SCENE = { format: "paintaplate-scene", version: 1 };

const TOOLS = { b: "paint", e: "erase", l: "light" };
// The viewer's colour keys, after OpenRV's rvui.mu: exposure e, gamma y, contrast k, saturation S, hue h; channels c r g b l.
// Here E, B and L pick tools, so exposure and the channels take Shift.
const COLOR_KEYS = { "Shift+e": "exposure", y: "gamma", k: "contrast", "Shift+s": "saturation", h: "hue" };
const CHANNEL_KEYS = { "Shift+c": "rgb", "Shift+r": "r", "Shift+g": "g", "Shift+b": "b", "Shift+l": "l" };
const NAME = { paint: "Paint", erase: "Erase", light: "Light" };
const HINT = {
  paint: "Describe what to paint, then paint it on the frame. A fire, a wooden desk, a red umbrella",
  erase: "Optional: name what to remove, then paint over it. A red umbrella, a man in a coat",
  light: "Optional: describe the light, then paint where it comes from. Warm sunset, neon sign",
};
const FLUID_MISSING = "Fluid shots need ainvfx-fluid.safetensors in models/loras: download it from huggingface.co/AInVFX/ainvfx-fluid (folder ltx-2.5).";
const FLUID_HINT = "Describe the fluid: smoke plume, wild fire, thick white steam (ainvfxfluid is added)";

const S = {
  plate: null, original: null, hero: null,
  edits: [], draft: null, running: null, ids: 0, vers: 0, past: [], future: [], chain: Promise.resolve(), queued: 0,
  tool: "paint", size: 48, colors: { paint: "#000000", light: "#ffd890" }, rub: false,
  get color() { return this.colors[this.tool] ?? "#000000"; },
  frame: 0, playing: false, inPt: 0, outPt: 0, wipe: null, compare: false,
  fit: { w: 0, h: 0, x: 0, y: 0 }, zoom: { k: 1, x: 0, y: 0 },
  display: { ...DISPLAY }, mode: null, scrub: null, // the viewer's colour (display only), and its interactive edit as in RV
  fluid: null, lastFluid: null, clip: null, fluidReady: true, // a fluid shot on a blank plate, the last one, a copied keyframe
  shot: null, shotDirty: false, stage: null, run: 0, exported: null, wantDownload: null,
  background: (() => { try { return localStorage.getItem("paintaplate.background") !== "0"; } catch { return true; } })(), // prepare the export after each change
  previewCap: (() => { try { return +localStorage.getItem("paintaplate.preview") || PREVIEW_CAP; } catch { return PREVIEW_CAP; } })(), // long side of the shot preview: Fast by default
  heroKey: "", renders: new Map(), // set of edits -> what has been rendered for it
  erases: new Map(), // set of erases -> their matte and clean plates, for every render that has the same erases
  peek: null, // the History row picked: frame 0 shows its strokes over the edited first frame
  uploads: new Map(), live: null, vram: 0, // the live preview on show, the GPU's memory in bytes
};

const view = $("#view"), ctx = view.getContext("2d");
const plateVid = $("#plate-video"), shotVid = $("#shot-video");
const fx = document.createElement("canvas"); // scratch layer for masked overlays
const HISTORY_HELP = $("#history-empty").textContent;
const FLUID_HELP = "A fluid shot: paint flat colour blobs (light grey smoke, white steam, orange and yellow fire) on frame 0 and on the " +
  "last frame, and on the 8-frame grid between if you want. Ctrl+C and Ctrl+V copy a keyframe; drag its diamond to move it. Describe " +
  "the fluid, then Enter.";

const quiet = (e) => { if (e?.message === "cancelled") return; console.error(e); status(e?.message ?? String(e), "error"); };
const num = (e) => S.edits.indexOf(e) + 1 || "New"; // an edit's number: its place in History, 1 at the bottom
const snapKeyOf = (e) => `${painted(e)}|${e.whole ? e.prompt : ""}`; // what SAM's answer depends on: the strokes, and the name when it searches by name
const uploadCanvas = async (c, name) => upload(await blob(c), name, `paintaplate/${S.plate.id}`);

// ---------- What Klein sees ----------

function editImage(e, before, size) { // what Klein sees: the strokes over the frame; for an erase, the frame itself
  const c = snap(before, size);
  if (e.tool === "erase") return c; // told to remove the object, Klein cleans it; shown a filled hole, it drew a new object there
  c.getContext("2d").drawImage(e.paint, 0, 0, size[0], size[1]);
  return c;
}

const maskAt = (e, size) => (e.tool === "light" ? snap(null, size, "#fff") : snap(e.mask, size, "#000"));

function templateCaption(e) { // the page's own caption, when the upsampler gives nothing back
  const colors = e.strokes.filter((s) => s.tool !== "rub").map((s) => s.color); // eraser strokes have no colour
  return caption({ tool: e.tool, words: e.prompt, colors, color: e.color, bbox: bounds(e.mask) });
}

function paintGrid(e) { // the painted area on a coarse grid: an erase's locked boxes, and the check of its caption
  const w = PAINT_GRID, h = Math.max(1, Math.round((w * e.mask.height) / e.mask.width));
  const d = snap(e.mask, [w, h], "#000").getContext("2d").getImageData(0, 0, w, h).data, bits = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) bits[i] = d[i * 4] > 32 ? 1 : 0;
  return { bits, w, h };
}

async function captionFor(e, reference, key, kind = "edit") { // Klein's own upsampler writes the caption Klein was trained on; the page keeps its boxes
  if (e.caption?.key === key) return e.caption.text;
  if (e.caption?.key === "scene") { e.caption.key = key; log(`Edit ${num(e)}: the caption saved with the scene is used as it is`); return e.caption.text; }
  if (e.captioning?.key === key) { // the same request is on its way (the strokes rested, then Generate): wait for it rather than ask twice
    try { return await e.captioning.promise; } catch (err) { if (err?.message !== "cancelled" || kind !== "edit") throw err; }
  }
  const promise = writeCaption(e, reference, key, kind);
  e.captioning = { key, promise };
  try { return await promise; } finally { if (e.captioning?.promise === promise) e.captioning = null; }
}

async function writeCaption(e, reference, key, kind) {
  const paint = e.tool === "erase" ? paintGrid(e) : null; // an erase locks one box per painted part
  const ask = upsampleRequest({ tool: e.tool, words: e.prompt, bbox: bounds(e.mask), boxes: paint && paintBoxes(paint) });
  const where = ask.locked?.length > 1 ? `boxes ${JSON.stringify(ask.locked.map((r) => r.src_bbox))}` : `box ${JSON.stringify(ask.locked?.[0]?.src_bbox ?? bounds(e.mask))}`;
  log(`Edit ${num(e)}: asking Klein's prompt writer (${ask.mode} mode) for "${e.prompt || "no words"}" in ${where}`);
  let text = "";
  try {
    const out = await run("prompt", { image: reference, request: ask.request, system: UPSAMPLER[ask.mode] }, { kind, front: true }).done;
    text = (outputText("prompt", out, "text") ?? "").trim();
  } catch (err) { if (err?.message === "cancelled") throw err; quiet(err); }
  let made = text ? (ask.locked ? reconcile(text, ask.locked) : text) : "";
  if (made && paint && !erasesPaint(made, ask.locked, paint)) { // it removed something the paint does not cover (an astronaut, 28 Oct)
    log(`Edit ${num(e)}: the prompt writer removed something the paint does not cover: ${splitTable(made)[0]}`);
    made = "";
  }
  e.caption = { key, text: made || templateCaption(e) };
  log(made ? `Edit ${num(e)}: caption from the prompt writer: ${e.caption.text}` : `Edit ${num(e)}: the page's own caption: ${e.caption.text}`);
  return e.caption.text;
}

function levelled(e, patch, under) { // an erase's fill, levelled with the background it continues (logic.levelFill)
  const [W, H] = S.plate.work, t0 = performance.now(), c = snap(patch, [W, H]), x = c.getContext("2d"), img = x.getImageData(0, 0, W, H);
  const data = (k) => k.getContext("2d").getImageData(0, 0, W, H).data;
  const { rgba, moved } = levelFill({ fill: img.data, base: data(under), paint: data(maskAt(e, [W, H])), width: W, height: H });
  img.data.set(rgba);
  x.putImageData(img, 0, 0);
  log(`Edit ${num(e)}: the fill levelled with the background around it, ${moved.toFixed(1)} levels on average, in ${Math.round(performance.now() - t0)} ms`);
  return c;
}

// ---------- Plate ----------

async function openPlate(list, typed, cs, opts = {}) { // opts.fluid: a blank plate, opened as a fluid shot
  if (!list.length && !typed) return status("Choose files, or type a path in ComfyUI's input folder.");
  stopEverything();
  Object.assign(S, { plate: null, hero: null, original: null }); // nothing to draw while the new plate loads
  const id = Date.now().toString(36), sub = `paintaplate/${id}`;
  let path = typed, out;
  const name = list.length ? list[0].name.replace(/[._]?\d*\.[^.]+$/, "") : typed.split("/").pop();
  opening(name, list.length > 0);
  try {
    if (list.length) {
      const total = list.reduce((a, f) => a + f.size, 0), t0 = performance.now();
      let sent = 0;
      for (const [i, f] of list.entries()) {
        await upload(f, f.name, sub, (n) => {
          const done = sent + n, rate = done / Math.max(0.1, (performance.now() - t0) / 1000);
          openStep("upload", done / total, `${list.length > 1 ? `File ${i + 1} of ${list.length}, ` : ""}${gb(done)} of ${gb(total)}`,
            rate > 0 ? (total - done) / rate : null);
        });
        sent += f.size;
      }
      path = list.length === 1 ? `${sub}/${list[0].name}` : sub;
    }
    openStep("read", 0, "Decoding the frames");
    const t0 = performance.now();
    out = await run("ingest", { path, color_space: cs, prefix: `${sub}/hero`, video_prefix: `${sub}/proxy` }, {
      progress: (f) => openStep(OPENING.at, f, null, f > 0.02 ? ((performance.now() - t0) / 1000) * (1 - f) / f : null),
      step: (cls) => { const k = INGEST[cls]; if (k && OPENING.order.indexOf(k) >= OPENING.order.indexOf(OPENING.at)) openStep(k, 0); } }).done;
  } catch (err) {
    $("#empty").hidden = false; $("#opening").hidden = true;
    for (const b of ["#play-btn", "#wipe-btn"]) $(b).disabled = true;
    throw err;
  }
  openStep("load", 0);
  $("#opening").hidden = true; // the first frame shows from here; the playback video keeps arriving behind it
  const spec = JSON.parse(outputText("ingest", out, "spec"));
  const [w, h] = [spec.width, spec.height];
  const stem = (spec.kind === "video" ? spec.source : spec.first_file ?? spec.source ?? "plate").split(/[\\/]/).pop()
    .replace(/\.[^.]+$/, "").replace(/[._]?\d+$/, "") || "plate";
  S.plate = { id, path, cs, spec, frames: spec.frames, fps: spec.fps || 24, name: stem,
    first: spec.kind === "video" ? 1 : spec.first_frame ?? 1,
    work: fitSize(w, h, WORK_SIDE, 32), prev: fitSize(w, h, EDIT_SIDE, 16),
    track: fitSize(w, h, TRACK_SIDE, 32), trackErase: fitSize(w, h, ERASE_TRACK_SIDE, 32) }; // SAM tracks at one size whatever the preview size
  if (Q.get("shot") === "full") S.previewCap = Math.max(w, h);
  S.plate.shot = previewSize([w, h], S.plate.work, S.previewCap);
  S.original = snap(await loadImage(viewUrl(outputFile("ingest", out, "hero"))), S.plate.work);
  $("#prompt").value = "";
  Object.assign(S, { hero: S.original, edits: [], draft: null, running: null, past: [], future: [], selected: null, hover: null, peek: null, live: null,
    frame: 0, inPt: 0, outPt: S.plate.frames - 1, shot: null, shotDirty: false, exported: null, wantDownload: null,
    stage: { phase: "none" }, zoom: { k: 1, x: 0, y: 0 }, wipe: null, heroKey: "" });
  S.uploads.clear(); S.renders.clear(); S.erases.clear();
  S.fluid = opts.fluid ? { keys: [], seed: (Math.random() * 2 ** 31) | 0, runs: 0, result: null, view: "keys", prompt: "", ...opts.fluid, busy: null } : null;
  [view.width, view.height] = S.plate.work;
  view.classList.add("painting");
  plateVid.src = viewUrl(outputFile("ingest", out, "proxy"));
  plateVid.addEventListener("canplaythrough", () => { if (OPENING.at === "load") { OPENING.at = "done"; status("Ready to play. Describe the edit at the top, paint on the frame, then Generate."); } }, { once: true });
  shotVid.removeAttribute("src"); shotVid.load();
  for (const b of ["#play-btn", "#wipe-btn"]) $(b).disabled = false;
  const kind = spec.kind === "video" ? spec.codec : `${spec.ext.slice(1).toUpperCase()} ${spec.kind}`;
  $("#spec").textContent = `${S.plate.name}: ${kind}, ${w} × ${h}, ${Math.round(S.plate.fps * 1000) / 1000} fps, ${spec.frames} frames, ${cs}`;
  document.activeElement?.blur();
  S.took = {};
  previewUI(); fitView(); historyUI(); timelineUI(); stagesUI(); exportUI(); render();
  log(`Plate ${S.plate.name}: ${w} x ${h}, ${spec.frames} frames; edits at ${S.plate.work.join(" x ")}, quick passes at ${S.plate.prev.join(" x ")}, preview at ${S.plate.shot.join(" x ")}, tracking at ${S.plate.track.join(" x ")}`);
  const offered = [...$("#cs").options].some((o) => o.value === spec.color_space_guess);
  const gaps = spec.missing?.length ? ` ${spec.missing.length} frame${spec.missing.length > 1 ? "s are" : " is"} missing (${spec.missing.slice(0, 4).map((n) => n).join(", ")}${spec.missing.length > 4 ? "…" : ""}): the frame before holds, as in RV.` : "";
  if (gaps) setTimeout(() => status(gaps.trim()), 50);
  status(spec.color_space_guess === cs ? "Describe the edit at the top, paint on the frame, then Generate."
    : offered ? `The file suggests ${spec.color_space_guess}. Reopen with it if colours look wrong.`
    : `The file suggests ${spec.color_space_guess}, which this ComfyUI does not offer yet: update ComfyUI past v0.42.5.`);
  if (S.fluid) enterFluid(); else fluidUI();
}

function stopEverything() {
  pause();
  clearTimeout(S.prefetchTimer); clearTimeout(idleTimer);
  for (const e of S.edits) e.token = (e.token ?? 0) + 1;
  cancel("edit", "snap", "warm", "fluid", ...BACKGROUND);
}

async function warmAll() { // every model loads while the person looks at the page: the first edit and the first shot start at once
  const t0 = performance.now(), vram = (S.vram = (await (await fetch("/system_stats")).json()).devices?.[0]?.vram_total ?? 0);
  // ComfyUI keeps its history in memory until it restarts: a model that a prompt in it used is still loaded
  const history = Object.values(await (await fetch("/history?max_items=200")).json());
  const used = new Set(history.flatMap((h) => Object.values(h.prompt?.[2] ?? {}).map((n) => n.class_type)));
  const tiny = await upload(await blob(snap(null, [256, 144], "#808080")), "warm.png", "paintaplate/warm");
  const mask = await upload(await blob(snap(null, [256, 144], "#000")), "warm_mask.png", "paintaplate/warm");
  const jobs = [["edit", "ReferenceMultiLatent", { base: tiny, reference: tiny, start: tiny, mask, caption: "warm up", seed: 0, steps: 1, denoise: 1,
    grow: 0, feather: 1, sigma: 1 }], ["prompt", "TextGenerate", { image: tiny, request: "Say yes.", system: "Answer with one word.", max_length: 4 }]];
  if (vram >= WARM_ALL_VRAM) jobs.push(["warm", "LTXVConditioning", {}]); // on a smaller card LTX would push the edit models out
  for (const [name, cls, values] of jobs) if (!used.has(cls)) await run(name, values, { kind: "warm" }).done.catch(() => {}); // SAM loads in a second
  if (!S.plate) status(`Ready: every model loaded in ${Math.round((performance.now() - t0) / 1000)} s, so the first edit starts at once. Open a plate.`);
}

// What opening a plate does, in order. Ingest's nodes tell the page which step runs.
const OPENING = { order: ["upload", "read", "convert", "first", "proxy", "load", "done"], at: "upload",
  label: { upload: "Upload the files", read: "Read the frames", convert: "Convert the colours", first: "Save the first frame",
    proxy: "Encode the playback video", load: "Load it in the browser" } };
const INGEST = { PaintAPlate_LoadPlate: "read", ImageColorSpace: "convert", ImageScaleToMaxDimension: "first", SaveImage: "first",
  CreateVideo: "proxy", SaveVideo: "proxy" };
function opening(name, uploading) {
  $("#empty").hidden = true;
  $("#opening").hidden = false;
  $("#op-title").textContent = `Opening ${name || "the plate"}`;
  OPENING.at = uploading ? "upload" : "read";
  OPENING.skip = uploading ? [] : ["upload"];
  openStep(OPENING.at, 0);
}

function openStep(id, f = 0, text = null, left = null) { // one step of opening, with a bar for it and the list of all steps
  OPENING.at = id;
  const order = OPENING.order.filter((k) => !OPENING.skip?.includes(k) && k !== "done"), i = order.indexOf(id);
  $("#op-bar").style.width = `${Math.round(((Math.max(0, i) + Math.min(1, f)) / order.length) * 100)}%`;
  $("#op-step").textContent = [text ?? OPENING.label[id] ?? "", f > 0 && f < 1 ? `${Math.round(f * 100)}%` : "", secs(left)].filter(Boolean).join(", ");
  $("#op-steps").replaceChildren(...order.map((k, j) => Object.assign(document.createElement("li"), {
    className: j < i || id === "done" ? "done" : j === i ? "now" : "", textContent: OPENING.label[k] })));
}

// ---------- Decoded frames (frames.mjs), and RV's green stripe of cached frames ----------

const playhead = () => (S.plate ? { fps: S.plate.fps, frame: S.frame, inPt: S.inPt, outPt: S.outPt } : null);
const caches = new Map([plateVid, shotVid].map((v) => [v, new FrameCache(v, { view: playhead, changed: () => cacheUI(), budget: CACHE_MB * 1e6 })]));

function cacheUI() { // the green stripe along the top of the timeline: frames that draw at once
  if (cacheUI.queued) return;
  cacheUI.queued = requestAnimationFrame(() => {
    cacheUI.queued = 0;
    const c = $("#tl-cache"), p = S.plate;
    if (!p) return;
    const w = (c.width = Math.max(1, Math.round(c.clientWidth * devicePixelRatio))), x = c.getContext("2d");
    c.height = 4;
    x.clearRect(0, 0, w, 4);
    const cache = caches.get(S.shot?.url ? shotVid : plateVid);
    x.fillStyle = "#4caf6a";
    for (const f of cache.frames.keys()) x.fillRect(Math.floor((f / p.frames) * w), 0, Math.ceil(w / p.frames), 4);
  });
}

// ---------- Playback, as in RV ----------

const time = (f) => (f + 0.5) / S.plate.fps;
const clampFrame = (f) => Math.max(0, Math.min(S.plate.frames - 1, Math.round(f)));
const shotReady = () => !!S.shot?.url && shotVid.readyState >= 2;
const stale = () => !!S.shot && S.shot.key !== S.heroKey;
const master = () => (shotReady() ? shotVid : plateVid);

function play() {
  if (!S.plate || S.playing) return;
  if (S.frame >= S.outPt) S.frame = S.inPt;
  S.playing = true;
  S.peek = null;
  $("#play-btn").classList.add("playing");
  for (const v of [plateVid, shotVid]) if (v.getAttribute("src")) { v.currentTime = time(S.frame); v.play().catch(() => {}); }
  const left = renderLeft(), done = left ? `, the edited shot is ${secs(left)}` : "";
  if (S.edits.some((e) => e.on && e.patch)) {
    if (!S.shot) hud(`Playing the plate${done}`, 2500);
    else if (stale()) hud(`Playing the previous render${done}`, 2500);
  }
  requestAnimationFrame(tick);
}

function pause() {
  if (!S.playing) return;
  S.playing = false;
  for (const v of [plateVid, shotVid]) v.pause();
  $("#play-btn").classList.remove("playing");
  if (S.shot?.url && shotVid.readyState >= 2) keepFrame(shotVid); // shown while the video seeks to the exact frame
  seek(S.frame);
}

function tick() {
  if (!S.playing) return;
  const m = master(), fps = S.plate.fps;
  const f = Math.floor(m.currentTime * fps + 1e-3);
  if (f > S.outPt || f < S.inPt || m.ended) { // loop between the in and out points
    S.frame = S.inPt;
    for (const v of [plateVid, shotVid]) if (v.getAttribute("src")) { v.currentTime = time(S.inPt); v.play().catch(() => {}); }
  } else {
    S.frame = Math.min(f, S.plate.frames - 1);
    if (m === shotVid && Math.abs(plateVid.currentTime - m.currentTime) > 0.5 / fps) plateVid.currentTime = m.currentTime;
  }
  render(); timelineUI();
  requestAnimationFrame(tick);
}

function seek(f) {
  if (!S.plate) return;
  S.frame = clampFrame(f);
  if (!S.playing) for (const v of [plateVid, shotVid]) {
    if (v.getAttribute("src") && v.readyState && !caches.get(v).get(S.frame)) v.currentTime = time(S.frame);
  }
  render(); timelineUI();
}

for (const v of [plateVid, shotVid]) {
  v.addEventListener("seeked", () => { if (!S.playing) { render(); caches.get(v).grab(v, S.frame); } });
  v.addEventListener("loadeddata", () => { caches.get(v).reset(); caches.get(v).fill(); });
  v.addEventListener("error", () => v.getAttribute("src") &&
    status(`This browser cannot play the ${v === plateVid ? "plate" : "shot"} preview (H.264 MP4). Chrome, Edge, Safari and Firefox can.`));
}
plateVid.addEventListener("loadeddata", () => seek(S.frame));
plateVid.addEventListener("progress", () => { // the playback video arriving in the browser
  if (OPENING.at !== "load" || !plateVid.duration) return;
  const end = plateVid.buffered.length ? plateVid.buffered.end(plateVid.buffered.length - 1) : 0;
  if (end < plateVid.duration - 0.05) $("#status").textContent = `Loading the playback video: ${Math.round((end / plateVid.duration) * 100)}%`;
});
shotVid.addEventListener("loadeddata", () => {
  if (S.playing) { shotVid.currentTime = plateVid.currentTime; shotVid.play().catch(() => {}); }
  else seek(S.frame);
});
shotVid.addEventListener("canplay", () => { if (!S.playing) render(); }); // a frame that arrives after "seeked" is drawn too

function setIn(f) { S.inPt = Math.min(f, S.outPt); hud(`In point: frame ${S.plate.first + S.inPt}`); timelineUI(); }
function setOut(f) { S.outPt = Math.max(f, S.inPt); hud(`Out point: frame ${S.plate.first + S.outPt}`); timelineUI(); }

// ---------- The picture ----------

function fitView() { // the frame fills the viewport with the plate's own aspect; zoom and pan sit on top
  if (!S.plate) return;
  const box = $("#viewport").getBoundingClientRect(), aspect = S.plate.spec.width / S.plate.spec.height;
  const pad = Math.min(box.width, box.height) < 420 ? 8 : 24; // a phone keeps most of its screen for the frame
  let w = box.width - pad, h = w / aspect;
  if (h > box.height - pad) { h = box.height - pad; w = h * aspect; }
  S.fit = { w, h, x: (box.width - w) / 2, y: (box.height - h) / 2 };
  applyView();
}

function applyView() {
  const { w, h, x, y } = S.fit, z = S.zoom;
  Object.assign(view.style, { width: `${w}px`, height: `${h}px`, transform: `translate(${x + z.x}px, ${y + z.y}px) scale(${z.k})` });
  placeWipe();
}
addEventListener("resize", fitView);

function frameAt(e) { // pointer position in frame pixels (working size); stays right under zoom and pan
  const r = view.getBoundingClientRect();
  return [((e.clientX - r.left) * view.width) / r.width, ((e.clientY - r.top) * view.height) / r.height];
}

function layered(upto = S.edits.length, keep = () => true) { // the first frame with the active edits before index `upto`
  const c = snap(S.original, S.plate.work), x = c.getContext("2d");
  for (const e of S.edits.slice(0, upto)) if (e.on && e.patch && e.state !== "generating" && keep(e)) x.drawImage(e.patch, 0, 0, c.width, c.height);
  return c;
}

function recompose() {
  S.hero = layered();
  const key = S.edits.filter((e) => e.on && e.patch && e.state !== "generating").map((e) => `${e.id}.${e.version}`).join(",");
  if (key === S.heroKey) return;
  S.heroKey = key;
  const r = S.renders.get(key), pv = previewOf(r); // a set of edits seen before plays at once (a bypass turned back on, for example)
  S.exported = r?.exported ?? null;
  if (r?.review || pv?.comp) setShot(r.review ?? pv.comp, key); // the full-size review once there is one
  else if (!key) setShot(null, key);
  S.shotDirty = !!key && !r?.exported;
  stagesUI(); exportUI();
}

function showLive(d) { // the shot as LTX predicts it, every other step: a small looping animation until the shot itself arrives
  const img = new Image(), key = S.heroKey;
  img.onload = () => {
    if (key !== S.heroKey || S.shot?.key === key) return;
    S.live = img;
    hud(`Live preview, step ${d.step}: the shot follows`, 2000);
    if (!showLive.on) { showLive.on = true; const tick = () => { if (!S.live) { showLive.on = false; return; } render(); requestAnimationFrame(tick); }; tick(); }
  };
  img.src = viewUrl(d.image);
}

function setShot(src, key) {
  S.live = null; // the shot itself, rough or composited, replaces the live preview
  S.shot = src ? { url: src, key } : null;
  if (src) { if (shotVid.getAttribute("src") !== src) shotVid.src = src; }
  else { shotVid.removeAttribute("src"); shotVid.load(); }
  render(); timelineUI();
}

// Once the shot of the current edits exists, it shows on every frame, playing or paused; the plate shows only in the wipe and
// while O is held. Frame 0 shows the edited first frame with the strokes while edits are made. Paused, the viewer drew the plate
// whenever the shot video had no frame ready, and frame 0 kept showing Klein's still (28 Oct).
const held = { canvas: canvas([1, 1]), url: "" }; // the last shot frame drawn while paused: shown while the shot video seeks
const editingFirst = () => !!(S.draft || stroke || S.running || S.queued || S.hover || S.peek);

function keepFrame(src) {
  const [W, H] = [view.width, view.height], c = held.canvas;
  if (c.width !== W || c.height !== H) [c.width, c.height] = [W, H];
  c.getContext("2d").drawImage(src, 0, 0, W, H);
  held.url = S.shot.url;
}

function shotFrame() { // the shot at the playhead: a cached frame, the video when it shows that frame, or the frame held
  const cached = !S.playing && caches.get(shotVid).get(S.frame);
  if (cached) return cached;
  if (shotVid.readyState >= 2 && (S.playing || !shotVid.seeking)) return shotVid;
  return !S.playing && held.url === S.shot.url ? held.canvas : null;
}

function render() {
  if (!S.plate || !S.hero) return;
  if (S.fluid) return renderFluid();
  const W = view.width, H = view.height, still = !S.playing;
  const live = S.draft || stroke ? null : S.live; // while an edit is painted, the frame shows it, not the live preview of a render
  const first = still && S.frame === 0 && (!S.shot?.url || stale() || editingFirst());
  const pic = live || first || !S.shot?.url ? null : shotFrame();
  if (S.playing && S.shot?.url && !live && !pic) return; // the shot video catches up in a frame: the last frame stays on screen
  const drawPlate = () => {
    const cached = still && S.frame !== 0 && caches.get(plateVid).get(S.frame);
    if (still && S.frame === 0) ctx.drawImage(S.original, 0, 0, W, H);
    else if (cached) ctx.drawImage(cached, 0, 0, W, H);
    else if (plateVid.readyState >= 2) ctx.drawImage(plateVid, 0, 0, W, H);
  };
  const drawEdited = () => {
    if (live) { ctx.drawImage(live, 0, 0, W, H); return "live"; }
    if (pic) {
      ctx.drawImage(pic, 0, 0, W, H);
      if (pic === held.canvas) return "held";
      if (still) keepFrame(pic);
      return "shot";
    }
    if (still && S.frame === 0) { ctx.drawImage(S.hero, 0, 0, W, H); overlays(W, H); return "hero"; }
    drawPlate();
    return "plate";
  };
  ctx.globalAlpha = 1;
  let shown = "plate";
  if (S.compare) drawPlate();
  else if (S.wipe !== null) {
    drawPlate();
    ctx.save(); ctx.beginPath(); ctx.rect(S.wipe * W, 0, W - S.wipe * W, H); ctx.clip();
    shown = drawEdited();
    ctx.restore();
  } else shown = drawEdited();
  view.dataset.picture = shown; // what the edited side shows: live, hero, shot, held or plate (tests/ui_mock.py reads it)
  drawCursor();
}

function renderFluid() { // a fluid shot: the keyframes on black, the shot LTX predicts, or the generated shot (the wipe shows both)
  const W = view.width, H = view.height, f = S.fluid;
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, W, H);
  const shot = () => ctx.drawImage((!S.playing && caches.get(shotVid).get(S.frame)) || shotVid, 0, 0, W, H);
  if (S.live && f.busy) ctx.drawImage(S.live, 0, 0, W, H);
  else if (f.result && f.view === "result" && !S.compare && shotReady()) {
    if (S.wipe === null) shot();
    else { keysLayer(W, H); ctx.save(); ctx.beginPath(); ctx.rect(S.wipe * W, 0, W - S.wipe * W, H); ctx.clip(); shot(); ctx.restore(); }
  } else keysLayer(W, H);
  drawCursor();
}

function keysLayer(W, H) { // the keyframe on this frame; between keyframes, the two around it faintly, as onion skins
  const key = keyHere();
  if (key) return void ctx.drawImage(key.canvas, 0, 0, W, H);
  if (S.playing) return;
  const { prev, next } = nearKeys(S.fluid.keys, S.frame);
  ctx.globalAlpha = 0.25;
  for (const k of [prev, next]) if (k) ctx.drawImage(k.canvas, 0, 0, W, H);
  ctx.globalAlpha = 1;
}

function overlays(W, H) { // on the first frame: the strokes, then the edit taking shape inside them
  const e = S.running;
  if (e?.preview) ctx.drawImage(e.preview, 0, 0, W, H);
  else if (e?.latent) {
    [fx.width, fx.height] = [W, H];
    const f = fx.getContext("2d");
    f.globalCompositeOperation = "copy"; f.drawImage(e.latent, 0, 0, W, H);
    if (e.tool !== "light") { f.globalCompositeOperation = "destination-in"; f.drawImage(softMask(e), 0, 0); }
    ctx.drawImage(fx, 0, 0);
  }
  if (S.draft) strokes(S.draft, 1);
  const shown = S.hover ?? S.selected; // History: which edit is which, and the one selected
  if (shown && shown !== e && shown.tool !== "light" && shown.strokes.length) strokes(shown, S.hover ? 0.55 : 0.8);
  if (e && e.launched && !e.preview) { // the strokes stay until the first preview replaces them, then fade into it
    const t = e.shown ? (performance.now() - e.shown) / 350 : 0;
    if (t < 1) { strokes(e, 1 - t); if (e.shown) requestAnimationFrame(render); }
  }
}

function strokes(e, alpha) {
  if (e.tool === "erase") { // the area to clean: a red tint inside a light outline
    const W = e.mask.width, H = e.mask.height, r = Math.max(1.5, W / 640);
    [fx.width, fx.height] = [W, H];
    const t = fx.getContext("2d");
    t.globalCompositeOperation = "copy"; t.drawImage(e.mask, 0, 0);
    t.globalCompositeOperation = "source-in"; t.fillStyle = "#ff5040"; t.fillRect(0, 0, W, H);
    ctx.globalAlpha = 0.45 * alpha; ctx.drawImage(fx, 0, 0);
    t.globalCompositeOperation = "copy"; t.clearRect(0, 0, W, H);
    t.globalCompositeOperation = "source-over";
    for (const [dx, dy] of [[r, 0], [-r, 0], [0, r], [0, -r], [r, r], [-r, -r], [r, -r], [-r, r]]) t.drawImage(e.mask, dx, dy);
    t.globalCompositeOperation = "destination-out"; t.drawImage(e.mask, 0, 0);
    t.globalCompositeOperation = "source-in"; t.fillStyle = "#fff4f0"; t.fillRect(0, 0, W, H);
    ctx.globalAlpha = 0.9 * alpha; ctx.drawImage(fx, 0, 0);
  } else { ctx.globalAlpha = 0.9 * alpha; ctx.drawImage(e.paint, 0, 0); }
  ctx.globalAlpha = 1;
}

function softMask(e) { // the edit mask with a soft edge, close to what the workflow composites with
  const key = `${e.strokes.length}:${e.snapped ?? 0}:${!!e.sam}`;
  if (e.soft?.key !== key) {
    const c = canvas([e.mask.width, e.mask.height]), x = c.getContext("2d");
    x.filter = `blur(${Math.max(2, Math.round(e.mask.width / 160))}px)`;
    x.drawImage(e.mask, 0, 0);
    e.soft = { key, canvas: c };
  }
  return e.soft.canvas;
}

function drawCursor() { // the brush outline, at its real size on the frame
  if (!S.cursor || stroke || S.playing || S.mode || view.classList.contains("near-wipe")) return;
  ctx.lineWidth = Math.max(1.5, view.width / 900);
  ctx.strokeStyle = S.rub ? "#ffffff" : S.tool === "erase" ? "#ff8070" : S.color === "#000000" ? "#d8d8d8" : S.color;
  if (S.rub) ctx.setLineDash([6, 5]);
  ctx.beginPath(); ctx.arc(S.cursor[0], S.cursor[1], S.size / 2, 0, 2 * Math.PI); ctx.stroke();
  ctx.setLineDash([]);
}

function placeWipe() {
  const el = $("#wipe");
  el.hidden = S.wipe === null || !S.plate;
  if (el.hidden) return;
  const r = view.getBoundingClientRect(), box = $("#viewport").getBoundingClientRect();
  const top = Math.max(0, r.top - box.top), bottom = Math.min(box.height, r.bottom - box.top);
  Object.assign(el.style, { left: `${r.left - box.left + S.wipe * r.width}px`, top: `${top}px`, height: `${bottom - top}px` });
}

function setWipe(on) {
  S.wipe = on ? S.wipe ?? 0.5 : null;
  $("#wipe-btn").setAttribute("aria-pressed", String(on));
  placeWipe(); render();
  hud(on ? "Wipe: the plate on the left, the result on the right" : "Wipe off");
}

function nearWipe(e) { // a press this close to the wipe line moves the wipe: it never paints
  if (S.wipe === null || !S.plate) return false;
  const r = view.getBoundingClientRect();
  return Math.abs(e.clientX - (r.left + S.wipe * r.width)) <= WIPE_GRAB;
}

function dragWipe(e, el) {
  e.preventDefault();
  el.setPointerCapture(e.pointerId);
  const move = (ev) => {
    const r = view.getBoundingClientRect();
    S.wipe = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
    placeWipe(); render();
  };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", () => el.removeEventListener("pointermove", move), { once: true });
}
$("#wipe .grip").addEventListener("pointerdown", (e) => dragWipe(e, e.currentTarget));

let hudTimer;
function hud(text, ms = 1600) {
  const el = $("#hud");
  el.textContent = text;
  el.classList.add("on");
  clearTimeout(hudTimer);
  hudTimer = setTimeout(() => el.classList.remove("on"), ms);
}

// ---------- Painting: the strokes wait for Generate (Enter), which makes the edit, then its shot ----------

let stroke = null, nav = null, pinch = null;
const touches = new Map(); // fingers on the frame: two pan and zoom it, as Alt and Ctrl drags do with a mouse

view.addEventListener("pointerdown", (e) => {
  if (!S.plate) return;
  if (e.pointerType === "touch") {
    touches.set(e.pointerId, [e.clientX, e.clientY]);
    if (touches.size === 2) return pinchStart();
    if (touches.size > 2 || pinch) return;
  }
  if (S.mode && e.button === 0 && !e.altKey && !e.ctrlKey && !e.metaKey) { // a colour edit: dragging changes the value, as in RV
    e.preventDefault();
    view.setPointerCapture(e.pointerId);
    S.scrub = { x: e.clientX, start: S.display[S.mode] };
    return;
  }
  if (e.button === 1 || (e.button === 0 && (e.altKey || e.ctrlKey || e.metaKey))) return navigate(e);
  if (e.button === 0 && nearWipe(e)) return dragWipe(e, view);
  const rub = S.rub || (e.pointerType === "pen" && (e.buttons & 32)); // the eraser tool, or a pen's eraser end
  if (e.button !== 0 && !rub) return;
  if (S.playing) pause();
  if (S.fluid) return paintKey(e, rub);
  if (S.frame !== 0) { seek(0); hud("Edits are painted on the first frame"); }
  if (rub) return rubOut(e);
  cancel("prefetch"); // a caption written for fewer strokes is outdated
  clearTimeout(S.prefetchTimer);
  mark(); // one undo step per stroke
  let d = S.draft;
  const to = strokeTarget({ draft: S.draft, current: S.selected, tool: S.tool }); // the current edit takes the strokes of its own tool
  if (to === "current") d = busy(S.selected) ? reopen(S.selected) : reopenDone(S.selected); // the edit changes: its passes and its render stop
  if (to === "new") { S.selected = null; d = S.draft = newEdit(); editingUI(); } // a new edit: what renders goes on until Generate
  view.setPointerCapture(e.pointerId);
  stroke = { tool: d.tool, color: S.color, size: S.size, points: [] };
  d.strokes.push(stroke);
  addPoint(d, e);
});

view.addEventListener("pointermove", (e) => {
  if (touches.has(e.pointerId)) touches.set(e.pointerId, [e.clientX, e.clientY]);
  if (pinch) return pinchMove();
  if (S.scrub) return setDisplay({ [S.mode]: clampParam(S.mode, S.scrub.start + (e.clientX - S.scrub.x) * PARAMS[S.mode].drag) });
  if (nav) return navigateMove(e);
  if (stroke && S.keyDraft) return addKeyPoint(S.keyDraft, e);
  if (stroke && S.draft) return addPoint(S.draft, e);
  S.cursor = frameAt(e);
  view.classList.toggle("near-wipe", nearWipe(e));
  if (!S.playing) requestAnimationFrame(render);
});
view.addEventListener("pointerleave", () => { S.cursor = null; if (!S.playing) requestAnimationFrame(render); });
view.addEventListener("pointercancel", (e) => view.dispatchEvent(new PointerEvent("pointerup", e))); // the browser took the touch: end as a lift
view.addEventListener("pointerup", (e) => {
  touches.delete(e.pointerId);
  if (pinch) { if (touches.size < 2) pinch = null; return; }
  if (S.scrub) { S.scrub = null; return leaveMode(); } // RV leaves the edit when the drag ends
  if (nav) { nav = null; view.classList.remove("panning"); return; }
  if (!stroke) return;
  stroke = null;
  if (S.keyDraft) { S.keyDraft = null; fluidUI(); return render(); }
  if (S.draft && !painted(S.draft)) return discard(); // everything was rubbed out
  prepareSoon();
});

function rubOut(e) { // the eraser works on the strokes in progress, or on the current edit
  let d = S.draft;
  const target = S.selected;
  if (!d && target?.strokes.length) d = busy(target) ? reopen(target) : reopenDone(target);
  if (!d) return hud("Nothing to rub out: select an edit in History, or paint first");
  cancel("prefetch");
  clearTimeout(S.prefetchTimer);
  mark();
  view.setPointerCapture(e.pointerId);
  stroke = { tool: "rub", size: S.size, points: [] };
  d.strokes.push(stroke);
  addPoint(d, e);
}

const busy = (e) => e === S.running || e.state === "queued"; // an edit being generated, or waiting for its turn

function reopenDone(edit) { // a finished edit changes (strokes, words, the switch): strokes again until Generate; its render stops
  cancel(...BACKGROUND);
  edit.kept = edit.strokes.length;
  edit.state = "drawing";
  historyUI();
  return (S.draft = edit);
}

function takeInputs(edit) { // the words and the Whole object switch belong to the edit being drawn, as they change
  edit.prompt = $("#prompt").value.trim();
  if (edit.tool === "erase") edit.whole = $("#whole").checked;
}

function prepareSoon(typing = false) { // the draft waits for Generate; SAM and the prompt writer start now, so Generate starts at once
  clearTimeout(S.prefetchTimer);
  if (!S.draft) return generateUI();
  takeInputs(S.draft); // the prefetch sees them: SAM finds the whole object first, then the prompt writer writes for its box
  if (typing) S.prefetchTimer = setTimeout(() => prefetch(S.draft), PREFETCH_MS); // not on every keystroke
  else { prefetch(S.draft); hud("Generate (Enter) makes the edit, then its shot. Esc cancels.", 2500); }
  generateUI();
}

function newEdit() {
  return { id: ++S.ids, tool: S.tool, color: S.color, prompt: "", seed: (Math.random() * 2 ** 31) | 0,
    strokes: [], on: true, state: "drawing", version: 0, basis: [], results: new Map(),
    paint: canvas(S.plate.work), mask: canvas(S.plate.work), patch: null, foot: null };
}

function addPoint(d, e) {
  const [x, y] = (S.cursor = frameAt(e));
  stroke.points.push([x, y, e.pressure || 0.5]);
  drawStroke(d, stroke, stroke.points.length - 1);
  render();
}

function drawStroke(d, s, from = 0) {
  const pc = d.paint.getContext("2d"), mc = d.mask.getContext("2d");
  if (s.tool === "rub") { // the eraser takes strokes away, whatever drew them
    for (const c of [pc, mc]) c.globalCompositeOperation = "destination-out";
    for (let i = from; i < s.points.length; i++) {
      const [x, y, p] = s.points[i], [px, py] = s.points[Math.max(i - 1, 0)], r = (s.size * (0.5 + p)) / 2;
      line(mc, px, py, x, y, r, "#fff"); line(pc, px, py, x, y, r, "#fff");
    }
    for (const c of [pc, mc]) c.globalCompositeOperation = "source-over";
    return;
  }
  for (let i = from; i < s.points.length; i++) {
    const [x, y, p] = s.points[i], [px, py] = s.points[Math.max(i - 1, 0)], r = (s.size * (0.5 + p)) / 2;
    line(mc, px, py, x, y, r, "#fff");
    if (s.tool === "paint") line(pc, px, py, x, y, r, s.color);
    if (s.tool === "light") dark(s.color) ? line(pc, px, py, x, y, r, "#000000a0") : glow(pc, x, y, r * 2.5, s.color);
  }
}

function line(c, x0, y0, x1, y1, r, color) {
  Object.assign(c, { strokeStyle: color, lineWidth: 2 * r, lineCap: "round", lineJoin: "round" });
  c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke();
}

function glow(c, x, y, r, color) {
  const g = c.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0, `${color}cc`); g.addColorStop(1, `${color}00`);
  c.globalCompositeOperation = "lighter"; c.fillStyle = g; c.fillRect(x - r, y - r, 2 * r, 2 * r);
  c.globalCompositeOperation = "source-over";
}

function redrawStrokes(d) { // painted strokes, then SAM's object, then the eraser strokes on top of both
  for (const c of [d.paint, d.mask]) c.getContext("2d").clearRect(0, 0, c.width, c.height);
  for (const s of d.strokes) if (s.tool !== "rub") drawStroke(d, s);
  if (d.sam) d.mask.getContext("2d").drawImage(d.sam, 0, 0);
  for (const s of d.strokes) if (s.tool === "rub") drawStroke(d, s);
  d.soft = null;
}

const painted = (d) => d.strokes.filter((s) => s.tool !== "rub").length; // SAM grows from these

function pinchStart() { // a second finger: the first one's stroke is taken back, then the two fingers pan and zoom
  if (stroke) dropStroke();
  const [a, b] = [...touches.values()];
  pinch = { d: Math.hypot(a[0] - b[0], a[1] - b[1]) || 1, m: [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2], start: { ...S.zoom } };
}

function pinchMove() {
  if (touches.size < 2) return;
  const [a, b] = [...touches.values()], s = pinch.start, m = [(a[0] + b[0]) / 2, (a[1] + b[1]) / 2];
  const k = Math.max(0.25, Math.min(16, s.k * (Math.hypot(a[0] - b[0], a[1] - b[1]) / pinch.d)));
  const box = $("#viewport").getBoundingClientRect(), ox = pinch.m[0] - box.left - S.fit.x, oy = pinch.m[1] - box.top - S.fit.y;
  S.zoom = { k, x: ox - ((ox - s.x) * k) / s.k + m[0] - pinch.m[0], y: oy - ((oy - s.y) * k) / s.k + m[1] - pinch.m[1] }; // about where the fingers met
  applyView(); render();
}

function dropStroke() { // the stroke a finger began before the pinch goes, with its undo step
  const owner = S.keyDraft ?? S.draft, s = stroke;
  stroke = null; S.keyDraft = null;
  if (owner) {
    owner.strokes.splice(owner.strokes.lastIndexOf(s), 1);
    if (owner.canvas) { redrawKey(owner); if (!owner.strokes.length) S.fluid.keys.splice(S.fluid.keys.indexOf(owner), 1); } else redrawStrokes(owner);
  }
  S.past.pop(); undoUI();
  const d = S.draft;
  if (d && !painted(d) && !S.edits.includes(d)) S.draft = null; // nothing left of a new edit
  else if (d && S.edits.includes(d) && reuse(d)) { S.draft = null; historyUI(); touch(); } // a made edit back as it was
  render(); generateUI();
}

function navigate(e) { // RV: Alt or middle button drag pans, Ctrl drag zooms
  e.preventDefault();
  view.setPointerCapture(e.pointerId);
  nav = { zoom: e.ctrlKey || e.metaKey, x: e.clientX, y: e.clientY, start: { ...S.zoom }, at: [e.clientX, e.clientY] };
  view.classList.add("panning");
}

function navigateMove(e) {
  const dx = e.clientX - nav.x, dy = e.clientY - nav.y, s = nav.start;
  if (!nav.zoom) S.zoom = { ...s, x: s.x + dx, y: s.y + dy };
  else {
    const k = Math.max(0.25, Math.min(16, s.k * Math.exp(dx / 200)));
    const box = $("#viewport").getBoundingClientRect();
    const ox = nav.at[0] - box.left - S.fit.x, oy = nav.at[1] - box.top - S.fit.y; // zoom about the press point
    S.zoom = { k, x: ox - ((ox - s.x) * k) / s.k, y: oy - ((oy - s.y) * k) / s.k };
  }
  applyView(); render();
}

function zoomTo(k) {
  const z = S.fit;
  S.zoom = k === 1 ? { k: 1, x: 0, y: 0 } : { k, x: (z.w - z.w * k) / 2, y: (z.h - z.h * k) / 2 };
  applyView(); render();
  hud(k === 1 ? "Fit" : "1:1");
}

// ---------- A fluid shot on a blank plate: keyframes painted in flat colours, then ainvfx-fluid ----------

const keyHere = () => S.fluid?.keys.find((k) => k.frame === S.frame);
const newKey = (frame) => ({ id: ++S.ids, frame, strokes: [], canvas: canvas(S.plate.work) });

function enterFluid() { // a blank plate opens as a fluid shot: the paint tool in a fluid colour, the keyframes, the panel
  const f = S.fluid;
  setTool("paint");
  if (dark(S.colors.paint)) S.colors.paint = "#c8c8c8"; // black paint on a black plate shows nothing
  colorUI();
  $("#prompt").value = f.prompt ?? "";
  if (f.result) { f.view = "result"; setShot(f.result.preview, "fluid"); }
  fluidUI(); timelineUI(); render();
  status("Fluid shot: paint flat colour blobs on frame 0 and on the last frame, describe the fluid, then Enter. Keyframes snap to the 8-frame grid.");
}

function paintKey(e, rub) { // strokes go to the keyframe on the playhead's slot of the 8-frame grid
  const f = S.fluid, slot = snapKey(S.frame, S.plate.frames);
  if (slot !== S.frame) { seek(slot); hud(`Keyframes sit on frame 0, on the last frame, or on 8k + 1 between: frame ${S.plate.first + slot}`, 2500); }
  let key = f.keys.find((k) => k.frame === slot);
  if (!key && rub) return hud("No keyframe on this frame to rub out");
  mark();
  if (!key) f.keys.push((key = newKey(slot)));
  f.view = "keys";
  view.setPointerCapture(e.pointerId);
  stroke = { tool: rub ? "rub" : "paint", color: S.color, size: S.size, points: [] };
  key.strokes.push(stroke);
  S.keyDraft = key;
  staleFluid();
  addKeyPoint(key, e);
}

function addKeyPoint(key, e) {
  const [x, y] = (S.cursor = frameAt(e));
  stroke.points.push([x, y, e.pressure || 0.5]);
  drawKeyStroke(key, stroke, stroke.points.length - 1);
  render();
}

function drawKeyStroke(key, s, from = 0) { // flat colour on the keyframe; the eraser takes it away
  const c = key.canvas.getContext("2d");
  c.globalCompositeOperation = s.tool === "rub" ? "destination-out" : "source-over";
  for (let i = from; i < s.points.length; i++) {
    const [x, y, p] = s.points[i], [px, py] = s.points[Math.max(i - 1, 0)];
    line(c, px, py, x, y, (s.size * (0.5 + p)) / 2, s.tool === "rub" ? "#fff" : s.color);
  }
  c.globalCompositeOperation = "source-over";
}

function redrawKey(key) {
  key.canvas.getContext("2d").clearRect(0, 0, key.canvas.width, key.canvas.height);
  for (const s of key.strokes) drawKeyStroke(key, s);
}

// what a fluid shot is made from: its keyframes, its words and its seed. Shots already made are kept by it, so Enter never makes one twice
const fluidSig = () => JSON.stringify([[...S.fluid.keys].sort((a, b) => a.frame - b.frame).map((k) => [k.frame, strokesSig(k.strokes)]),
  $("#prompt").value.trim(), S.fluid.seed]);

function staleFluid() { // the keyframes or the words changed: the shot on show comes from the old ones, and a run of the old ones stops
  const f = S.fluid;
  if (f?.busy && f.busy.sig !== fluidSig()) {
    cancel("fluid");
    log(`Fluid v${f.busy.v}: stopped, its keyframes or words changed`);
    hud("Stopped: the keyframes or the words changed. Generate starts again.", 2500);
  }
  fluidUI(); timelineUI();
}

function copyKey() {
  const k = keyHere();
  if (!k) return hud("No keyframe on this frame to copy");
  S.clip = k.strokes.map((s) => ({ ...s, points: s.points.slice() }));
  hud(`Keyframe ${S.plate.first + k.frame} copied: Ctrl+V pastes it on another frame`);
}

function pasteKey() {
  if (!S.clip) return hud("Copy a keyframe first: Ctrl+C on its frame");
  const f = S.fluid, slot = snapKey(S.frame, S.plate.frames);
  mark();
  let k = f.keys.find((x) => x.frame === slot);
  if (!k) f.keys.push((k = newKey(slot)));
  k.strokes = S.clip.map((s) => ({ ...s, points: s.points.slice() }));
  redrawKey(k);
  f.view = "keys";
  pause(); seek(slot); staleFluid(); render();
  hud(`Keyframe pasted on frame ${S.plate.first + slot}`);
}

function deleteKey(k = keyHere()) {
  if (!k) return hud("No keyframe on this frame");
  mark();
  S.fluid.keys.splice(S.fluid.keys.indexOf(k), 1);
  staleFluid(); render();
  hud(`Keyframe ${S.plate.first + k.frame} deleted: Ctrl+Z brings it back`);
}

function jumpKey(dir) {
  const { prev, next } = nearKeys(S.fluid.keys, S.frame), k = dir < 0 ? prev : next;
  if (k) { pause(); seek(k.frame); } else hud(dir < 0 ? "No keyframe before this frame" : "No keyframe after this frame");
}

function dragKey(e, key, el) { // a keyframe dragged along the timeline lands on the nearest free slot of the grid; a click goes to it
  e.preventDefault();
  e.stopPropagation();
  el.setPointerCapture(e.pointerId);
  const box = $("#timeline").getBoundingClientRect(), n = S.plate.frames;
  let moved = false;
  S.draggingKey = true;
  const move = (ev) => {
    const to = moveKey(S.fluid.keys, key, Math.round(((ev.clientX - box.left) / box.width) * n - 0.5), n);
    if (to === key.frame) return;
    if (!moved) { mark(); moved = true; }
    key.frame = to;
    el.dataset.frame = to;
    el.style.left = `${((to + 0.5) / n) * 100}%`;
    pause(); seek(to); staleFluid();
  };
  el.addEventListener("pointermove", move);
  el.addEventListener("pointerup", () => {
    el.removeEventListener("pointermove", move);
    S.draggingKey = false;
    if (moved) hud(`Keyframe moved to frame ${S.plate.first + key.frame}`); else { pause(); seek(key.frame); }
    keysUI(true);
  }, { once: true });
}

function keysUI(force = false) { // the keyframe diamonds on the timeline, over the slots of the 8-frame grid they snap to
  const box = $("#tl-keys"), p = S.plate, f = S.fluid;
  const sig = f ? `${p.frames}|${f.keys.map((k) => k.frame).join(",")}` : "";
  if ((force || sig !== box.dataset.sig) && !S.draggingKey) {
    box.dataset.sig = sig;
    const pos = (fr) => `${((fr + 0.5) / p.frames) * 100}%`;
    box.replaceChildren(...(f ? [...keySlots(p.frames).map((fr) => {
      const tick = document.createElement("i");
      tick.className = "tl-slot";
      tick.style.left = pos(fr);
      return tick;
    }), ...f.keys.map((k) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "tl-kf";
      b.dataset.frame = k.frame;
      b.style.left = pos(k.frame);
      b.title = `Keyframe at frame ${p.first + k.frame}: drag it to move it, click to go to it`;
      b.addEventListener("pointerdown", (e) => dragKey(e, k, b));
      return b;
    })] : []));
  }
  for (const b of box.querySelectorAll(".tl-kf")) b.classList.toggle("on", +b.dataset.frame === S.frame);
}

async function generateFluid(another = false) { // one LTX 2.5 pass with ainvfx-fluid: the keyframes become smoke, steam or fire
  const p = S.plate, f = S.fluid;
  if (!S.fluidReady) return status(FLUID_MISSING);
  if (!f.keys.length) return status("Paint a keyframe first: flat colour blobs on frame 0 and on the last frame.");
  if (another) f.seed = (Math.random() * 2 ** 31) | 0;
  else { // Enter again: a shot being made, or already made, from these keyframes, words and seed is not made twice
    if (f.busy?.sig === fluidSig()) return hud(`Fluid shot v${f.busy.v} is being made from these keyframes and words`, 2500);
    const made = f.made?.get(fluidSig());
    if (made) {
      if (f.result !== made) { f.result = made; setShot(made.preview, "fluid"); log(`Fluid v${made.v}: made before from these keyframes, words and seed: shown again, nothing runs`); }
      f.view = "result"; fluidUI(); render();
      return hud(`Fluid shot v${made.v} is already made from these keyframes and words. Ctrl+Enter tries another seed.`, 3000);
    }
  }
  cancel("fluid");
  const sig = fluidSig(), v = ++f.runs, dir = `paintaplate/${p.id}/fluid_v${v}`, size = [p.spec.width, p.spec.height], prompt = fluidPrompt($("#prompt").value);
  f.prompt = $("#prompt").value.trim();
  const t0 = performance.now();
  f.busy = { v, sig, progress: 0 };
  f.view = "keys";
  fluidUI(); render();
  try {
    const keys = [];
    for (const k of [...f.keys].sort((a, b) => a.frame - b.frame)) // the control video's keyframes: the paint on black, at the shot's size
      keys.push({ frame: k.frame, image: await uploadCanvas(snap(k.canvas, size, "#000"), `fluid_v${v}_key${k.frame}.png`) });
    log(`Fluid v${v}: ${keys.length} keyframe(s) at ${keys.map((k) => p.first + k.frame).join(", ")}, ${size.join(" x ")}, ${p.frames} frames at ${p.fps} fps, seed ${f.seed}, prompt "${prompt}"`);
    status(`Fluid shot v${v}: one LTX 2.5 pass with ainvfx-fluid`);
    const out = await run("fluid", { path: p.path, color_space: "sRGB", max_frames: p.frames, keys: JSON.stringify(keys), prompt, seed: f.seed,
      prefix: `${dir}/plate`, video_prefix: `${dir}/preview`, live: liveEvery() },
      { kind: "fluid", progress: (x) => { if (f.busy) { f.busy.progress = x; fluidUI(); } }, live: showLive }).done;
    f.result = { v, sig, seed: f.seed, prompt, path: `output:${dir}/plate/${p.spec.source.split(/[\\/]/).pop()}`, preview: viewUrl(outputFile("fluid", out, "video")) };
    (f.made ??= new Map()).set(sig, f.result);
    f.view = "result";
    f.busy = null;
    setShot(f.result.preview, "fluid");
    log(`Fluid v${v}: done in ${((performance.now() - t0) / 1000).toFixed(1)} s: ${(outputText("fluid", out, "plate") ?? "").split("\n")[0]}`);
    status(`Fluid shot v${v} is ready: Space plays it. Use as the plate to erase, paint or relight it; Ctrl+Enter tries another seed.`);
  } catch (err) {
    if (err?.message !== "cancelled") quiet(err);
  } finally {
    if (f.busy?.v === v) f.busy = null;
    fluidUI(); render();
  }
}

async function useFluid() { // the generated shot becomes the plate: erase, paint, relight and export work on it
  const f = S.fluid;
  if (!f?.result) return status("Generate the fluid shot first: Enter.");
  f.prompt = $("#prompt").value.trim();
  S.lastFluid = f;
  log(`Fluid v${f.result.v}: opened as the plate (${f.result.path})`);
  await openPlate([], f.result.path, "sRGB");
  status("The fluid shot is the plate: erase, paint or relight it, then Export. File > Back to the fluid keyframes returns to them.");
}

async function backToKeys() { // the blank plate again, with the keyframes, the words, the seed and the last result
  if (S.lastFluid) await openPlate([], S.lastFluid.blankPath, "sRGB", { fluid: { ...S.lastFluid } });
}

const blankForm = () => blankSpec({ width: $("#b-width").value, height: $("#b-height").value, fps: $("#b-fps").value, frames: $("#b-frames").value });

function blankNote() { // what the blank plate will be, snapped to what LTX and ainvfx-fluid take
  const s = blankForm();
  $("#b-note").textContent = `${s.width} × ${s.height}, ${s.frames} frames at ${s.fps} fps: ${(s.frames / s.fps).toFixed(2)} s.` +
    (s.frames === FLUID.tested ? "" : ` ${FLUID.tested} frames is the tested length.`) + (S.fluidReady ? "" : ` ${FLUID_MISSING}`);
  $("#blank-go").disabled = !S.fluidReady;
}

async function openBlank() { // a black canvas LTX and ainvfx-fluid take, then a fluid shot on it
  if (!S.fluidReady) return status(FLUID_MISSING);
  const spec = blankForm(), r = await post("/paintaplate/blank", spec);
  if (!r.ok) throw new Error(await r.text());
  const { path } = await r.json();
  $("#open").close();
  log(`Blank plate: ${spec.width} x ${spec.height}, ${spec.frames} frames at ${spec.fps} fps (${path})`);
  await openPlate([], path, "sRGB", { fluid: { blankPath: path } });
}

function fluidUI() { // the panel, the tools and the help of a fluid shot; none of it outside one
  const f = S.fluid, on = !!f;
  $("#fluid").hidden = !on;
  if (S.plate) $("#render").hidden = on;
  $("#history-empty").textContent = on ? FLUID_HELP : HISTORY_HELP;
  for (const t of ["erase", "light"]) $(`.tools [data-tool="${t}"]`).disabled = on;
  if (!on) return generateUI();
  const n = f.keys.length, busy = f.busy, r = f.result, stale = !!r && r.sig !== fluidSig();
  $("#spec").textContent = `Fluid shot on a blank plate: ${S.plate.spec.width} × ${S.plate.spec.height}, ${S.plate.fps} fps, ${S.plate.frames} frames`;
  $("#fluid-state").textContent = busy ? `generating ${Math.round((busy.progress ?? 0) * 100)}%`
    : r ? (stale ? "keyframes changed" : `v${r.v} ready`) : `${n} keyframe${n === 1 ? "" : "s"}`;
  $("#fluid-again").disabled = !n || !S.fluidReady;
  $("#fluid-use").disabled = !r || !!busy;
  generateUI();
}

// ---------- Edits: generate, keep, bypass, remove ----------

function queue(fn) {
  S.queued++;
  S.chain = S.chain.then(fn).catch(quiet).finally(() => { S.queued--; touch(); });
}

function launch(edit) { // Generate: the edit on the first frame, then its shot. A result it already has is used again
  if (S.draft === edit) S.draft = null;
  clearTimeout(S.prefetchTimer);
  if (!edit.strokes.length) return generateUI();
  takeInputs(edit);
  if (!S.edits.includes(edit)) S.edits.push(edit);
  edit.launched = performance.now();
  S.selected = edit; // it stays the current edit: new words, more strokes or the switch change it, until New edit or another tool
  S.peek = null;
  if (reuse(edit)) {
    log(`Edit ${num(edit)}: unchanged since a result it already has, so nothing runs again`);
    hud(`Edit ${num(edit)} has not changed: its result stays. Ctrl+Enter tries another seed.`, 3000);
    recompose(); historyUI(); render(); timelineUI();
    queue(regenerateDependents);
    return;
  }
  edit.state = "queued";
  edit.thumb ??= strokesThumb(edit);
  historyUI(); render();
  queue(() => generate(edit));
  queue(regenerateDependents); // the edits above it that saw it run again
}

function reuse(edit) { // a result made from the same strokes, words, seed and switch comes back without a pass
  const rec = recordOf(edit), same = edit.made === rec && !!edit.patch, hit = same ? null : edit.results?.get(rec);
  if (!same && !hit) return false;
  if (hit) Object.assign(edit, hit, { made: rec });
  Object.assign(edit, { state: "done", force: false, kept: undefined, preview: null, latent: null });
  return true;
}

function keep(edit) { // the result just made, kept by what made it
  const m = (edit.results ??= new Map());
  m.delete(edit.made);
  m.set(edit.made, { patch: edit.patch, version: edit.version, foot: edit.foot, basis: edit.basis, thumb: edit.thumb });
  while (m.size > RESULTS_KEPT) m.delete(m.keys().next().value);
}

async function regenerateDependents() {
  for (const e of [...S.edits]) if (e.on && e.state === "done" && needsRegen(e)) await generate(e);
  recompose(); historyUI(); render(); timelineUI();
}

function select(edit) { // a History row becomes the current edit: its words in the prompt field, its strokes on the frame
  if (edit && S.draft && S.draft !== edit) launch(S.draft); // the strokes in progress start before another edit is picked
  S.selected = edit;
  S.peek = edit; // frame 0 shows its strokes until playback starts or an edit is launched
  if (edit) { setTool(edit.tool); $("#prompt").value = edit.prompt; if (edit.tool === "erase") $("#whole").checked = !!edit.whole; }
  else if (!S.draft) $("#prompt").value = "";
  if (edit) hud(`Edit ${num(edit)} selected: retype its words, paint more or rub strokes out, then Generate. N starts a new edit.`, 3500);
  historyUI(); render();
}

function editingUI() { // the Editing tag and the New edit button: which edit new strokes and words change
  const e = S.selected ?? (S.edits.includes(S.draft) ? S.draft : null), tag = $("#editing");
  tag.hidden = !e;
  if (e) tag.textContent = `Editing ${num(e)} · ${NAME[e.tool]}`;
  $("#new-edit").disabled = !S.plate || !!S.fluid || (!S.draft && !S.selected);
  generateUI();
}

function nextEdit() { // New edit (N): the strokes in progress start now, and the next strokes make a separate edit
  if (!S.plate || S.fluid) return;
  if (S.draft) launch(S.draft);
  S.selected = null;
  $("#prompt").value = "";
  historyUI(); render();
  hud(`New edit: describe it, then paint. The tool stays ${NAME[S.tool]}.`, 2500);
}

function pickTool(t) { // the person picks a tool: another tool than the edit being worked on starts a new edit
  if (!S.fluid && toolEndsEdit({ draft: S.draft, current: S.selected }, t)) {
    if (S.draft) launch(S.draft);
    S.selected = null;
    $("#prompt").value = "";
    historyUI();
  }
  setTool(t);
}

function reopen(edit) { // the edit being generated, or waiting for its turn, changes: it stops and waits for Generate
  edit.token = (edit.token ?? 0) + 1;
  if (S.running === edit) { cancel("edit", "snap", "prefetch"); S.running = null; }
  cancel(...BACKGROUND);
  edit.state = "drawing"; edit.preview = edit.latent = null;
  edit.kept = edit.strokes.length;
  historyUI();
  return (S.draft = edit);
}

function activeBefore(edit) {
  return S.edits.slice(0, S.edits.indexOf(edit)).filter((e) => e.on && e.patch);
}

async function baseUpload(below, before, size) { // the frame under an edit, uploaded once per set of edits below it
  const key = `${below.map((e) => `${e.id}.${e.version}`).join(",") || "plate"}@${size}`;
  if (!S.uploads.has(key)) S.uploads.set(key, uploadCanvas(snap(before, size), `base_${S.uploads.size}.png`));
  return S.uploads.get(key);
}

async function generate(edit) {
  if (!S.edits.includes(edit) || !edit.on || edit.state === "drawing") return; // changed since it was queued: it waits for Generate
  const token = (edit.token = (edit.token ?? 0) + 1);
  const alive = () => edit.token === token && S.edits.includes(edit) && edit.on;
  const p = S.plate, light = edit.tool === "light", tag = `e${edit.id}_${token}`;
  cancel("warm"); // an edit never waits for the warm-up: what it needs loads now
  S.running = edit;
  edit.saw = activeBefore(edit).map(record); // the edits under it as it starts: a change to them restarts it (rebuild)
  Object.assign(edit, { state: "generating", preview: null, latent: null, shown: null });
  recompose(); historyUI(); render();
  log(`Edit ${num(edit)}: ${NAME[edit.tool]} "${edit.prompt || ""}", seed ${edit.seed}${edit.tool === "erase" ? `, whole object ${edit.whole ? "on" : "off"}` : ""}, ${painted(edit)} stroke${painted(edit) === 1 ? "" : "s"}, over ${edit.saw.length} edit${edit.saw.length === 1 ? "" : "s"}`);
  try {
    await edit.preparing; // the snap and the caption started when the strokes stopped: reused when nothing changed since
    if (!alive()) return;
    status(`Edit ${num(edit)}: ${NAME[edit.tool].toLowerCase()}, writing the prompt`);
    const { before, below, base, reference, cap } = await prepare(edit, S.edits.indexOf(edit), "edit");
    if (!alive()) return;
    const show = (b) => alive() && createImageBitmap(b).then((bm) => {
      if (!alive() || edit.preview) return;
      edit.latent = bm;
      edit.shown ??= performance.now();
      render();
    });
    // 1. A quick pass at preview size: its steps appear live inside the strokes. Paint may change a zone around them.
    status(`Edit ${num(edit)}: ${NAME[edit.tool].toLowerCase()}, first look`);
    const size = p.prev, values = { base, reference, start: light ? base : reference, caption: cap, seed: edit.seed,
      mask: await uploadCanvas(maskAt(edit, size), `${tag}_mask.png`), ...editSettings(edit, size, QUICK) };
    log(`Edit ${num(edit)}: Klein quick pass at ${size.join(" x ")}, ${QUICK.steps} steps`);
    const quick = await run("edit", values, { kind: "edit", front: true, preview: show, progress: (f) => editProgress(edit, f / 2) }).done;
    if (!alive()) return;
    edit.preview = await loadImage(viewUrl(outputFile("edit", quick, "patch")));
    edit.shown ??= performance.now();
    edit.latent = null; render();
    // 2. The same seed at full size, starting from the quick pass: it resolves in place.
    status(`Edit ${num(edit)}: ${NAME[edit.tool].toLowerCase()}, full size`);
    log(`Edit ${num(edit)}: Klein full-size pass at ${p.work.join(" x ")}, ${FULL.steps} steps from the quick result at denoise ${FULL.denoise}`);
    const work = p.work, start = snap(before, work);
    start.getContext("2d").drawImage(edit.preview, 0, 0, work[0], work[1]);
    const startName = await uploadCanvas(start, `${tag}_start.png`);
    const full = await run("edit", { ...values, base: await baseUpload(below, before, work), start: startName,
      // an erase refines the quick result, which has no object left: shown the original, Klein drew part of it back
      reference: edit.tool === "erase" ? startName : await uploadCanvas(editImage(edit, before, work), `${tag}_ref_full.png`),
      mask: await uploadCanvas(maskAt(edit, work), `${tag}_mask_full.png`), ...editSettings(edit, work, FULL),
      relight: light ? 1 : 0 }, { kind: "edit", front: true, progress: (f) => editProgress(edit, 0.5 + f / 2) }).done;
    if (!alive()) return;
    // a relight shows the frame as the export will make it: Klein's light on the plate's own detail
    edit.patch = await loadImage(viewUrl(outputFile("edit", full, light ? "relit" : "patch")));
    if (edit.tool === "erase") edit.patch = levelled(edit, edit.patch, snap(before, work));
    Object.assign(edit, { preview: null, latent: null, state: "done", version: ++S.vers, force: false, kept: undefined }); // versions are unique: a kept result never meets a new one
    edit.foot = footprint(edit);
    edit.basis = activeBefore(edit).map(record);
    edit.made = recordOf(edit); // the strokes, words, seed and switches this result came from: undo compares against it
    S.running = null;
    recompose();
    edit.thumb = thumbOf(edit);
    keep(edit);
    historyUI(); render(); timelineUI();
    status(`Edit ${num(edit)} is on the first frame. Its shot renders next.`);
    log(`Edit ${num(edit)}: done, ${((performance.now() - edit.launched) / 1000).toFixed(1)} s after it started`);
  } catch (err) {
    if (edit.token === token) {
      Object.assign(edit, { state: edit.patch ? "done" : "failed", preview: null, latent: null });
      S.running = null; recompose(); historyUI(); render();
    }
    if (err?.message !== "cancelled") throw explained(err, `Edit ${num(edit)}`);
  }
}


function editSettings(edit, size, pass) { // steps, denoise, and the growth and edge of the mask, for one Klein pass at `size`
  const zone = edit.tool === "paint"; // paint may change a zone around its strokes: room for an explosion and its glow
  return { steps: pass.steps, denoise: pass.denoise, grow: Math.round(size[0] / (zone ? PAINT_ZONE : EDIT_GROW)),
    ...(zone ? ZONE_SOFT : { feather: pass.feather, sigma: pass.sigma }) };
}

// What Klein's first pass needs: the whole object for an erase, the frame under the edit, and the caption. It runs when the
// strokes stop ("prefetch", cancelled by the next stroke) and again when the edit starts, which reuses what is still current.
async function prepare(edit, index, kind) {
  const below = (index < 0 ? S.edits : S.edits.slice(0, index)).filter((e) => e.on && e.patch), size = S.plate.prev;
  const before = layered(index < 0 ? S.edits.length : index);
  if (edit.tool === "erase" && !edit.whole && edit.sam) { edit.sam = null; edit.snapped = ""; redrawStrokes(edit); } // Whole object turned off: the strokes alone
  if (edit.tool === "erase" && edit.whole && edit.snapped !== snapKeyOf(edit)) {
    edit.sam = null; redrawStrokes(edit);
    await snapErase(edit, before, kind === "edit" ? "snap" : kind);
    edit.snapped = snapKeyOf(edit); // only once SAM has answered: a snap stopped half way, or new words, runs it again
  }
  const base = await baseUpload(below, before, size);
  const reference = await uploadCanvas(editImage(edit, before, size), `e${edit.id}_${painted(edit)}_ref.png`);
  const key = [edit.tool, edit.prompt, bounds(edit.mask), painted(edit), edit.sam ? 1 : 0, below.map((e) => `${e.id}.${e.version}`)].join("|");
  return { before, below, base, reference, cap: await captionFor(edit, reference, key, kind) };
}

// what a set of strokes is: tool, colour, size, and the points themselves (a sum, so two strokes of the same length differ)
const strokesSig = (strokes) => strokes.map((s) => `${s.tool}:${s.color ?? ""}:${Math.round(s.size)}:${s.points.length}:${Math.round(s.points.reduce((a, q) => a + q[0] * 3 + q[1], 0))}`).join(";");
const recordOf = (e) => JSON.stringify({ strokes: strokesSig(e.strokes), tool: e.tool, prompt: e.prompt, seed: e.seed, whole: !!e.whole });

function prefetch(edit) { // the snap and the prompt writer start as the strokes stop: by the time the edit starts, they are often done
  if (!edit || !painted(edit) || !S.plate) return;
  cancel("warm", "prefetch");
  edit.preparing = prepare(edit, S.edits.indexOf(edit), "prefetch").catch(() => {});
}

async function snapErase(edit, before, kind = "snap") { // one SAM request per strokes and words at a time: a second caller waits for it
  const key = snapKeyOf(edit);
  if (edit.snapping?.key === key) {
    try { return await edit.snapping.promise; } catch (err) { if (err?.message !== "cancelled" || kind === "prefetch") throw err; }
  }
  const promise = findWhole(edit, before, kind);
  edit.snapping = { key, promise };
  try { return await promise; } finally { if (edit.snapping?.promise === promise) edit.snapping = null; }
}

async function findWhole(edit, before, kind) { // SAM 3.1 finds the whole object under the erase strokes: by name, else point by point
  const size = S.plate.prev, k = size[0] / S.plate.work[0], area = size[0] * size[1];
  const pts = edit.strokes.filter((s) => s.tool !== "rub").flatMap((s) => s.points);
  const picks = [...new Set([0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * (pts.length - 1))))]; // up to five points, one prompt each
  const points = Object.fromEntries(picks.map((i, j) => [`point_${j}`, JSON.stringify([{ x: Math.round(pts[i][0] * k), y: Math.round(pts[i][1] * k) }])]));
  status(edit.prompt ? `Finding the ${edit.prompt} under the stroke` : "Finding the object under the stroke");
  const out = await run("snap", { image: await uploadCanvas(snap(before, size), `e${edit.id}_snap.png`), words: edit.prompt, ...points },
    { kind, front: true }).done;
  const bits = (c) => { // a mask canvas as 0 and 1 per pixel
    const d = c.getContext("2d").getImageData(0, 0, size[0], size[1]).data, m = new Uint8Array(area);
    for (let i = 0; i < area; i++) m[i] = d[i * 4] > 127 ? 1 : 0;
    return m;
  };
  const fileBits = async (f) => bits(snap(await loadImage(viewUrl(f)), size));
  const objects = pickObjects({ painted: bits(maskAt(edit, size)), area,
    named: await Promise.all(outputFiles("snap", out, "named").map(fileBits)),
    points: await Promise.all(picks.map((_, j) => outputFile("snap", out, `point_${j}`)).filter(Boolean).map(fileBits)) });
  log(`Edit ${num(edit)}: SAM 3.1 ${edit.prompt ? `found ${outputFiles("snap", out, "named").length - 1} object(s) named "${edit.prompt}", ` : ""}looked at ${picks.length} stroke point(s); ${objects.length} mask(s) kept`);
  if (!objects.length) return status("Erasing only what you painted: no single object under the stroke.");
  const sam = canvas(size), d = sam.getContext("2d"), img = d.createImageData(size[0], size[1]);
  for (let i = 0; i < area; i++) if (objects.some((m) => m[i])) img.data.fill(255, i * 4, i * 4 + 4);
  d.putImageData(img, 0, 0);
  edit.sam = snap(sam, [edit.mask.width, edit.mask.height]);
  redrawStrokes(edit);
  render();
}

function footprint(edit) { // where the edit changed the frame, on a coarse grid, one cell wider
  const w = 96, h = Math.max(1, Math.round((w * S.plate.work[1]) / S.plate.work[0])), bits = new Uint8Array(w * h);
  if (edit.tool === "light") return { w, h, bits: bits.fill(1) };
  const d = snap(edit.patch, [w, h]).getContext("2d").getImageData(0, 0, w, h).data;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (d[(y * w + x) * 4 + 3] <= 8) continue;
    for (let j = Math.max(0, y - 1); j <= Math.min(h - 1, y + 1); j++)
      for (let i = Math.max(0, x - 1); i <= Math.min(w - 1, x + 1); i++) bits[j * w + i] = 1;
  }
  return { w, h, bits };
}

const record = (e) => ({ id: e.id, version: e.version, tool: e.tool, foot: e.foot });
const needsRegen = (edit) => dependsOnChange(edit, activeBefore(edit).map(record), edit.basis);

function rebuild() { // after a bypass, a removal or another try: make again only what depends on the change
  cancel(...BACKGROUND);
  const r = S.running; // an edit being generated whose base changed, or which is to run again, stops now: its pass would be thrown away
  if (r && (r.force || !S.edits.includes(r) || !r.on || dependsOnChange(r, activeBefore(r).map(record), r.saw ?? []))) { log(`Edit ${num(r)}: its pass is stopped, it runs again`); stopEdit(r); }
  recompose(); historyUI(); render();
  queue(async () => {
    for (const e of [...S.edits]) {
      if (!e.on || e.state === "drawing" || e.state === "queued") continue;
      if (!e.patch || e.force || needsRegen(e)) await generate(e);
    }
    recompose(); historyUI(); render(); timelineUI();
  });
}

function toggle(edit) {
  mark();
  edit.on = !edit.on;
  if (!edit.on && S.running === edit) stopEdit(edit);
  status(edit.on ? `Edit ${num(edit)} is back on.` : `Edit ${num(edit)} is bypassed.`);
  rebuild();
}

function removeEdit(edit) {
  const i = S.edits.indexOf(edit);
  if (i < 0) return;
  mark();
  const n = num(edit);
  if (S.running === edit) stopEdit(edit);
  if (S.draft === edit) S.draft = null;
  if (S.hover === edit) S.hover = null; // its row is gone before the pointer leaves it: its strokes must go too
  if (S.selected === edit) select(null);
  S.edits.splice(i, 1);
  status(`Edit ${n} removed. Ctrl+Z brings it back.`);
  rebuild();
}

function again(edit) { // a new seed for one edit; the edits above it follow if they depend on it
  if (!edit.strokes.length || edit.state === "drawing") return;
  mark();
  Object.assign(edit, { seed: (Math.random() * 2 ** 31) | 0, on: true, force: true, launched: performance.now() });
  status(`Edit ${num(edit)}: another try, seed ${edit.seed}.`);
  rebuild();
}

function stopEdit(edit) {
  edit.token = (edit.token ?? 0) + 1;
  cancel("edit", "snap", "prefetch");
  if (S.running === edit) S.running = null;
}

// ---------- Undo and redo: every change to the edits is one step, back and forth ----------
// A step is a snapshot of the edits in order, each with its strokes, words, seed and switches, plus the strokes in
// progress. Undo restores the snapshot; an edit whose result no longer matches its strokes, words or seed is made again.

function snapshot() {
  const rec = (e) => ({ e, strokes: e.strokes.slice(), prompt: e.prompt, seed: e.seed, on: e.on, whole: !!e.whole });
  return { edits: S.edits.map(rec), draft: S.draft ? rec(S.draft) : null,
    keys: S.fluid ? S.fluid.keys.map((k) => ({ k, frame: k.frame, strokes: k.strokes.slice() })) : null };
}

function mark() { // call before a change: the state undo comes back to
  S.past.push(snapshot());
  if (S.past.length > UNDO_MAX) S.past.shift();
  S.future = [];
  undoUI();
}

function restore(snap) {
  clearTimeout(S.prefetchTimer);
  cancel(...BACKGROUND, "edit", "snap", "prefetch", "warm");
  for (const e of [...S.edits, S.draft].filter(Boolean)) if (e.state === "generating" || e.state === "queued") e.token = (e.token ?? 0) + 1;
  const kept = S.selected; // the current edit stays current while it exists: the next strokes still change it
  Object.assign(S, { running: null, draft: null, hover: null, selected: null });
  const apply = ({ e, strokes, prompt, seed, on, whole }) => {
    const same = strokes.length === e.strokes.length && strokes.every((st, i) => st === e.strokes[i]);
    Object.assign(e, { prompt, seed, on, whole });
    if (!same) { e.strokes = strokes.slice(); e.sam = null; e.snapped = ""; e.caption = null; redrawStrokes(e); }
    if (e.tool === "erase" && e.whole && !e.sam) e.snapped = "";
    return e;
  };
  S.edits = snap.edits.map(apply);
  for (const e of S.edits) { // a result that matches, or one made before from the same strokes and words, is kept; rebuild() makes the rest
    const current = e.patch && (e.made === recordOf(e) || reuse(e));
    e.force = !!e.patch && !current;
    e.state = e.patch ? "done" : "generating";
    if (!e.strokes.length) e.state = "done"; // nothing left to make: rebuild skips it
  }
  if (snap.draft) { S.draft = apply(snap.draft); S.draft.state = "drawing"; $("#prompt").value = S.draft.prompt; if (painted(S.draft)) prepareSoon(); }
  S.edits = S.edits.filter((e) => e.strokes.length); // an edit undone to no strokes at all is gone
  if (!S.draft && S.edits.includes(kept)) { S.selected = kept; $("#prompt").value = kept.prompt; }
  else if (!S.draft && !S.fluid) $("#prompt").value = ""; // in a fluid shot the words belong to the shot, not to an edit
  if (snap.keys && S.fluid) { // a fluid shot's keyframes: their frames and strokes as they were
    S.fluid.keys = snap.keys.map(({ k, frame, strokes }) => {
      const same = strokes.length === k.strokes.length && strokes.every((st, i) => st === k.strokes[i]);
      k.frame = frame;
      if (!same) { k.strokes = strokes.slice(); redrawKey(k); }
      return k;
    });
    S.keyDraft = null;
    staleFluid(); render();
  }
  undoUI();
  rebuild();
}

function undo() {
  if (!S.past.length) return status("Nothing to undo.");
  S.future.push(snapshot());
  restore(S.past.pop());
  status(`Undone. ${S.past.length} step${S.past.length === 1 ? "" : "s"} further back, Ctrl+Shift+Z redoes.`);
}

function redo() {
  if (!S.future.length) return status("Nothing to redo.");
  S.past.push(snapshot());
  restore(S.future.pop());
  status(`Redone. ${S.future.length} step${S.future.length === 1 ? "" : "s"} further ahead.`);
}

function undoUI() {
  $("#undo-btn").disabled = !S.past.length;
  $("#redo-btn").disabled = !S.future.length;
}

function discard() { // Esc: drop the strokes in progress, or stop the edit being generated
  clearTimeout(S.prefetchTimer);
  const d = S.draft ?? S.running;
  if (!d) return S.selected && select(null);
  mark();
  stopEdit(d);
  if (S.draft === d) S.draft = null;
  if (d.patch) { // it had a result: go back to it
    if (d.kept !== undefined) { d.strokes.length = d.kept; redrawStrokes(d); d.snapped = snapKeyOf(d); }
    Object.assign(d, { state: "done", preview: null, latent: null, force: false, kept: undefined });
    status("Cancelled. The edit keeps its last result.");
  } else {
    const i = S.edits.indexOf(d);
    if (i >= 0) S.edits.splice(i, 1);
    status("Edit cancelled");
  }
  recompose(); historyUI(); render(); touch();
}

// ---------- History ----------

const ICON = {
  eye: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  off: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 3l18 18M10.6 5.1A10 10 0 0 1 12 5c6.5 0 10 7 10 7a17 17 0 0 1-3.2 4.1M6.6 6.6A17 17 0 0 0 2 12s3.5 7 10 7a9.7 9.7 0 0 0 5.4-1.6M9.9 9.9a3 3 0 0 0 4.2 4.2"/></svg>',
  again: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M20 12a8 8 0 1 1-2.3-5.6M20 4v4h-4"/></svg>',
  del: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M6 6l12 12M18 6L6 18"/></svg>',
};
const STATE = { drawing: "Drawing", queued: "Waiting", generating: "Generating", failed: "Failed: try again" };

function thumbOf(edit) { // the frame after this edit, cropped to where it changed
  const c = layered(S.edits.indexOf(edit) + 1), f = edit.foot;
  let [x0, y0, x1, y1] = [f.w, f.h, -1, -1];
  for (let y = 0; y < f.h; y++) for (let x = 0; x < f.w; x++) if (f.bits[y * f.w + x]) { x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y); }
  const t = canvas([120, 80]), k = c.width / f.w;
  if (x1 < 0 || edit.tool === "light") { t.getContext("2d").drawImage(c, 0, 0, 120, 80); return t.toDataURL("image/jpeg", 0.8); }
  let [cx, cy, cw, ch] = [x0 * k, y0 * k, (x1 - x0 + 1) * k, (y1 - y0 + 1) * k];
  const want = Math.max(cw, (ch * 3) / 2) * 1.4; // 3:2, with a margin
  [cw, ch] = [Math.min(c.width, want), Math.min(c.height, (want * 2) / 3)];
  cx = Math.max(0, Math.min(c.width - cw, cx + (x1 - x0 + 1) * k / 2 - cw / 2));
  cy = Math.max(0, Math.min(c.height - ch, cy + (y1 - y0 + 1) * k / 2 - ch / 2));
  t.getContext("2d").drawImage(c, cx, cy, cw, ch, 0, 0, 120, 80);
  return t.toDataURL("image/jpeg", 0.8);
}

function strokesThumb(edit) { // the frame with the strokes, until the edit has a result
  const t = canvas([120, 80]), x = t.getContext("2d");
  x.drawImage(S.hero, 0, 0, 120, 80);
  if (edit.tool === "erase") { x.globalAlpha = 0.6; x.drawImage(whiteOf(edit.mask, "#ff5040"), 0, 0, 120, 80); }
  else x.drawImage(edit.paint, 0, 0, 120, 80);
  return t.toDataURL("image/jpeg", 0.8);
}

function historyUI() {
  editingUI();
  const list = $("#history");
  $("#history-empty").hidden = S.edits.length > 0;
  list.replaceChildren(...[...S.edits].reverse().map((e) => {
    const li = document.createElement("li");
    li.dataset.id = e.id;
    li.className = [e.on ? "" : "off", e.state === "generating" || e.state === "queued" || e.state === "drawing" ? "busy" : "",
      e.state === "failed" ? "failed" : "", S.selected === e ? "selected" : ""].join(" ").trim();
    li.innerHTML = `<img class="thumb" alt=""><div class="what"><span class="title"></span><small></small></div>
      <div class="acts"><button class="eye" aria-pressed="${e.on}" title="${e.on ? "Bypass this edit" : "Turn this edit back on"}">${e.on ? ICON.eye : ICON.off}</button>
      <button class="again" title="Try another">${ICON.again}</button><button class="del" title="Remove this edit">${ICON.del}</button></div>`;
    const img = li.querySelector(".thumb");
    if (e.thumb) img.src = e.thumb; else img.removeAttribute("src");
    li.title = "Select this edit: its words come back; retype them, paint more or rub strokes out, and it runs again";
    li.querySelector(".title").textContent = `${num(e)}. ${NAME[e.tool]}`;
    const what = e.tool === "erase" ? (e.whole ? "Whole object" : "Painted area") : e.prompt || (e.tool === "light" ? "From the strokes" : "No words");
    const small = li.querySelector("small");
    if (STATE[e.state] && e.on) {
      small.innerHTML = '<span class="state"></span>';
      small.firstChild.textContent = STATE[e.state];
    } else small.textContent = e.on ? what : `Bypassed: ${what}`;
    small.title = e.caption?.text ? `What Klein received: ${e.caption.text}` : what;
    li.querySelector(".eye").onclick = () => toggle(e);
    li.querySelector(".again").onclick = () => again(e);
    li.querySelector(".del").onclick = () => removeEdit(e);
    li.querySelector(".again").disabled = e.state === "drawing" || !e.strokes.length;
    li.onmouseenter = () => { S.hover = e; render(); };
    li.onmouseleave = () => { S.hover = null; render(); };
    li.onclick = (ev) => { if (!ev.target.closest("button")) { pause(); seek(0); select(S.selected === e ? null : e); } };
    return li;
  }));
  undoUI();
  exportUI(); timelineUI();
}

function editProgress(edit, f) { // the state line of one History row, without rebuilding the list
  const el = $(`#history li[data-id="${edit.id}"] .state`);
  if (el) el.textContent = `Generating ${Math.round(f * 100)}%`;
}

// ---------- In idle time: the shot, its mattes, the composite to play, then the export ----------

let idleTimer;
function touch(ms = IDLE_MS) { clearTimeout(idleTimer); idleTimer = setTimeout(idle, ms); }

function idle() { // one pipeline at a time: a running one goes on, unless the set of edits changed under it
  if (!S.plate) return;
  if ((S.draft && S.edits.includes(S.draft)) || S.running || S.queued) return touch(); // an edit of this render changes; a new edit being painted lets it run
  if (S.piping) { if (S.shotDirty && S.piping !== S.heroKey) cancel(...BACKGROUND); return; }
  const r = S.renders.get(S.heroKey);
  if (!S.shotDirty && !((S.background || S.wantDownload) && S.heroKey && !r?.exported)) return;
  S.piping = S.heroKey || "-";
  pipeline().catch((e) => {
    if (e?.message === "cancelled") S.shotDirty = true;
    else { const st = STAGES.find((x) => x.id === S.stage?.id); quiet(explained(e, st?.label ?? "The render")); S.stage = null; S.wantDownload = null; stagesUI(); exportUI(); generateUI(); }
  }).finally(() => { S.piping = null; touch(); });
}

const liveEvery = () => (S.vram >= LIVE.vram ? LIVE.every : 0); // steps between live previews, 0 for none
const grow = (w, erase) => Math.max(4, Math.round(w / (erase ? COMPOSITE_GROW.erase : COMPOSITE_GROW.other))); // pixels at width w
const feather = (w) => Math.max(6, Math.round(w / COMPOSITE_FEATHER));

// Every step of a render, in order. `final` steps make the export; they run after the preview when the export is
// prepared in the background, or when Export asks for them.
// `preview` steps are made once per preview size, so going back to a size plays what it made at once.
const STAGES = [
  { id: "erase", label: "Track the erase", ref: 6 }, { id: "clean", label: "Erase pass", ref: 10, preview: true },
  { id: "shot", label: "Shot", ref: 20, preview: true }, { id: "track", label: "Track the paint", ref: 5, preview: true },
  { id: "comp", label: "Composite", ref: 14, preview: true },
  { id: "cleanfull", label: "Erase pass at full size", ref: 32, final: true }, { id: "full", label: "Shot at full size", ref: 45, final: true },
  { id: "trackfull", label: "Track at full size", ref: 5, final: true }, { id: "export", label: "Export", ref: 18, final: true },
];
const previewOf = (r) => r?.previews?.[S.plate.shot.join("x")]; // what this preview size made for a set of edits
const doneOf = (r, st) => (st.preview ? previewOf(r) : r)?.done?.[st.id]; // seconds a step took, if it ran
S.took = {}; // measured seconds per step, for this plate: the next estimates use them

function plan(r, active) { // the steps this set of edits needs: the erase pass for erases, Ripple for paint and light, no second size when the preview is full size
  const p = S.plate, [sw, sh] = p.shot, onePass = sw === p.work[0] && sh === p.work[1];
  const erase = active.some((e) => e.tool === "erase"), paint = active.some((e) => e.tool === "paint"), carry = active.some((e) => e.tool !== "erase");
  r.skip = new Set([!erase && "erase", !erase && "clean", !carry && "shot", !paint && "track", (onePass || !erase) && "cleanfull",
    (onePass || !carry) && "full", (onePass || !paint) && "trackfull"].filter(Boolean));
  return r;
}

function estimate(id) { // seconds: what this step took last time, or a measured reference scaled to this plate
  if (S.took[id]) return S.took[id];
  const p = S.plate, ref = 928 * 512 * 97;
  const big = ["full", "cleanfull", "export"].includes(id);
  const size = big ? p.work : ["erase", "track", "trackfull"].includes(id) ? p.track : p.shot;
  const scale = (size[0] * size[1] * p.frames) / ref * (big ? 0.73 : 1);
  return STAGES.find((x) => x.id === id).ref * Math.max(0.25, scale);
}

async function step(r, id, work, store = r) { // run one step of a render, timed and shown; preview steps keep their result per size
  if (store.done?.[id] !== undefined || r.skip?.has(id)) return;
  const t0 = performance.now();
  S.stage = { key: S.heroKey, id, progress: 0, t0 };
  stagesUI();
  log(`Render v${r.v}: ${STAGES.find((x) => x.id === id).label} (about ${Math.round(estimate(id))} s)`);
  await work((f) => { if (S.stage?.id === id) { S.stage.progress = f; stagesUI(); } });
  const dt = (performance.now() - t0) / 1000;
  (store.done ??= {})[id] = dt;
  S.took[id] = dt;
  S.stage = null;
  log(`Render v${r.v}: ${STAGES.find((x) => x.id === id).label} took ${dt.toFixed(1)} s`);
  stagesUI();
}

function reused(r, store, id, take) { // a step that a render with the same erases made already: its result is used again
  if (store.done?.[id] !== undefined) return;
  take();
  (store.done ??= {})[id] = 0;
  log(`Render v${r.v}: ${STAGES.find((x) => x.id === id).label}: made by an earlier render with the same erases, used again`);
}

async function pipeline() {
  S.shotDirty = false;
  cancel(...BACKGROUND, "warm");
  const p = S.plate, key = S.heroKey, active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
  if (!key || !active.length) return;
  const fresh = () => key === S.heroKey;
  let r = S.renders.get(key);
  if (!r) { r = { v: ++S.run, previews: {} }; r.base = `paintaplate/${p.id}/v${r.v}`; S.renders.set(key, r); }
  plan(r, active);
  const [sw, sh] = p.shot, sized = `${sw}x${sh}`, pv = (r.previews[sized] ??= {}), base = r.base;
  const relight = active.some((e) => e.tool === "light"), erases = active.filter((e) => e.tool === "erase"), erase = erases.length > 0;
  const carry = active.some((e) => e.tool !== "erase"); // paint and light: Ripple carries them through the shot
  // what the erases make depends on the erases alone: kept by them, so a render with the same erases uses it again (a paint
  // added over an erase tracked and cleaned it all a second time, 28 Oct)
  const ekey = erases.map((e) => `${e.id}.${e.version}`).join(",");
  const E = erase ? S.erases.get(ekey) ?? S.erases.set(ekey, { sizes: {} }).get(ekey) : null;
  r.hero ??= await uploadCanvas(S.hero, `hero_v${r.v}.png`);
  if (erase) r.clean0 ??= E.clean0 ??= await uploadCanvas(layered(S.edits.length, (e) => e.tool === "erase"), `clean_v${r.v}.png`);
  const common = { color_space: p.cs, max_frames: p.frames, seed: active[0].seed };
  const prompt = shotPrompt(active.map((e) => ({ tool: e.tool, words: e.prompt })));
  const scene = erase ? erasePrompt(erases.map((e) => e.caption?.text)) : ""; // the scene as it stays, never the erased object
  log(`Render v${r.v}: ${active.length} edit(s) (${active.map((e) => `${num(e)} ${NAME[e.tool]}`).join(", ")}), preview at ${sized}, seed ${common.seed}, steps: ${STAGES.filter((st) => !r.skip.has(st.id)).map((st) => st.id).join(" > ")}`);
  if (carry) log(`Render v${r.v}: LTX prompt: ${prompt}`);
  if (erase) log(`Render v${r.v}: erase pass prompt: ${scene || "none"}`);
  // the erase is tracked on the plate first: the erase pass regenerates its areas, the composite keeps them
  if (E?.erased) reused(r, r, "erase", () => { r.erased = E.erased; });
  await step(r, "erase", async (progress) => { r.erased = E.erased = await track(active, null, base, "", progress, null, ["erase"]); });
  const cleanAt = async (size, progress, live) => { // the erase pass at `size`, kept by the erases: a preview, or the full size's first stage
    const at = `${size[0]}x${size[1]}`, kept = (E.sizes[at] ??= {});
    if (kept.clean) return kept;
    const out = await run("clean", { ...common, seed: erases[0].seed, path: p.path, hero: r.clean0, hole: r.erased.found.matte_a, prompt: scene,
      width: size[0], height: size[1], prefix: `${base}/${at}/clean/f`, video_prefix: `${base}/${at}/clean`, live: live ? liveEvery() : 0 },
      { kind: "clean", progress, live: live ? showLive : null }).done;
    return Object.assign(kept, { clean: `output:${base}/${at}/clean`, raw: viewUrl(outputFile("clean", out, "video")) });
  };
  const passes = async (store, size, dir, final) => { // the erase pass makes a clean plate; Ripple carries paint and light over it
    const id = final ? "cleanfull" : "clean", kept = erase && (final ? E.full : E.sizes[`${size[0]}x${size[1]}`]);
    if (kept?.clean) reused(r, store, id, () => Object.assign(store, { clean: kept.clean, raw: kept.raw }));
    await step(r, id, async (progress) => {
      if (!final) return void Object.assign(store, await cleanAt(size, progress, true));
      // at full size, Lightricks' two stages: the erase pass at half the working size (the preview's own when it is that size),
      // then 2 steps at full size from it, without the reference video. 8 steps at full size took 181 s on a 1080p plate (28 Oct)
      const low = stageOne(p.work), first = await cleanAt(low, (f) => progress(f / 2), false);
      log(`Render v${r.v}: erase pass at full size, 2 steps from the erase pass at ${low.join(" x ")}`);
      const out = await run("cleanup", { ...common, seed: erases[0].seed, path: p.path, hero: r.clean0, hole: r.erased.found.matte_a, prompt: scene,
        low: first.clean, width: size[0], height: size[1], prefix: `${base}/${dir}/clean/f`, video_prefix: `${base}/${dir}/clean` },
        { kind: "clean", progress: (f) => progress(0.5 + f / 2) }).done;
      E.full = { clean: `output:${base}/${dir}/clean`, raw: viewUrl(outputFile("cleanup", out, "video")) };
      Object.assign(store, E.full);
    }, store);
    await step(r, final ? "full" : "shot", async (progress) => {
      const plate = erase ? { path: store.clean, color_space: "sRGB" } : { path: p.path };
      const out = await run("shot", { ...common, ...plate, hero: r.hero, prompt, width: size[0], height: size[1],
        prefix: `${base}/${dir}/shot/f`, video_prefix: `${base}/${dir}/raw`, live: final ? 0 : liveEvery() },
        { kind: "shot", progress, live: final ? null : showLive }).done;
      store.shot = `output:${base}/${dir}/shot`;
      store.raw = viewUrl(outputFile("shot", out, "video"));
    }, store);
    return carry ? store.shot : store.clean;
  };
  const made = await passes(pv, p.shot, sized, false);
  if (!fresh()) return;
  if (!pv.comp && !r.review && S.shot?.url !== pv.raw) { // a rough look at once: the whole frame as the model made it, until the composite
    setShot(pv.raw, key);
    hud("Rough preview: Space plays it. The composite follows.", 2500);
  }
  await step(r, "track", async (progress) => { pv.painted = await track(active, made, base, `_${sized}`, progress, null, ["paint"],
    erase ? { path: pv.clean, cs: "sRGB" } : { path: p.path, cs: p.cs }); }, pv);
  pv.mattes = mattesOf({ ...r.erased?.found, ...pv.painted?.found });
  if (!fresh()) return;
  await step(r, "comp", async (progress) => {
    const comp = await run("comp", { path: p.path, color_space: p.cs, max_frames: p.frames, width: sw, height: sh, shot: made,
      ...pv.mattes.values, relight, grow: grow(sw, erase), feather: feather(sw), grain: 0, video_prefix: `${base}/${sized}/comp` },
      { kind: "comp", progress }).done;
    pv.comp = viewUrl(outputFile("comp", comp, "video"));
  }, pv);
  if (!fresh()) return;
  if (!r.review && S.shot?.url !== pv.comp) {
    setShot(pv.comp, key);
    hud("The edited shot is ready: Space plays it", 2500);
    status(S.background ? "The edited shot is ready. The export is prepared next, at full quality."
      : "The edited shot is ready. Export renders it at full quality when you need it.");
  }
  if (!S.background && !S.wantDownload) return stagesUI();
  const onePass = sw === p.work[0] && sh === p.work[1];
  const final = onePass ? made : await passes(r, p.work, "full", true);
  if (!fresh()) return;
  if (!onePass && !r.review && r.raw && S.shot?.url !== r.raw) { // the full-size shot as LTX made it, until the export is ready:
    setShot(r.raw, key); // the preview size can lose an effect that the full size keeps (a fire faded by 85% at 640, 28 Oct)
    hud("Full size: Space plays the shot as LTX made it. The export follows.", 2500);
    log(`Render v${r.v}: the viewer plays the full-size shot until the export is ready`);
  }
  await step(r, "trackfull", async (progress) => { r.full = await track(active, final, base, "_full", progress, pv.mattes, ["paint"],
    erase ? { path: onePass ? pv.clean : r.clean, cs: "sRGB" } : { path: p.path, cs: p.cs }); });
  r.full ??= pv.mattes;
  if (!fresh()) return;
  await step(r, "export", async (progress) => {
    const done = await run("export", { path: p.path, color_space: p.cs, max_frames: p.frames, shot: final, ...r.full.values, relight,
      keep_untouched: !relight, prefix: `${base}/export`, matte_prefix: `${base}/matte/matte`, review_prefix: `${base}/review`,
      grow: grow(p.spec.width, erase), feather: feather(p.spec.width) }, { kind: "export", progress }).done;
    r.exported = { run: base, name: `${p.name}_paintaplate_v${r.v}`, text: outputText("export", done, "export") ?? "" };
    r.review = viewUrl(outputFile("export", done, "review"));
  });
  if (!fresh()) return;
  S.exported = r.exported;
  setShot(r.review, key);
  hud("Full size: the viewer now plays the export", 2500);
  stagesUI(); exportUI();
  status(`Exported to the output folder: ${S.exported.text.split("\n")[0]}.`);
  log(`Export v${r.v}: ${S.exported.text.replace(/\n/g, "; ")}`);
  if (S.wantDownload) { const parts = S.wantDownload; S.wantDownload = null; download(parts); }
}

function elementOf(zones, size) { // where the edits changed the first frame, inside the paint zones: the paint matte starts here
  const [w, h] = size, data = (c) => c.getContext("2d").getImageData(0, 0, w, h).data;
  const bits = changedMask(data(snap(S.hero, size)), data(snap(S.original, size)), data(zones), FOLLOW.seed);
  const c = canvas(size), x = c.getContext("2d"), img = x.createImageData(w, h);
  for (let i = 0; i < w * h; i++) img.data.fill(bits[i] ? 255 : 0, i * 4, i * 4 + 3), (img.data[i * 4 + 3] = 255);
  x.putImageData(img, 0, 0);
  return c;
}

async function track(active, shotPath, base, suffix, progress, previous, tools, under = null) { // SAM 3.1 follows a kind of edit through the shot; `under`: the plate the shot was made over
  const p = S.plate, found = { ...(previous?.found ?? {}) };
  for (const [key, tool, path, cs] of [["matte_a", "erase", p.path, p.cs], ["matte_b", "paint", shotPath, "sRGB"]]) {
    const edits = active.filter((e) => e.tool === tool);
    if (!edits.length || !tools.includes(tool)) continue; // the erase follows the plate; the paint follows the shot
    const size = tool === "erase" ? p.trackErase : p.track, [sw, sh] = size;
    const union = canvas(size), u = union.getContext("2d");
    u.fillStyle = "#000"; u.fillRect(0, 0, sw, sh);
    u.globalCompositeOperation = "lighten";
    for (const e of edits) u.drawImage(tool === "paint" ? whiteOf(e.patch) : e.mask, 0, 0, sw, sh);
    const compare = tool === "paint" && under ? { base: under.path, base_color_space: under.cs } : {}; // the paint matte follows what the shot changed
    if (tool === "paint") compare.seed = await uploadCanvas(elementOf(union, size), `seed${suffix}_${S.run}.png`); // from what the edits changed
    const out = await run("matte", { path, color_space: cs, max_frames: p.frames, width: sw, height: sh, prefix: `${base}/${key}${suffix}/m`,
      mask: await uploadCanvas(union, `${key}${suffix}_${S.run}.png`), zone: FOLLOW.zone, threshold: FOLLOW.threshold, ...compare },
      { kind: "matte", progress }).done;
    const note = outputText("matte", out, "follow");
    if (note) log(`${tool === "erase" ? "Erase" : "Paint"} matte${suffix ? ` (${suffix.slice(1)})` : ""}: ${note}`);
    found[key] = `output:${base}/${key}${suffix}`;
  }
  return mattesOf(found);
}

function mattesOf(found) { // a missing matte is the other one again: the workflows take both
  const a = found.matte_a ?? found.matte_b, b = found.matte_b ?? found.matte_a;
  return { found, any: !!a, values: { matte_a: a ?? "", matte_b: b ?? "" } };
}

const PARTS = { export: "the result in the plate's format", matte: "its matte", review: "a review movie", shot: "the regenerated shot" };

function download(parts = ["export", "matte"]) {
  const a = Object.assign(document.createElement("a"), {
    href: `/paintaplate/download?${new URLSearchParams({ run: S.exported.run, name: S.exported.name, parts: parts.join(",") })}`,
    download: `${S.exported.name}.zip` });
  document.body.append(a); a.click(); a.remove();
  const what = parts.map((k) => PARTS[k]);
  status(`Downloading ${S.exported.name}.zip: ${what.slice(0, -1).join(", ")}${what.length > 1 ? " and " : ""}${what.at(-1)}.`);
}

// ---------- Interface ----------

function explained(err, what) { // ComfyUI's own message goes to the log; the status line says what failed, why, and what to do
  if (err?.message === "cancelled") return err;
  const raw = err?.message ?? String(err);
  log(`${what} failed. ComfyUI said: ${raw}`, "error");
  return new Error(`${what} failed: ${plainError(raw)} Generate tries again.`);
}

function status(text, level = "") { // the status line, and a line in the log
  $("#status").textContent = text;
  log(text, level);
}

function log(text, level = "") { // the log panel only: what happens under the hood, with the time
  const li = document.createElement("li");
  li.className = level;
  li.innerHTML = "<time></time><span></span>";
  li.firstChild.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  li.lastChild.textContent = text;
  const list = $("#log");
  list.append(li);
  while (list.children.length > 400) list.firstChild.remove();
  list.scrollTop = list.scrollHeight;
  if (level === "error" && list.hidden) $("#log-btn").classList.add("alert"); // an error while the log is closed: the button says so
}

function renderLeft(finalToo = false) { // seconds until the preview (or the export) is ready, from the steps still to run
  const p = S.plate, r = S.renders.get(S.heroKey);
  if (!p || !S.heroKey || (finalToo ? r?.exported : previewOf(r)?.comp || r?.review)) return 0;
  const active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
  const skip = r?.skip ?? plan({}, active).skip;
  let t = 0;
  for (const st of STAGES) {
    if (st.final && !finalToo) break;
    if (skip.has(st.id) || doneOf(r, st) !== undefined) continue;
    const est = estimate(st.id);
    if (S.stage?.id === st.id && S.stage.key === S.heroKey) {
      const run = (performance.now() - S.stage.t0) / 1000, f = S.stage.progress;
      t += f > 0.05 ? Math.max(0, run * (1 - f) / f) : Math.max(est - run, est * 0.2);
    } else t += est;
  }
  return t;
}

function stagesUI() { // the Render panel: every step, done, running or waiting, and the time left
  const list = $("#stages"), p = S.plate, r = S.renders.get(S.heroKey);
  const active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
  $("#render").hidden = !p || !!S.fluid;
  list.hidden = !active.length;
  if (!p || !active.length) { $("#render-left").textContent = ""; return timelineBar(); }
  const skip = r?.skip ?? plan({}, active).skip, waiting = !S.background && !S.wantDownload;
  list.replaceChildren(...STAGES.filter((st) => !skip.has(st.id)).map((st) => {
    const li = document.createElement("li"), took = doneOf(r, st);
    const now = S.stage?.id === st.id && S.stage.key === S.heroKey;
    li.className = took !== undefined ? "done" : now ? "now" : st.final && waiting ? "later" : "";
    li.innerHTML = '<span class="dot"></span><span class="name"></span><span class="time"></span>';
    li.children[1].textContent = st.label;
    li.children[2].textContent = took !== undefined ? `${Math.round(took)} s` : now ? `${Math.round(S.stage.progress * 100)}%`
      : st.final && waiting ? "on Export" : `~${Math.round(estimate(st.id))} s`;
    return li;
  }));
  const pre = renderLeft(), all = renderLeft(true);
  const busy = S.stage?.key === S.heroKey;
  $("#render-left").textContent = stale() || !(previewOf(r)?.comp || r?.review) ? (pre ? `preview ${secs(pre)}` : busy ? "preview almost ready" : "")
    : r?.exported ? "export ready" : waiting ? "preview ready" : all ? `export ${secs(all)}` : busy ? "export almost ready" : "";
  timelineBar();
}

function timelineBar() { // the line under the timeline: the preview in gold, then the export in grey, green when exported
  const bar = $("#tl-render"), r = S.renders.get(S.heroKey);
  bar.className = "tl-render";
  if (!S.plate || !S.heroKey || !r) { bar.style.width = "0"; if (S.heroKey && stale()) bar.classList.add("stale"); return; }
  const steps = STAGES.filter((st) => !r.skip?.has(st.id) && (!st.final || S.background || S.wantDownload || r.exported));
  const total = steps.reduce((a, st) => a + estimate(st.id), 0);
  let done = steps.reduce((a, st) => a + (doneOf(r, st) !== undefined ? estimate(st.id) : 0), 0);
  if (S.stage?.key === S.heroKey) done += estimate(S.stage.id) * S.stage.progress;
  bar.style.width = `${Math.round((done / Math.max(1, total)) * 100)}%`;
  if (r.exported) bar.classList.add("ready");
  else if (previewOf(r)?.comp) bar.classList.add("export");
}

function timelineUI() {
  const p = S.plate;
  if (!p) return;
  const n = p.frames, pos = (f) => `${((f + 0.5) / n) * 100}%`;
  $("#tl-head").style.left = pos(S.frame);
  const r = $("#tl-range");
  r.style.left = `${(S.inPt / n) * 100}%`;
  r.style.width = `${((S.outPt - S.inPt + 1) / n) * 100}%`;
  r.classList.toggle("full", S.inPt === 0 && S.outPt === n - 1);
  $("#tl-key").hidden = !!S.fluid || !S.edits.some((e) => e.on && e.patch);
  keysUI();
  cacheUI();
  $("#tl-key").style.left = pos(0);
  $("#frame-now").textContent = p.first + S.frame;
  $("#frame-total").textContent = `/ ${p.first + n - 1}`;
  $("#fps").textContent = `${Math.round(p.fps * 100) / 100} fps`;
  const t = $("#timeline");
  t.setAttribute("aria-valuemin", p.first); t.setAttribute("aria-valuemax", p.first + n - 1); t.setAttribute("aria-valuenow", p.first + S.frame);
  stagesUI();
}

function setPreview(cap) { // a smaller shot preview renders faster; the export stays at full size
  S.previewCap = cap;
  try { localStorage.setItem("paintaplate.preview", String(cap)); } catch { /* this session only */ }
  if (!S.plate) return;
  S.plate.shot = previewSize([S.plate.spec.width, S.plate.spec.height], S.plate.work, cap);
  previewUI();
  S.heroKey = ""; recompose(); // what this size made already plays at once; the full size and its export never depend on it
  status(`Previews at ${S.plate.shot[0]} × ${S.plate.shot[1]}. The export stays at full size.`);
  stagesUI(); exportUI(); touch();
}

function previewUI() { // the Preview size menu: the sizes this plate can take, the one in use selected
  const sel = $("#preview-size"), p = S.plate;
  if (!p) return;
  const sizes = previewSizes([p.spec.width, p.spec.height], p.work);
  sel.replaceChildren(...sizes.map((o) => new Option(`${o.label} · ${o.size[0]} × ${o.size[1]}${o.div > 1 ? ` (1/${o.div})` : o.label === "Full" ? " (slow)" : ""}`, String(o.cap))));
  const on = sizes.find((o) => o.size[0] === p.shot[0] && o.size[1] === p.shot[1]) ?? sizes.at(-1);
  sel.value = String(on.cap);
}

function exportUI() {
  const b = $("#export-btn"), edits = S.edits.some((e) => e.on && e.patch);
  b.disabled = !S.plate || !edits;
  b.textContent = S.wantDownload ? `Exporting${renderLeft(true) ? `, ${secs(renderLeft(true))}` : ""}` : "Export";
  $("#save-btn").disabled = !S.plate;
}

function exportDialog() {
  const r = S.renders.get(S.heroKey), ready = !!r?.exported && !S.shotDirty, kind = S.plate.spec.kind;
  $("#x-format").textContent = kind === "video" ? `${S.plate.spec.codec} movie` : `${S.plate.spec.ext.slice(1).toUpperCase()} ${kind}`;
  $("#x-bg").checked = S.background;
  $("#x-note").textContent = ready ? "Ready: the zip downloads at once."
    : `The full-quality render runs first, ${secs(renderLeft(true)) || "a moment"}. The zip downloads when it is done.`;
  $("#export").showModal();
}

function setTool(t) {
  if (S.fluid && t !== "paint") return hud(`${NAME[t]} works on a plate: generate the fluid shot, then Use as the plate`);
  S.tool = t;
  S.rub = false;
  $("#rub-btn").setAttribute("aria-pressed", "false");
  $$(".tools [data-tool]").forEach((b) => b.classList.toggle("on", b.dataset.tool === t));
  $("#prompt").placeholder = S.fluid ? FLUID_HINT : HINT[t];
  colorUI();
  render();
}

function setSize(v) {
  S.size = Math.max(4, Math.min(320, Math.round(v)));
  $("#size").value = S.size;
  $("#size-out").textContent = S.size;
  render();
}

function openDialog() { $("#files").value = ""; $("#scene").value = ""; blankNote(); $("#open").showModal(); listPlates().catch(quiet); }

async function listPlates() { // input/plates, each with its first frame: one click fills the path, a double click opens it
  const grid = $("#plates"), note = $("#plates-empty");
  grid.replaceChildren(); note.hidden = false; note.textContent = "Looking for plates in ComfyUI's input/plates folder";
  const items = await (await fetch("/paintaplate/plates")).json();
  note.hidden = items.length > 0;
  note.textContent = "No plates in ComfyUI's input/plates folder yet. On a pod, bash tools/get_plates.sh fetches the AInVFX set (no restart). Or choose files below.";
  grid.replaceChildren(...items.map((it) => {
    const b = document.createElement("button");
    b.type = "button"; b.className = "plate"; b.dataset.path = it.path;
    b.title = `${it.path}: ${it.width} x ${it.height}, ${it.frames} frames at ${it.fps} fps${it.kind === "video" ? "" : `, ${it.ext.slice(1).toUpperCase()} frames`}`;
    b.innerHTML = '<img alt="" loading="lazy"><span class="plate-name"></span><small></small>';
    b.firstChild.src = `/paintaplate/thumb?${new URLSearchParams({ path: it.path })}&v=${it.mtime}`;
    b.children[1].textContent = it.name;
    b.children[2].textContent = `${it.width} × ${it.height} · ${it.frames} fr`;
    b.onclick = () => { $("#path").value = it.path; $("#cs").value = it.color_space; $("#files").value = ""; $$("#plates .plate").forEach((x) => x.classList.toggle("on", x === b)); };
    b.ondblclick = () => { b.onclick(); $("#open-go").click(); };
    return b;
  }));
}

// ---------- Scenes: the plate and every edit with its strokes, words and seed, in a file to open again ----------

const r5 = (v) => Math.round(v * 1e5) / 1e5;
const packStrokes = (strokes, [W, H]) => strokes.map((s) => ({ tool: s.tool, color: s.color, size: r5(s.size / W),
  points: s.points.map(([x, y, pr]) => [r5(x / W), r5(y / H), r5(pr)]) })); // positions as fractions of the frame
const unpackStrokes = (saved, [W, H]) => saved.map((s) => ({ tool: s.tool, color: s.color, size: s.size * W,
  points: s.points.map(([x, y, pr]) => [x * W, y * H, pr]) }));

function saveScene() {
  const work = S.plate.work, f = S.fluid;
  const scene = { ...SCENE, saved: new Date().toISOString(), plate: { path: S.plate.path, color_space: S.plate.cs, name: S.plate.name },
    preview: S.previewCap, in: S.inPt, out: S.outPt,
    edits: S.edits.map((e) => ({ tool: e.tool, color: e.color, prompt: e.prompt, seed: e.seed, whole: !!e.whole, on: e.on,
      caption: e.caption?.text ?? "", strokes: packStrokes(e.strokes, work) })),
    ...(f ? { fluid: { prompt: $("#prompt").value.trim(), seed: f.seed, keys: f.keys.map((k) => ({ frame: k.frame, strokes: packStrokes(k.strokes, work) })) } } : {}) };
  const a = Object.assign(document.createElement("a"), { download: `${S.plate.name}.paintaplate.json`,
    href: URL.createObjectURL(new Blob([JSON.stringify(scene, null, 1)], { type: "application/json" })) });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  status(`Scene saved as ${a.download}. Open plate opens it again, on this ComfyUI.`);
}

async function saveGraph() { // the whole scene as one ComfyUI workflow, to open in ComfyUI and keep editing there
  const p = S.plate, active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
  if (!p || !active.length) return status("Make an edit first: the ComfyUI graph holds the edits and the render.");
  status("Writing the ComfyUI graph: each edit's mask and strokes go to ComfyUI's input folder");
  const edits = [];
  for (const e of active) edits.push({ tool: e.tool, seed: e.seed, caption: e.caption?.text || templateCaption(e),
    mask: await uploadCanvas(maskAt(e, p.work), `graph_e${e.id}_mask.png`),
    layer: e.tool === "erase" ? null : await uploadCanvas(snap(e.paint, p.work), `graph_e${e.id}_strokes.png`),
    quick: editSettings(e, p.prev, QUICK), full: editSettings(e, p.work, FULL) });
  const erase = active.some((e) => e.tool === "erase");
  const graph = sceneGraph(WF, { edits,
    plate: { path: p.path, cs: p.cs, frames: p.frames, work: p.work, prev: p.prev, track: p.track, trackErase: p.trackErase },
    render: { prompt: shotPrompt(active.map((e) => ({ tool: e.tool, words: e.prompt }))), seed: active[0].seed,
      erasePrompt: erasePrompt(active.filter((e) => e.tool === "erase").map((e) => e.caption?.text)),
      grow: grow(p.spec.width, erase), feather: feather(p.spec.width), prefix: `paintaplate/${p.id}/graph` } });
  const a = Object.assign(document.createElement("a"), { download: `${p.name}.comfyui.json`,
    href: URL.createObjectURL(new Blob([JSON.stringify(graph, null, 1)], { type: "application/json" })) });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  status(`Saved ${a.download}: ${Object.keys(graph).length} nodes. Drop it on this ComfyUI to open it: it reads the plate and the strokes from the input folder.`);
}

async function openScene(file) { // the plate opens, then every edit runs again with its own seed and words
  const scene = JSON.parse(await file.text());
  if (scene.format !== SCENE.format || !(scene.version <= SCENE.version)) throw new Error("This file is not a PaintAPlate scene.");
  if (scene.preview) setPreview(scene.preview);
  await openPlate([], scene.plate.path, scene.plate.color_space,
    scene.fluid ? { fluid: { blankPath: scene.plate.path, seed: scene.fluid.seed, prompt: scene.fluid.prompt ?? "" } } : {});
  if (scene.fluid) { // a fluid shot: its keyframes come back, ready to generate
    S.fluid.keys = scene.fluid.keys.map((k) => { const key = newKey(k.frame); key.strokes = unpackStrokes(k.strokes, S.plate.work); redrawKey(key); return key; });
    fluidUI(); timelineUI(); render();
    return status(`Scene opened: a fluid shot with ${S.fluid.keys.length} keyframe${S.fluid.keys.length === 1 ? "" : "s"}. Enter generates it.`);
  }
  for (const saved of scene.edits) {
    const e = Object.assign(newEdit(), { tool: saved.tool, color: saved.color, prompt: saved.prompt ?? "", seed: saved.seed,
      whole: !!saved.whole, on: saved.on !== false, state: "queued", launched: performance.now(), caption: saved.caption ? { key: "scene", text: saved.caption } : null,
      strokes: unpackStrokes(saved.strokes, S.plate.work) });
    redrawStrokes(e);
    e.thumb = strokesThumb(e);
    S.edits.push(e);
    if (e.on) queue(() => generate(e));
  }
  if (Number.isInteger(scene.in) && Number.isInteger(scene.out)) [S.inPt, S.outPt] = [scene.in, scene.out];
  queue(regenerateDependents);
  historyUI(); timelineUI();
  status(`Scene opened: ${scene.edits.length} edit${scene.edits.length === 1 ? "" : "s"} run again with their own seeds and captions.`);
}

function clearRange() { S.inPt = 0; S.outPt = S.plate.frames - 1; hud("In and out points cleared"); timelineUI(); }
function fullScreen() { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen(); }

// ---------- The viewer's colour, as in RV: exposure, contrast, gamma, saturation, hue, channels, invert ----------
// Display only: one SVG filter on the canvas, and none at the defaults, so playback pays nothing until a value moves. It
// works on the 8-bit preview, where values above white are already clipped; the export never changes.

function setDisplay(change) {
  Object.assign(S.display, change);
  const d = S.display, { slope, intercept, exponent } = displayTransfer(d), on = displayActive(d);
  for (const f of $$("#display-filter .fx-lin")) { f.setAttribute("slope", String(slope)); f.setAttribute("intercept", String(intercept)); }
  for (const f of $$("#display-filter .fx-gamma")) f.setAttribute("exponent", String(exponent));
  $("#fx-matrix").setAttribute("values", displayMatrix(d));
  view.style.filter = on ? "url(#display-filter)" : "";
  $("#display-state").hidden = !on;
  $("#display-state").textContent = displayLabel(d);
  hud(S.mode ? `${PARAMS[S.mode].label} ${formatParam(S.mode, d[S.mode])}` : on ? displayLabel(d) : "Colour as shot", 1400);
}

function colorMode(name) { // RV's interactive edit: drag on the frame, or the wheel, - and =; Backspace resets; Esc or the key again leaves
  if (S.mode === name) return leaveMode();
  S.mode = name;
  view.classList.add("scrub");
  hud(`${PARAMS[name].label} ${formatParam(name, S.display[name])}: drag on the frame, or the wheel, - and =. Backspace resets, Esc leaves.`, 4000);
  render();
}

function leaveMode() {
  if (!S.mode) return;
  const name = S.mode;
  S.mode = S.scrub = null;
  view.classList.remove("scrub");
  hud(displayActive(S.display) ? displayLabel(S.display) : `${PARAMS[name].label} as shot`);
}

const stepColor = (name, dir) => setDisplay({ [name]: clampParam(name, S.display[name] + dir * PARAMS[name].step) });

function modeKey(k, combo) { // the keys of an interactive edit, as RV's paramscrub table; any other key leaves it, then acts
  if (k === "-" || k === "_") stepColor(S.mode, -1);
  else if (k === "=" || k === "+") stepColor(S.mode, 1);
  else if (k === "Backspace" || k === "Delete" || combo === "Shift+r") setDisplay({ [S.mode]: DISPLAY[S.mode] });
  else if (k === "Escape" || k === "Enter" || COLOR_KEYS[combo] === S.mode) leaveMode();
  else { leaveMode(); return false; }
  return true;
}

function resetDisplay() { leaveMode(); setDisplay({ ...DISPLAY }); }

// ---------- The right-click menu, as RV's: every action of the page, with its key ----------

function menuItems() { // [group, [[label, key, action, disabled, checked] or "-", ...]]
  const p = !!S.plate, d = S.display, edits = S.edits.some((e) => e.on && e.patch);
  const chan = (c, key) => [CHANNEL_NAMES[c], key, () => setDisplay({ channel: c }), !p, d.channel === c];
  const param = (name, key) => [`${PARAMS[name].label}…`, key, () => colorMode(name), !p, S.mode === name];
  const step = (by) => () => { pause(); seek(S.frame + by); };
  const groups = [
    ["File", [["Open plate…", "", openDialog], ["Back to the fluid keyframes", "", () => backToKeys().catch(quiet), !S.lastFluid || !!S.fluid],
      ["Save scene", "", saveScene, !p], ["Export…", "", exportDialog, !edits],
      ["ComfyUI graph", "", () => saveGraph().catch(quiet), !edits]]],
    ["Edit", [["Undo", "Ctrl+Z", undo, !S.past.length], ["Redo", "Ctrl+Shift+Z", redo, !S.future.length], "-",
      ["New edit", "N", nextEdit, !p || !!S.fluid || (!S.draft && !S.selected)], ["Generate", "Enter", () => enter(false), $("#generate").disabled], ["Try another seed", "Ctrl+Enter", () => enter(true), !S.edits.length],
      ["Deselect", "Esc", () => select(null), !S.selected]]],
    ["Tools", [["Paint", "B", () => pickTool("paint"), !p, S.tool === "paint" && !S.rub], ["Erase", "E", () => pickTool("erase"), !p || !!S.fluid, S.tool === "erase" && !S.rub],
      ["Light", "L", () => pickTool("light"), !p || !!S.fluid, S.tool === "light" && !S.rub], ["Eraser", "X", () => setRub(!S.rub), !p, S.rub], "-",
      ["Whole object", "", () => $("#whole").click(), !p, $("#whole").checked], ["Smaller brush", "-", () => setSize(S.size / 1.2), !p],
      ["Larger brush", "=", () => setSize(S.size * 1.2), !p]]],
    ["Control", [["Play or pause", "Space", () => (S.playing ? pause() : play()), !p, S.playing], ["Next frame", "Right", step(1), !p],
      ["Previous frame", "Left", step(-1), !p], "-", ["Go to the in point", "Home", () => { pause(); seek(S.inPt); }, !p],
      ["Go to the out point", "End", () => { pause(); seek(S.outPt); }, !p], ["Set the in point", "[", () => setIn(S.frame), !p],
      ["Set the out point", "]", () => setOut(S.frame), !p], ["Clear in and out", "\\", clearRange, !p]]],
    ["Colour", [param("exposure", "Shift+E"), param("contrast", "K"), param("gamma", "Y"), param("saturation", "Shift+S"), param("hue", "H"), "-",
      ["Invert", "Shift+I", () => setDisplay({ invert: !d.invert }), !p, d.invert], ["Reset colour", "", resetDisplay, !displayActive(d)]]],
    ["View", [chan("rgb", "Shift+C"), chan("r", "Shift+R"), chan("g", "Shift+G"), chan("b", "Shift+B"), chan("l", "Shift+L"), "-",
      ["Fit", "F", () => zoomTo(1), !p], ["1:1", "1", () => zoomTo(S.plate.work[0] / S.fit.w), !p],
      ["Wipe", "F6", () => setWipe(S.wipe === null), !p, S.wipe !== null], ["Full screen", "`", fullScreen],
      ["Log", "", () => $("#log-btn").click(), false, !$("#log").hidden]]],
    ["Help", [["Keys", "?", () => $("#help").showModal()]]],
  ];
  const f = S.fluid;
  if (f) groups.splice(2, 0, ["Fluid", [["Generate", "Enter", () => generateFluid().catch(quiet), !f.keys.length],
    ["Another seed", "Ctrl+Enter", () => generateFluid(true).catch(quiet), !f.keys.length], ["Use as the plate", "", () => useFluid().catch(quiet), !f.result || !!f.busy], "-",
    ["Copy keyframe", "Ctrl+C", copyKey, !keyHere()], ["Paste keyframe", "Ctrl+V", pasteKey, !S.clip], ["Delete keyframe", "Delete", () => deleteKey(), !keyHere()], "-",
    ["Previous keyframe", "Alt+Left", () => jumpKey(-1)], ["Next keyframe", "Alt+Right", () => jumpKey(1)]]]);
  return groups;
}

const SHEET = matchMedia("(max-width: 900px) and (orientation: portrait), (max-width: 600px), (max-height: 520px)"); // phones: the menu along the bottom

function openMenu(x, y) {
  const root = $("#ctx");
  root.replaceChildren(...menuItems().map(([group, items]) => {
    const li = document.createElement("li"), sub = document.createElement("ul");
    li.className = "group";
    li.innerHTML = '<span></span><span class="arrow">▸</span>';
    li.firstChild.textContent = group;
    sub.className = "sub";
    sub.setAttribute("role", "menu");
    for (const it of items) {
      const row = document.createElement("li");
      if (it === "-") { row.className = "sep"; sub.append(row); continue; }
      const [label, key, action, disabled = false, checked] = it, b = document.createElement("button");
      b.type = "button";
      b.disabled = !!disabled;
      b.setAttribute("role", checked === undefined ? "menuitem" : "menuitemcheckbox");
      if (checked !== undefined) b.setAttribute("aria-checked", String(!!checked));
      b.innerHTML = '<span class="check"></span><span></span><kbd></kbd>';
      b.children[1].textContent = label;
      b.children[2].textContent = key;
      b.onclick = () => { closeMenu(); action(); };
      row.append(b);
      sub.append(row);
    }
    li.onmouseenter = () => { // a submenu that would leave the window moves up
      sub.style.top = "";
      const r = sub.getBoundingClientRect();
      if (r.bottom > innerHeight - 8) sub.style.top = `${Math.round(innerHeight - 8 - r.bottom - 5)}px`;
    };
    li.append(sub);
    return li;
  }));
  for (const g of root.querySelectorAll(".group")) g.onclick = (ev) => { // a tap opens a group: phones have no hover
    if (ev.target.closest("button")) return;
    const open = !g.classList.contains("open");
    root.querySelectorAll(".group.open").forEach((o) => o.classList.remove("open"));
    g.classList.toggle("open", open);
  };
  root.classList.toggle("sheet", SHEET.matches);
  root.hidden = false;
  if (SHEET.matches) { root.style.left = root.style.top = ""; return; }
  root.style.left = `${Math.max(8, Math.min(x, innerWidth - root.offsetWidth - 8))}px`;
  root.style.top = `${Math.max(8, Math.min(y, innerHeight - root.offsetHeight - 8))}px`;
  root.classList.toggle("flip", x + root.offsetWidth + 260 > innerWidth); // no room on the right: the submenus open on the left
}

function closeMenu() { $("#ctx").hidden = true; }

$("#viewport").addEventListener("contextmenu", (e) => { e.preventDefault(); openMenu(e.clientX, e.clientY); });
document.addEventListener("pointerdown", (e) => { // a press outside the open menu closes it and does nothing else
  if ($("#ctx").hidden || e.target.closest("#ctx, #menu-btn")) return;
  closeMenu();
  e.stopPropagation();
  e.preventDefault();
}, true);
addEventListener("blur", closeMenu);

async function boot() { // the workflows, the WebSocket, then what this ComfyUI lacks: nodes, then model files
  onNotice(status);
  onLog(log);
  const t0 = performance.now();
  const [, upsampler] = await Promise.all([loadWorkflows(WORKFLOWS), fetch("upsampler.json").then((r) => r.json())]);
  Object.assign(UPSAMPLER, upsampler);
  connect();
  const combo = (spec) => (Array.isArray(spec?.[0]) ? spec[0] : spec?.[1]?.options ?? []); // V1 or V3 schema
  const spaces = combo((await objectInfo("ImageColorSpace"))?.input.required.source);
  $("#cs").replaceChildren(...(spaces.length ? spaces : ["sRGB"]).map((s) => new Option(s, s)));
  const needs = { PaintAPlate_LoadPlate: "this pack",
    PaintAPlate_FollowMatte: "this pack, restart ComfyUI after an update", LTXAddVideoICLoRAGuide: "ComfyUI-LTXVideo",
    LTXVInpaintPreprocess: "ComfyUI-LTXVideo", SAM3_VideoTrack: "ComfyUI 0.42 or newer", ReferenceMultiLatent: "ComfyUI 0.41 or newer",
    TextGenerate: "ComfyUI 0.41 or newer" };
  const models = new Map(); // every model file the workflows load, by loader and input
  for (const wf of Object.values(WF)) for (const n of Object.values(wf.prompt))
    for (const [k, v] of Object.entries(n.inputs)) if (typeof v === "string" && v.endsWith(".safetensors")) models.set(v, [n.class_type, k]);
  const classes = [...new Set([...Object.keys(needs), ...[...models.values()].map(([cls]) => cls), "PaintAPlate_KeyframeVideo"])];
  const info = Object.fromEntries(await Promise.all(classes.map(async (cls) => [cls, await objectInfo(cls)]))); // one round trip for all
  const missing = Object.entries(needs).filter(([cls]) => !info[cls]).map(([cls, from]) => `${cls} (${from})`);
  if (missing.length) return status(`Missing nodes: ${missing.join(", ")}. Install them, then reload this page.`);
  const absent = []; // only lists count: a file named in a text input is optional (the live preview's decoder)
  for (const [file, [cls, input]] of models) { const options = combo(info[cls]?.input.required[input]); if (options.length && !options.includes(file)) absent.push(file); }
  const fluidFiles = new Set(Object.values(WF.fluid.prompt).flatMap((n) => Object.values(n.inputs)).filter((v) => typeof v === "string" && v.endsWith(".safetensors")));
  const only = (file) => fluidFiles.has(file) && !Object.entries(WF).some(([name, wf]) => name !== "fluid" && JSON.stringify(wf.prompt).includes(file));
  S.fluidReady = !absent.some(only) && !!info.PaintAPlate_KeyframeVideo && !!info.LTXICLoRALoaderModelOnly; // fluid shots are optional
  if (!S.fluidReady) log(`Fluid shots are off: ${absent.filter(only).join(", ") || "update this pack and ComfyUI-LTXVideo"} (blank plates need ainvfx-fluid in models/loras).`);
  const missingFiles = absent.filter((file) => !only(file));
  if (missingFiles.length) return status(`Missing model files: ${missingFiles.join(", ")}. tools/pod_setup.sh lists each one with its models folder and downloads it.`);
  log(`Page ready in ${Math.round(performance.now() - t0)} ms: ${WORKFLOWS.length} workflows, ${classes.length} node classes and ${models.size} model files checked`);
  status("Ready. Open a plate to start. The models load in the background.");
  warmAll().catch(() => {}); // a ComfyUI that reports no GPU details simply skips it
}

$$(".tools [data-tool]").forEach((b) => (b.onclick = () => pickTool(b.dataset.tool)));
$("#size").oninput = (e) => setSize(+e.target.value);
function setColor(c) { // the colour of the current tool: Paint and Light keep their own
  if (S.tool === "erase") return;
  S.colors[S.tool] = c;
  colorUI();
}
function colorUI() {
  const c = S.color, off = S.tool === "erase";
  $$(".swatches .sw[data-color]").forEach((b) => b.setAttribute("aria-pressed", String(!off && b.dataset.color === c)));
  $(".swatches").classList.toggle("off", off);
  $("#color").value = c;
  $(".swatches .custom").classList.toggle("on", !off && ![...$$(".swatches .sw[data-color]")].some((b) => b.dataset.color === c));
}
$$(".swatches .sw[data-color]").forEach((b) => (b.onclick = () => setColor(b.dataset.color)));
$("#color").oninput = (e) => setColor(e.target.value);
function setRub(on) {
  S.rub = on;
  $("#rub-btn").setAttribute("aria-pressed", String(on));
  hud(on ? "Eraser: rub out the strokes you just painted" : NAME[S.tool]);
  render();
}
$("#rub-btn").onclick = () => setRub(!S.rub);
$("#whole").onchange = () => { // on the current erase, the switch is a change like the words: Generate runs it again
  pickTool("erase");
  const cur = S.selected;
  if (!S.draft && cur?.tool === "erase") { mark(); if (busy(cur)) reopen(cur); else reopenDone(cur); }
  if (S.draft?.tool === "erase") prepareSoon();
};
$("#prompt").oninput = () => { // the words belong to the edit being drawn, or to the current one, which Generate runs again
  if (stroke) return;
  if (S.fluid) return staleFluid(); // new words for a fluid shot: the one on show used the old ones
  const cur = S.selected;
  if (!S.draft && cur) { mark(); if (busy(cur)) reopen(cur); else reopenDone(cur); }
  if (S.draft) prepareSoon(true); else generateUI();
};
$("#editing").onclick = () => select(null);
$("#new-edit").onclick = () => nextEdit();
$("#blank-go").onclick = () => openBlank().catch(quiet);
for (const id of ["#b-width", "#b-height", "#b-fps", "#b-frames"]) $(id).oninput = blankNote;
$("#generate").onclick = () => enter(false);
$("#fluid-again").onclick = () => generateFluid(true).catch(quiet);
$("#fluid-use").onclick = () => useFluid().catch(quiet);
$("#display-state").onclick = () => resetDisplay();
$("#undo-btn").onclick = () => undo();
$("#redo-btn").onclick = () => redo();
$("#save-btn").onclick = () => S.plate && saveScene();
$("#x-graph").onclick = () => saveGraph().catch(quiet);
$("#open-btn").onclick = $("#empty-open").onclick = openDialog;
$("#help-btn").onclick = () => $("#help").showModal();
$("#menu-btn").onclick = (e) => { // the same menu as a right-click, for touch screens
  if (!$("#ctx").hidden) return closeMenu();
  const r = e.currentTarget.getBoundingClientRect();
  openMenu(r.left, r.bottom + 4);
};
$("#play-btn").onclick = () => (S.playing ? pause() : play());
$("#wipe-btn").onclick = () => setWipe(S.wipe === null);
$("#export-btn").onclick = exportDialog;
$("#preview-size").value = String(S.previewCap);
$("#preview-size").onchange = (e) => setPreview(+e.target.value);
$("#x-bg").onchange = (e) => {
  S.background = e.target.checked;
  try { localStorage.setItem("paintaplate.background", S.background ? "1" : "0"); } catch { /* private mode: this session only */ }
  stagesUI(); touch();
};
$("#x-go").onclick = () => {
  const parts = ["export", ...["matte", "review", "shot"].filter((k) => $(`#x-${k}`).checked)];
  const r = S.renders.get(S.heroKey);
  if (r?.exported && !S.shotDirty) return download(parts);
  S.wantDownload = parts;
  status("Rendering the export at full quality: the zip downloads when it is done.");
  exportUI(); stagesUI(); touch();
};
$("#log-btn").onclick = () => {
  const open = $("#log").hidden;
  $("#log").hidden = !open;
  $("#log-btn").setAttribute("aria-expanded", String(open));
  $("#log-btn").classList.remove("alert");
  if (open) $("#log").scrollTop = $("#log").scrollHeight;
};
$("#files").onchange = (e) => { const ext = e.target.files[0]?.name.split(".").pop().toLowerCase(); $("#cs").value = ext === "exr" ? "linear" : "sRGB"; };
$("#open-go").onclick = () => {
  const scene = $("#scene").files[0];
  (scene ? openScene(scene) : openPlate([...$("#files").files], $("#path").value.trim(), $("#cs").value)).catch(quiet);
};

const timeline = $("#timeline");
let scrub = false;
timeline.addEventListener("pointerdown", (e) => {
  if (!S.plate) return;
  timeline.setPointerCapture(e.pointerId);
  scrub = true; pause(); scrubTo(e);
});
timeline.addEventListener("pointermove", (e) => scrub && scrubTo(e));
timeline.addEventListener("pointerup", () => (scrub = false));
function scrubTo(e) { const r = timeline.getBoundingClientRect(); seek(((e.clientX - r.left) / r.width) * S.plate.frames - 0.5); }

let wheel = 0;
for (const el of [$("#viewport"), timeline]) el.addEventListener("wheel", (e) => { // RV: the wheel steps through frames
  if (!S.plate) return;
  e.preventDefault();
  wheel += e.deltaY;
  if (Math.abs(wheel) < 40) return;
  if (S.mode) { stepColor(S.mode, wheel < 0 ? 1 : -1); wheel = 0; return; } // during a colour edit the wheel changes the value (RV)
  pause();
  seek(S.frame + Math.sign(wheel) * (e.ctrlKey ? 10 : 1));
  wheel = 0;
}, { passive: false });

document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  e.preventDefault();
  const list = [...e.dataTransfer.files];
  if (list.length) openPlate(list, "", /\.exr$/i.test(list[0].name) ? "linear" : "sRGB").catch(quiet);
});

addEventListener("keydown", (e) => {
  if (e.target.matches("input, select, textarea")) {
    if (e.key === "Enter" && e.target.id === "prompt") { enter(e.ctrlKey || e.metaKey); e.target.blur(); e.preventDefault(); }
    else if (e.key === "Escape") e.target.blur();
    return;
  }
  if (e.key === "?" && $("#help").open) { $("#help").close(); return e.preventDefault(); }
  if ($("dialog[open]")) return;
  const k = e.key, low = k.toLowerCase(), mod = e.ctrlKey || e.metaKey, combo = `${e.shiftKey && k.length === 1 ? "Shift+" : ""}${low}`;
  if (!$("#ctx").hidden) { if (k === "Escape") closeMenu(); return e.preventDefault(); } // the menu is open: Esc closes it
  if (!S.plate && !["?", "F6"].includes(k)) return;
  if (S.mode && modeKey(k, combo)) return e.preventDefault();
  if (!mod && !e.altKey && COLOR_KEYS[combo]) { colorMode(COLOR_KEYS[combo]); return e.preventDefault(); }
  if (!mod && !e.altKey && CHANNEL_KEYS[combo]) { setDisplay({ channel: CHANNEL_KEYS[combo] }); return e.preventDefault(); }
  if (!mod && combo === "Shift+i") { setDisplay({ invert: !S.display.invert }); return e.preventDefault(); }
  if (S.fluid && mod && !e.shiftKey && (low === "c" || low === "v") && !getSelection().toString()) { if (low === "c") copyKey(); else pasteKey(); return e.preventDefault(); }
  if (S.fluid && !mod && (k === "Delete" || k === "Backspace")) { deleteKey(); return e.preventDefault(); }
  if (S.fluid && e.altKey && (k === "ArrowLeft" || k === "ArrowRight")) { jumpKey(k === "ArrowLeft" ? -1 : 1); return e.preventDefault(); }
  if (k === " " || k === "ArrowDown") S.playing ? pause() : play();
  else if (k === "ArrowLeft" || k === "ArrowRight") { pause(); seek(S.frame + (k === "ArrowLeft" ? -1 : 1)); }
  else if (k === "Home") { pause(); seek(S.inPt); }
  else if (k === "End") { pause(); seek(S.outPt); }
  else if (k === "[") setIn(S.frame);
  else if (k === "]") setOut(S.frame);
  else if (k === "\\") clearRange();
  else if (k === "F6") setWipe(S.wipe === null);
  else if (low === "f" && !mod) zoomTo(1);
  else if (k === "1" && !mod) zoomTo(S.plate.work[0] / S.fit.w);
  else if (k === "`") fullScreen();
  else if (k === "?") $("#help").showModal();
  else if (TOOLS[low] && !mod) pickTool(TOOLS[low]);
  else if (low === "n" && !mod) nextEdit();
  else if (low === "x" && !mod) setRub(!S.rub);
  else if (k === "-" || k === "_") setSize(S.size / 1.2);
  else if (k === "=" || k === "+") setSize(S.size * 1.2);
  else if (k === "Enter") enter(mod);
  else if (k === "Escape") discard();
  else if (low === "z" && mod) e.shiftKey ? redo() : undo();
  else if (low === "y" && mod) redo();
  else if (low === "o" && !mod) { if (!S.compare) { S.compare = true; render(); hud("Plate"); } }
  else return;
  e.preventDefault();
});
addEventListener("keyup", (e) => { if (e.key.toLowerCase() === "o" && S.compare) { S.compare = false; render(); } });
function enter(another) { // Generate (Enter): the edit in progress, then its shot; nothing already made runs again. Ctrl+Enter: another seed
  if (S.fluid) return void generateFluid(another).catch(quiet); // a fluid shot: generate it, Ctrl+Enter with another seed
  if (S.draft) return launch(S.draft);
  if (another) { const target = S.selected ?? S.edits.at(-1); if (target) again(target); return; }
  if (renderPending()) { S.shotDirty = true; touch(0); return hud("The shot renders now", 2000); } // a render that stopped or failed goes on
  hud(S.edits.length ? "Nothing changed since the last result. Ctrl+Enter tries another seed." : "Paint on the frame first, then Generate.", 3000);
}

function renderPending() { // the edits on show have no finished render, and none runs or waits
  const r = S.renders.get(S.heroKey);
  return !!S.plate && !S.fluid && !!S.heroKey && !S.piping && !S.running && !S.queued && !(previewOf(r)?.comp && (r?.exported || !S.background));
}

function generateUI() { // the Generate button is live when Enter has something to start
  const b = $("#generate"), f = S.fluid;
  const working = f ? !!f.busy : !!(S.running || S.queued || S.piping);
  const todo = !S.plate ? false : f ? S.fluidReady && f.keys.length > 0 && !f.made?.has(fluidSig()) && !(f.busy && f.busy.sig === fluidSig())
    : (!!S.draft && painted(S.draft) > 0) || renderPending();
  b.disabled = !todo;
  b.textContent = working && !todo ? "Generating…" : "Generate";
}
new ResizeObserver(() => { fitView(); cacheUI(); }).observe($("#viewport"));

setTool("paint");
setSize(48);
boot().catch(quiet);
