// AInVFX PaintAPlate: one viewer to play a plate, paint edits on its first frame and watch the edited shot.
// The page runs on the ComfyUI server that serves it. Every step is a workflow from ./workflows, run by comfy.mjs;
// pure rules live in logic.mjs (tested in Node), canvas helpers in canvas.mjs, the frame cache in frames.mjs.

import { bounds, blob, canvas, loadImage, snap, whiteOf } from "./canvas.mjs";
import { WF, cancel, connect, hashHex, loadWorkflows, objectInfo, onLog, onNotice, outputFile, outputFiles, outputText, post, run, setSalt, upload, viewUrl } from "./comfy.mjs";
import { Display } from "./display.mjs";
import { DeepFrames, FrameCache } from "./frames.mjs";
import { sceneGraph } from "./graph.mjs";
import { CHANNEL_NAMES, DISPLAY, FLUID, PARAMS, blankSpec, caption, changedMask, clampParam, fluidPrompt, keySlots, moveKey, nearKeys, snapKey, dark, dependsOnChange, displayActive, displayLabel, fitSize,
  erasePrompt, erasesPaint, formatParam, gb, nextRender, paintBoxes, pickObjects, pickedColor, plainError, previewSize, previewSizes, reconcile, secs, shotPrompt, splitTable, stageOne,
  stopsForEdit, strokeTarget, toolEndsEdit, upsampleRequest, ocioTree, browseItems, crumbs, framePattern, panelSize, hdrPlate, wantsHdr, hdrFps, blankDepth, HDR_DEPTH, escapeAction } from "./logic.mjs";

const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];
const Q = new URLSearchParams(location.search);

// ---------- Tuning: every number that sets a size, a delay or a budget ----------
// FLUX 3 Image Klein: a quick pass at EDIT_SIDE, then a full-size pass that refines it with a light denoise
const QUICK = { steps: 16, denoise: 1, feather: 6, sigma: 3 }; // 16: the official distilled setting, 1.8 s at 768 on an RTX PRO 6000
const FULL = { steps: +Q.get("refine") || 8, denoise: 0.35, feather: 12, sigma: 6 };
const CACHE_MB = +Q.get("cache") || 384; // decoded frames kept per video: about 180 frames at 960 x 544
const DEEP_MB = +Q.get("deep") || 512; // per cache (the plate, an export): an image sequence in its own values, about 160 frames of RGB half floats at 960 x 540
const DEEP_SIDE = 960; // their long side, the playback video's
const WORK_SIDE = 1920, EDIT_SIDE = 768, TRACK_SIDE = 960; // long sides: full-size edits, quick edits, SAM tracking
// the erase matte only places the erase pass's box, grown by 1/24 of the width: 640 is enough, at half the time of 960
const ERASE_TRACK_SIDE = 640;
const LIVE = { every: 2, vram: 24e9 }; // the live preview while LTX samples: from step 1, every other step, on cards with room for its tiny decoder
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
const SIDE_W = 288, LOG_H = 180; // CSS px: the side panel's width and the open log's height until a divider moves them
const PANEL_LEAST = { side: 220, log: 60 }, STAGE_LEAST = { side: 320, log: 320 }; // a drag never makes them smaller
const PANEL_STEP = 16; // CSS px per arrow key on a focused divider
const LAYOUT_PREF = "paintaplate.layout"; // the dragged sizes, kept for the next session
const RENDERS_WANTED = 6; // sets of edits whose renders go on in the background: the most recently shown
const WORKFLOWS = ["ingest", "prompt", "edit", "snap", "clean", "cleanup", "shot", "matte", "comp", "review", "export", "warm", "fluid", "hdr"];
const BACKGROUND = ["clean", "shot", "matte", "comp", "hdr", "review", "export"]; // the render's job kinds: Generate and a new plate stop them
const UPSAMPLER = {}; // Black Forest Labs' system prompts for Klein's upsampler (upsampler.json): table and plain
const SCENE = { format: "paintaplate-scene", version: 4 }; // 3: the OCIO config, the plate's colour space by its OCIO name, the display and view; 4: the SDR-to-HDR switch, the blank plate's bit depth
const OCIO_PREF = "paintaplate.ocio"; // the config, display, view and look, kept for the next session as RV keeps them
const saved = (key) => { try { return JSON.parse(localStorage.getItem(key)) ?? {}; } catch { return {}; } };

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
const HDR_MISSING = "16-bit needs Lightricks' SDR-to-HDR IC-LoRA: ltx-2.5-22b-ic-lora-sdr-to-hdr-1.0.safetensors in models/loras and its scene embeddings in models/embeddings. Accept its licence on Hugging Face, then python get_models.py downloads both.";
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
  fluid: null, clip: null, fluidReady: true, // a fluid shot on a blank plate, the last one, a copied keyframe
  shot: null, stage: null, run: 0, exported: null, wantDownload: null,
  ocio: { config: "", display: "", view: "", look: "", ...saved(OCIO_PREF), info: null }, // the OCIO config and the viewer's view, as in RV
  previewCap: (() => { try { return +localStorage.getItem("paintaplate.preview") || PREVIEW_CAP; } catch { return PREVIEW_CAP; } })(), // long side of the shot preview: Fast by default
  toHdr: true, // SDR to HDR after the full-size shot of an EXR plate, until switched off (logic.wantsHdr)
  heroKey: "", renders: new Map(), // set of edits -> what has been rendered for it
  erases: new Map(), // set of erases -> their matte and clean plates, for every render that has the same erases
  peek: null, // the History row picked: frame 0 shows its strokes over the edited first frame
  uploads: new Map(), live: null, vram: 0, // the live preview on show, the GPU's memory in bytes
  uploaded: new Map(), ups: 0, wants: 0, // images uploaded by content (hash -> name), for every plate; the order renders were shown in
};

const view = $("#view"), ctx = view.getContext("2d");
const plateVid = $("#plate-video"), shotVid = $("#shot-video");
const fx = document.createElement("canvas"); // scratch layer for masked overlays
const HISTORY_HELP = $("#history-empty").textContent;
const FLUID_HELP = "A fluid shot: paint flat colour blobs (light grey smoke, white steam, orange and yellow fire) on frame 0 and on the " +
  "last frame, and on the 8-frame grid between if you want. Ctrl+C and Ctrl+V copy a keyframe; drag its diamond to move it. Describe " +
  "the fluid, then Enter.";

const quiet = (e) => { if (e?.message === "cancelled") return; console.error(e); status(e?.message ?? String(e), "error"); };
const num = (e) => { const i = S.edits.indexOf(e); return i < 0 ? "New" : i + 1 + (S.fluid ? 1 : 0); }; // a blank plate's fluid shot is 1; an edit's number: its place in History, 1 at the bottom
const snapKeyOf = (e) => `${painted(e)}|${e.whole ? e.prompt : ""}`; // what SAM's answer depends on: the strokes, and the name when it searches by name
// An image is uploaded under the hash of its content: once per session, and under the same name in every session, so a job
// that reads it keeps its job index key when a scene opens again. Without WebCrypto (plain http) each upload has its own name.
const uploadCanvas = async (c, name) => {
  const b = await blob(c), h = await hashHex(b);
  if (!h) return upload(b, `${S.plate.id}_${++S.ups}_${name}`, `paintaplate/${S.plate.id}`);
  if (!S.uploaded.has(h)) S.uploaded.set(h, upload(b, `${h.slice(0, 32)}.png`, "paintaplate/up").catch((err) => { S.uploaded.delete(h); throw err; }));
  return S.uploaded.get(h);
};

const modelSpace = () => S.ocio.info?.model ?? "@model"; // the sRGB-encoded Rec.709 the models see, by its name in the config
const knownSpace = (name) => (name && S.ocio.info?.spaces.some((s) => s.name === name) ? name : null);

const folderOf = (name, out, key) => { // the folder a workflow saved its frames in, wherever an earlier session put it
  const f = outputFile(name, out, key);
  if (!f) throw new Error(`${name} saved no ${key}`);
  return `output:${f.subfolder}`;
};

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


// ---------- Plate ----------

// opts.cs: the plate's colour space (else read from the file); opts.fluid: a blank plate, opened as a fluid shot; opts.under:
// the same edits on another plate, or on the same plate in another colour space
async function openPlate(list, typed, opts = {}) {
  if (!list.length && !typed) return status("Choose files, or type a path in ComfyUI's input folder.");
  stopEverything();
  Object.assign(S, { plate: null, hero: null, original: null }); // nothing to draw while the new plate loads
  const id = Date.now().toString(36), sub = `paintaplate/${id}`;
  let path = typed, out, cs;
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
    const st = await fetch(`/paintaplate/stat?${new URLSearchParams({ path, config: S.ocio.config })}`).then((r) => (r.ok ? r.json() : null)).catch(() => null);
    setSalt(st ? JSON.stringify([path, st.files, st.size, st.mtime]) : null); // the plate's identity: job index keys change when it does
    cs = knownSpace(opts.cs) ?? st?.color_space ?? modelSpace(); // one colour space per plate: the viewer, the models and the export use it
    // a video plate's proxy keeps its own values at the working size, so the viewer converts it with OCIO as it does the plate
    const video = st?.kind === "video", work = st?.width ? fitSize(st.width, st.height, WORK_SIDE, 32) : null;
    const t0 = performance.now();
    out = await run("ingest", { path, config: S.ocio.config, color_space: cs, proxy_space: video ? cs : "@model",
      proxy_size: video && work ? Math.max(...work) : DEEP_SIDE, prefix: `${sub}/hero`, video_prefix: `${sub}/proxy` }, {
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
  S.plate = { id, path, cs, spec, frames: spec.frames, fps: spec.fps || 24, name: stem, deep: spec.kind !== "video", // an image sequence: read at full precision
    proxySpace: spec.kind === "video" ? cs : modelSpace(),
    first: spec.kind === "video" ? 1 : spec.first_frame ?? 1,
    work: fitSize(w, h, WORK_SIDE, 32), prev: fitSize(w, h, EDIT_SIDE, 16),
    track: fitSize(w, h, TRACK_SIDE, 32), trackErase: fitSize(w, h, ERASE_TRACK_SIDE, 32) }; // SAM tracks at one size whatever the preview size
  if (Q.get("shot") === "full") S.previewCap = Math.max(w, h);
  S.plate.shot = previewSize([w, h], S.plate.work, S.previewCap);
  S.original = snap(await loadImage(viewUrl(outputFile("ingest", out, "hero"))), S.plate.work);
  $("#prompt").value = "";
  Object.assign(S, { hero: S.original, running: null, live: null, halted: false, frame: 0, inPt: 0, outPt: S.plate.frames - 1, shot: null, exported: null,
    wantDownload: null, stage: { phase: "none" }, wipe: null, heroKey: "" });
  if (!opts.under) Object.assign(S, { edits: [], draft: null, past: [], future: [], selected: null, hover: null, peek: null, zoom: { k: 1, x: 0, y: 0 } });
  S.uploads.clear(); S.renders.clear(); S.erases.clear();
  if (!opts.under) S.fluid = opts.fluid ? { keys: [], seed: (Math.random() * 2 ** 31) | 0, runs: 0, result: null, view: "keys", prompt: "", on: true, editing: true,
    ...opts.fluid, busy: null } : null;
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
  if (opts.under) recompose(); // the edits' patches on the new first frame, until they are made again on it
  previewUI(); fitView(); historyUI(); timelineUI(); stagesUI(); exportUI(); render();
  log(`Plate ${S.plate.name}: ${w} x ${h}, ${spec.frames} frames; edits at ${S.plate.work.join(" x ")}, quick passes at ${S.plate.prev.join(" x ")}, preview at ${S.plate.shot.join(" x ")}, tracking at ${S.plate.track.join(" x ")}`);

  const gaps = spec.missing?.length ? ` ${spec.missing.length} frame${spec.missing.length > 1 ? "s are" : " is"} missing (${spec.missing.slice(0, 4).map((n) => n).join(", ")}${spec.missing.length > 4 ? "…" : ""}): the frame before holds, as in RV.` : "";
  if (gaps) setTimeout(() => status(gaps.trim()), 50);
  status(`${S.plate.name} in ${cs}${opts.cs ? "" : ", read from the file"} (right-click > OCIO > File Color Space changes it). Describe the edit at the top, paint on the frame, then Generate.`);
  if (keying()) enterFluid(); else fluidUI();
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
const deepOf = (v) => new DeepFrames(v, { view: playhead, changed: () => cacheUI(), budget: DEEP_MB * 1e6 });
const deep = deepOf(plateVid), deepShot = deepOf(shotVid); // full precision: an image-sequence plate, and its full-quality review
const look = new Display({ onready: () => render(), onerror: (m) => log(m, "error") }); // the viewer's OCIO, as in RV

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
  v.addEventListener("loadeddata", () => { caches.get(v).reset(); caches.get(v).fill(); if (v === plateVid || v === shotVid) wantDeep(); });
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
addEventListener("resize", () => { layoutUI(); fitView(); });

function frameAt(e) { // pointer position in frame pixels (working size); stays right under zoom and pan
  const r = view.getBoundingClientRect();
  return [((e.clientX - r.left) * view.width) / r.width, ((e.clientY - r.top) * view.height) / r.height];
}

function layered(upto = S.edits.length, keep = () => true) { // the first frame with the active edits before index `upto`
  const c = snap(S.original, S.plate.work), x = c.getContext("2d");
  for (const e of S.edits.slice(0, upto)) if (e.on && e.patch && e.state !== "generating" && keep(e)) x.drawImage(e.patch, 0, 0, c.width, c.height);
  return c;
}

function hdrUI() { // the SDR-to-HDR switch shows for an EXR plate, when the model is there
  const p = S.plate;
  $("#hdr-switch").hidden = !(p && hdrPlate(p.spec) && S.hdrReady);
  $("#hdr-on").checked = S.toHdr;
}
function setHdr(on) { // off: renders end with the SDR shot, as for a video plate; each setting keeps its own renders
  S.toHdr = on;
  log(`SDR to HDR ${on ? "on: the full-size shot is made again in scene-linear values, then fitted to the plate" : "off"}`);
  hud(`SDR to HDR ${on ? "on" : "off"}`, 1500);
  hdrUI(); recompose(); touch();
}
$("#hdr-on").addEventListener("change", () => setHdr($("#hdr-on").checked));

function recompose() {
  S.hero = layered();
  const edits = S.edits.filter((e) => e.on && e.patch && e.state !== "generating").map((e) => `${e.id}.${e.version}`).join(",");
  const key = edits && hdrPlate(S.plate?.spec) && !S.toHdr ? `${edits}|sdr` : edits; // SDR to HDR switched off: another render
  if (key === S.heroKey) return;
  S.heroKey = key;
  const r = S.renders.get(key), pv = previewOf(r); // a set of edits seen before plays at once (a bypass turned back on, for example)
  S.exported = r?.exported ?? null;
  const best = r?.review ?? r?.raw ?? pv?.comp ?? pv?.raw; // the full quality, else the full-size shot, else the preview
  if (best) setShot(best, key, best === r?.review ? r.reviewSpace : "@model", best === r?.review ? r.reviewFrames : null);
  else if (!key) setShot(null, key);
  stagesUI(); exportUI();
}

function showLive(d) { // the shot as LTX predicts it, from step 1: in the frame until a shot exists, then in a corner
  const img = new Image(), key = S.heroKey, label = STAGES.find((x) => x.id === S.stage?.id)?.label ?? (keying() ? "Fluid shot" : "Generating");
  img.onload = () => {
    if (key !== S.heroKey) return;
    if (S.shot?.key === key) { // a preview or a full-size shot already plays: the pass on its way shows as an inset over it
      const box = $("#live-inset");
      box.querySelector("img").src = img.src;
      box.querySelector("figcaption").textContent = `${label}: step ${d.step}`;
      box.hidden = false;
      return;
    }
    S.live = img;
    hud(`Live preview, step ${d.step}: the shot follows`, 2000);
    if (!showLive.on) { showLive.on = true; const tick = () => { if (!S.live) { showLive.on = false; return; } render(); requestAnimationFrame(tick); }; tick(); }
  };
  img.src = viewUrl(d.image);
}

function hideLive() { $("#live-inset").hidden = true; } // the pass that sent it ended

function generating() { return !!(S.queued || S.piping || S.fluid?.busy); }
function escape() { // Esc: logic.escapeAction. A selection goes first; then the HUD says a second Esc stops what generates
  const busy = generating(), what = escapeAction({ editing: !!(S.draft || S.running), selected: !!S.selected, generating: busy });
  if (what === "discard") return discard();
  if (what === "deselect") { select(null); if (busy) hud("Deselected. Esc again stops generating", 2500); return; }
  if (what === "stop") stopGenerating();
}
function stopGenerating() { // everything that generates stops where it is: what finished is kept, and Enter goes on from there
  if (!generating()) return;
  S.halted = true;
  if (S.running) discard();
  cancel("fluid", ...BACKGROUND);
  hideLive();
  log("Stopped (Esc): what finished is kept. Enter goes on from where it stopped");
  hud("Stopped. Enter goes on from where it stopped", 3000);
  status("Stopped. Enter goes on from where it stopped.");
  stagesUI(); generateUI();
}

function setShot(src, key, space = "@model", frames = null) { // the shot on show, the colour space of its values, its EXR frames
  hideLive();
  S.live = null; // the shot itself, rough or composited, replaces the live preview
  S.shot = src ? { url: src, key, space, frames } : null;
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
  if (keying()) return renderFluid();
  wantDeep(); // once a colour value moves, the frames' own values load around the playhead, as OpenRV's cache does
  const W = view.width, H = view.height, still = !S.playing;
  const live = S.draft || stroke ? null : S.live; // while an edit is painted, the frame shows it, not the live preview of a render
  const first = still && S.frame === 0 && (!S.shot?.url || stale() || editingFirst());
  const pic = live || first || !S.shot?.url ? null : shotFrame();
  if (S.playing && S.shot?.url && !live && !pic) return; // the shot video catches up in a frame: the last frame stays on screen
  const p = S.plate, model = modelSpace(), exact = [];
  const draw = (src, space) => { // through OCIO from the colour space its values are in; false when it cannot draw yet
    const img = src ? look.image(src, S.display, space) : null;
    if (img) { ctx.drawImage(img, 0, 0, W, H); if (src.data) exact.push(true); }
    return !!img;
  };
  // the plate in its own values, so a new File Color Space shows at once: an image sequence's frames once they arrive,
  // else the playback video (a video plate's own values at the working size), else the first frame as ingested
  const drawPlate = () => {
    if (p.deep && draw(deep.get(S.frame), p.cs)) return;
    const cached = still && caches.get(plateVid).get(S.frame);
    if (cached) return void draw(cached, p.proxySpace);
    if (plateVid.readyState >= 2 && (!still || !plateVid.seeking)) return void draw(plateVid, p.proxySpace);
    if (S.frame === 0) draw(S.original, model);
  };
  const drawEdited = () => {
    if (live) { draw(live, model); return "live"; }
    if (pic) {
      if (!(S.shot.frames && draw(deepShot.get(S.frame), p.cs))) draw(pic, S.shot.space); // the review's EXR frames as they arrive
      if (pic === held.canvas) return "held";
      if (still) keepFrame(pic);
      return "shot";
    }
    if (still && S.frame === 0) { // the first frame with its edits, in the model space; with none, the plate itself
      if (S.heroKey) draw(S.hero, model); else drawPlate();
      overlays(W, H); return "hero";
    }
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
  view.dataset.precision = exact.length ? "float" : "8-bit"; // an image sequence's own values, or 8-bit frames
  drawCursor();
}

function renderFluid() { // a fluid shot: the keyframes on black, the shot LTX predicts, or the generated shot (the wipe shows both)
  const W = view.width, H = view.height, f = S.fluid;
  ctx.globalAlpha = 1;
  ctx.fillStyle = "#000";
  ctx.fillRect(0, 0, W, H);
  const cached = caches.get(shotVid).get(S.frame), made = !!f.result && f.result.sig === fluidSig();
  const shot = () => ctx.drawImage(look.image(cached || shotVid, S.display, modelSpace()), 0, 0, W, H); // a decoded frame first: no seek shows
  if (S.live && f.busy) ctx.drawImage(look.image(S.live, S.display, modelSpace()), 0, 0, W, H);
  else if (f.result && (S.playing ? made : f.view === "result") && !S.compare && (cached || shotReady())) { // playing a made shot: never the keyframes
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
  if (S.picking) return; // the picker shows a crosshair instead of the brush
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
  if (S.picking && e.button === 0) { e.preventDefault(); return pickAt(e); }
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
  if (keying()) return paintKey(e, rub);
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

function reopenDone(edit) { // a finished edit changes (strokes, words, the switch): strokes again until Generate; renders go on
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

const keying = () => !!S.fluid?.editing; // the fluid's keyframes are being painted: the first edit of a blank plate
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
  keying() ? $("#prompt").value.trim() : S.fluid.prompt ?? "", S.fluid.seed]); // the field holds another edit's words once the keyframes close

function staleFluid() { // the keyframes or the words changed: the shot on show comes from the old ones, and a run of the old ones stops
  historyUI(); // the fluid row says what changed
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
  fluidUI(); historyUI(); render();
  try {
    const keys = [];
    for (const k of [...f.keys].sort((a, b) => a.frame - b.frame)) // the control video's keyframes: the paint on black, at the shot's size
      redrawKey(k), keys.push({ frame: k.frame, image: await uploadCanvas(snap(k.canvas, size, "#000"), `fluid_v${v}_key${k.frame}.png`) });
    log(`Fluid v${v}: ${keys.length} keyframe(s) at ${keys.map((k) => p.first + k.frame).join(", ")}, ${size.join(" x ")}, ${p.frames} frames at ${p.fps} fps, seed ${f.seed}, prompt "${prompt}"`);
    status(`Fluid shot v${v}: one LTX 2.5 pass with ainvfx-fluid`);
    const out = await run("fluid", { path: f.blankPath ?? p.path, config: S.ocio.config, color_space: "@model", max_frames: p.frames, keys: JSON.stringify(keys), prompt, seed: f.seed,
      prefix: `${dir}/plate`, video_prefix: `${dir}/preview`, live: liveEvery() },
      { kind: "fluid", progress: (x) => { if (f.busy) { f.busy.progress = x; fluidUI(); fluidProgress(); } }, live: showLive }).done;
    let path = `${folderOf("fluid", out, "video")}/plate/${(f.blankPath ?? p.spec.source).split(/[\\/]/).pop()}`;
    if (f.depth === HDR_DEPTH) { // 16-bit: SDR to HDR makes the fluid shot an EXR plate, so every edit on it renders in HDR too
      const t1 = performance.now();
      status(`Fluid shot v${v}: SDR to HDR, one LTX 2.5 pass with Lightricks' IC-LoRA`);
      const made = await run("hdr", { path, config: S.ocio.config, max_frames: p.frames, fps: Math.round(p.fps), cond_fps: hdrFps(p.fps), prefix: `${dir}/hdr/f`, live: liveEvery() },
        { kind: "fluid", progress: (x) => { if (f.busy) { f.busy.progress = x; fluidUI(); fluidProgress(); } }, live: showLive }).done;
      path = folderOf("hdr", made, "hdr");
      log(`Fluid v${v}: SDR to HDR took ${((performance.now() - t1) / 1000).toFixed(1)} s: half-float EXR frames in ${path}`);
    }
    f.result = { v, sig, seed: f.seed, prompt, path, hdr: f.depth === HDR_DEPTH, preview: viewUrl(outputFile("fluid", out, "video")) };
    (f.made ??= new Map()).set(sig, f.result);
    f.view = "result";
    f.busy = null;
    setShot(f.result.preview, "fluid");
    log(`Fluid v${v}: done in ${((performance.now() - t0) / 1000).toFixed(1)} s: ${(outputText("fluid", out, "plate") ?? "").split("\n")[0]}`);
    f.editing = false; // the shot is made: it becomes the plate under the next edits, and the viewer plays it
    f.busy = null;
    await rebase();
    status(`Fluid shot v${v} is the plate under the next edits: Space plays it. Paint, erase or relight on it; the pencil on its History row returns to the keyframes.`);
  } catch (err) {
    if (err?.message !== "cancelled") quiet(err);
  } finally {
    if (f.busy?.v === v) f.busy = null;
    fluidUI(); historyUI(); render();
  }
}

function editFluid() { // the fluid's keyframes and words again; the edits on its shot stay until a new shot is made
  const f = S.fluid;
  if (!f || keying()) return;
  if (S.draft) launch(S.draft);
  Object.assign(S, { selected: null, peek: null });
  f.editing = true;
  pause(); seek(0);
  enterFluid(); historyUI();
}

function leaveKeys() { // the keyframes close: the viewer shows the plate the fluid shot made, with the edits on it
  S.fluid.editing = false;
  S.heroKey = null; recompose(); // the shot of the edits on show, or none
  fluidUI(); historyUI(); render();
}

async function rebase() { // the plate under the edits: the fluid shot when it is on and made, else the blank plate
  const f = S.fluid, made = f.on !== false && f.result, path = made ? f.result.path : f.blankPath;
  if (!path || S.plate?.path === path) { historyUI(); return render(); }
  await openPlate([], path, { under: true, cs: made && f.result.hdr ? undefined : modelSpace() }); // an HDR fluid shot: its EXR frames' own space
  log(`The plate under the edits: ${made ? `the fluid shot v${f.result.v}` : "the blank plate"}`); // once it is open
  if (S.edits.some((e) => e.on && e.state === "done")) queue(regenerateDependents); // made again on it, or taken back
}

async function toggleFluid() { // bypass: the blank plate under the edits; on again: the fluid shot
  const f = S.fluid;
  f.on = f.on === false;
  if (keying() && f.result) leaveKeys();
  historyUI();
  await rebase();
}

async function removeFluid() { // the fluid shot goes: the blank plate under the edits, and empty keyframes to paint again
  const f = S.fluid;
  cancel("fluid");
  Object.assign(f, { keys: [], result: null, on: true, prompt: "", busy: null });
  f.made?.clear();
  await rebase();
  if (keying()) { enterFluid(); historyUI(); } else editFluid();
}

function fluidProgress() { // the state line of the fluid row, without rebuilding History
  const el = $('#history li[data-id="fluid"] .state');
  if (el && S.fluid?.busy) el.textContent = `Generating ${Math.round((S.fluid.busy.progress ?? 0) * 100)}%`;
}

function fluidRow() { // the first edit of a blank plate: its fluid shot, which the next edits are painted on
  const f = S.fluid, li = document.createElement("li"), n = f.keys.length, on = f.on !== false;
  const stale = !!f.result && f.result.sig !== fluidSig();
  li.dataset.id = "fluid";
  li.className = [on ? "" : "off", f.busy ? "busy" : "", keying() ? "selected" : ""].join(" ").trim();
  li.innerHTML = `<img class="thumb" alt=""><div class="what"><span class="title"></span><small></small></div>
    <div class="acts"><button class="edit" title="Edit its keyframes and words">${ICON.edit}</button>
    <button class="eye" aria-pressed="${on}" title="${on ? "Bypass the fluid shot: the blank plate" : "Turn the fluid shot back on"}">${on ? ICON.eye : ICON.off}</button>
    <button class="again" title="Try another seed">${ICON.again}</button><button class="del" title="Remove the fluid shot">${ICON.del}</button></div>`;
  const first = [...f.keys].sort((x, y) => x.frame - y.frame)[0], img = li.querySelector(".thumb");
  if (first) img.src = snap(first.canvas, [120, 80], "#000").toDataURL("image/jpeg", 0.8); else img.removeAttribute("src");
  li.querySelector(".title").textContent = "1. Fluid";
  const what = f.prompt || `${n} keyframe${n === 1 ? "" : "s"}`, small = li.querySelector("small");
  if (f.busy) { small.innerHTML = '<span class="state"></span>'; small.firstChild.textContent = `Generating ${Math.round((f.busy.progress ?? 0) * 100)}%`; }
  else small.textContent = !on ? `Bypassed: ${what}` : !f.result ? `${what}: Enter generates` : stale ? `${what}: keyframes changed` : `v${f.result.v}: ${what}`;
  li.title = "The fluid shot of this blank plate: the next edits are painted on it";
  li.querySelector(".edit").onclick = () => editFluid();
  li.querySelector(".eye").onclick = () => toggleFluid().catch(quiet);
  li.querySelector(".again").onclick = () => { editFluid(); generateFluid(true).catch(quiet); };
  li.querySelector(".again").disabled = !n || !!f.busy;
  li.querySelector(".del").onclick = () => removeFluid().catch(quiet);
  li.onclick = (ev) => { if (!ev.target.closest("button")) editFluid(); };
  return li;
}

$("#b-depth").addEventListener("change", () => blankNote());
const blankForm = () => blankSpec({ width: $("#b-width").value, height: $("#b-height").value, fps: $("#b-fps").value, frames: $("#b-frames").value });

function blankNote() { // what the blank plate will be, snapped to what LTX and ainvfx-fluid take
  const s = blankForm();
  $("#b-note").textContent = `${s.width} × ${s.height}, ${s.frames} frames at ${s.fps} fps: ${(s.frames / s.fps).toFixed(2)} s.` +
    (s.frames === FLUID.tested ? "" : ` ${FLUID.tested} frames is the tested length.`) + (S.fluidReady ? "" : ` ${FLUID_MISSING}`) +
    (blankDepth($("#b-depth").value) === HDR_DEPTH ? (S.hdrReady ? " 16-bit: SDR to HDR turns the fluid shot and every edit on it into half-float EXR." : ` ${HDR_MISSING}`) : "");
  openGoUI();
}

async function openBlank() { // a black canvas LTX and ainvfx-fluid take, then a fluid shot on it
  if (!S.fluidReady) return status(FLUID_MISSING);
  const spec = blankForm(), depth = blankDepth($("#b-depth").value);
  if (depth === HDR_DEPTH && !S.hdrReady) return status(HDR_MISSING);
  const r = await post("/paintaplate/blank", spec);
  if (!r.ok) throw new Error(await r.text());
  const { path } = await r.json();
  $("#open").close();
  log(`Blank plate: ${spec.width} x ${spec.height}, ${spec.frames} frames at ${spec.fps} fps, ${depth}-bit (${path})`);
  await openPlate([], path, { fluid: { blankPath: path, depth }, cs: modelSpace() });
}

function fluidUI() { // the panel, the tools and the help of a fluid shot; none of it outside one
  const f = S.fluid, on = keying();
  $("#fluid").hidden = !on;
  if (S.plate) $("#render").hidden = on;
  $("#history-empty").textContent = on ? FLUID_HELP : HISTORY_HELP;
  for (const t of ["erase", "light"]) $(`.tools [data-tool="${t}"]`).disabled = on && !f.result; // they work on the fluid shot
  if (!on) return generateUI();
  const n = f.keys.length, busy = f.busy, r = f.result, stale = !!r && r.sig !== fluidSig();
  $("#spec").textContent = `Fluid shot on a blank plate: ${S.plate.spec.width} × ${S.plate.spec.height}, ${S.plate.fps} fps, ${S.plate.frames} frames`;
  $("#fluid-state").textContent = busy ? `generating ${Math.round((busy.progress ?? 0) * 100)}%`
    : r ? (stale ? "keyframes changed" : `v${r.v} ready`) : `${n} keyframe${n === 1 ? "" : "s"}`;
  $("#fluid-again").disabled = !n || !S.fluidReady;
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
  preempt(); // Generate: a full-size or export step in its first half stops for this edit, and runs again later
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
  m.set(edit.made, { patch: edit.patch, version: edit.version, foot: edit.foot, basis: edit.basis, base: edit.base, thumb: edit.thumb });
  while (m.size > RESULTS_KEPT) m.delete(m.keys().next().value);
}

async function regenerateDependents() {
  for (const e of [...S.edits]) if (e.on && e.state === "done" && needsRegen(e) && !reuse(e)) await generate(e); // a result made on this plate comes back
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
  $("#new-edit").disabled = !S.plate || keying() || (!S.draft && !S.selected);
  generateUI();
}

function nextEdit() { // New edit (N): the strokes in progress start now, and the next strokes make a separate edit
  if (!S.plate || keying()) return;
  if (S.draft) launch(S.draft);
  S.selected = null;
  $("#prompt").value = "";
  historyUI(); render();
  hud(`New edit: describe it, then paint. The tool stays ${NAME[S.tool]}.`, 2500);
}

function pickTool(t) { // the person picks a tool: another tool than the edit being worked on starts a new edit
  if (!keying() && toolEndsEdit({ draft: S.draft, current: S.selected }, t)) {
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
    redrawStrokes(edit); // in one pass from its strokes, as a scene opened again draws them: the same images, the same job
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
      mask: await uploadCanvas(maskAt(edit, size), `${tag}_mask.png`), ...editSettings(edit, size, QUICK), prefix: `paintaplate/${p.id}/edits/e${edit.id}` };
    log(`Edit ${num(edit)}: Klein quick pass at ${size.join(" x ")}, ${QUICK.steps} steps`);
    const quick = await run("edit", values, { kind: "edit", front: true, preview: show, progress: (f) => editProgress(edit, f / 2) }).done;
    if (!alive()) return;
    edit.preview = await loadImage(viewUrl(outputFile("edit", quick, "patch")));
    edit.shown ??= performance.now();
    edit.latent = null; render();
    // 2. The same seed at full size, starting from the quick pass: it resolves in place.
    status(`Edit ${num(edit)}: ${NAME[edit.tool].toLowerCase()}, full size`);
    log(`Edit ${num(edit)}: Klein full-size pass at ${p.work.join(" x ")}, ${FULL.steps} steps from the quick result at denoise ${FULL.denoise}${edit.tool === "erase" ? ", its fill levelled with the background around it (Level Fill)" : ""}`);
    const work = p.work, start = snap(before, work);
    start.getContext("2d").drawImage(edit.preview, 0, 0, work[0], work[1]);
    const startName = await uploadCanvas(start, `${tag}_start.png`);
    const full = await run("edit", { ...values, base: await baseUpload(below, before, work), start: startName,
      // an erase refines the quick result, which has no object left: shown the original, Klein drew part of it back
      reference: edit.tool === "erase" ? startName : await uploadCanvas(editImage(edit, before, work), `${tag}_ref_full.png`),
      mask: await uploadCanvas(maskAt(edit, work), `${tag}_mask_full.png`), ...editSettings(edit, work, FULL),
      relight: light ? 1 : 0, level: edit.tool === "erase" }, { kind: "edit", front: true, progress: (f) => editProgress(edit, 0.5 + f / 2) }).done;
    if (!alive()) return;
    // a relight shows the frame as the export will make it: Klein's light on the plate's own detail
    edit.patch = await loadImage(viewUrl(outputFile("edit", full, light ? "relit" : "patch")));
    Object.assign(edit, { preview: null, latent: null, state: "done", version: ++S.vers, force: false, kept: undefined }); // versions are unique: a kept result never meets a new one
    edit.foot = footprint(edit);
    edit.basis = activeBefore(edit).map(record);
    edit.base = S.plate.path; // the plate it was made on: a fluid shot, or its blank plate
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
const recordOf = (e) => JSON.stringify({ base: S.plate?.path, strokes: strokesSig(e.strokes), tool: e.tool, prompt: e.prompt, seed: e.seed, whole: !!e.whole });

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
const needsRegen = (edit) => edit.base !== S.plate?.path || dependsOnChange(edit, activeBefore(edit).map(record), edit.basis);

function rebuild() { // after a bypass, a removal or another try: make again only what depends on the change; renders go on
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
  preempt(); // another try is a Generate: a full-size or export step in its first half stops for it
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
  cancel("edit", "snap", "prefetch", "warm"); // the edits change; renders go on, and what they make stays
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
  else if (!S.draft && !keying()) $("#prompt").value = ""; // in a fluid shot the words belong to the shot, not to an edit
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
  edit: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 20h4L19 9l-4-4L4 16v4zM14 6l4 4"/></svg>',
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
  const fluid = S.fluid && (S.fluid.keys.length || S.fluid.result) ? [fluidRow()] : [];
  $("#history-empty").hidden = S.edits.length > 0 || fluid.length > 0;
  list.replaceChildren(...[...S.edits].reverse().map((e) => {
    const li = document.createElement("li");
    li.dataset.id = e.id;
    li.className = [e.on ? "" : "off", e.state === "generating" || e.state === "queued" || e.state === "drawing" ? "busy" : "",
      e.state === "failed" ? "failed" : "", S.selected === e ? "selected" : ""].join(" ").trim();
    li.innerHTML = `<img class="thumb" alt=""><div class="what"><span class="title"></span><small></small></div>
      <div class="acts"><button class="edit" title="Edit: its strokes and words come back on the first frame">${ICON.edit}</button><button class="eye" aria-pressed="${e.on}" title="${e.on ? "Bypass this edit" : "Turn this edit back on"}">${e.on ? ICON.eye : ICON.off}</button>
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
    li.querySelector(".edit").onclick = () => { if (keying()) leaveKeys(); pause(); seek(0); select(e); };
    li.querySelector(".eye").onclick = () => toggle(e);
    li.querySelector(".again").onclick = () => again(e);
    li.querySelector(".del").onclick = () => removeEdit(e);
    li.querySelector(".again").disabled = e.state === "drawing" || !e.strokes.length;
    li.onmouseenter = () => { S.hover = e; render(); };
    li.onmouseleave = () => { S.hover = null; render(); };
    li.onclick = (ev) => { if (!ev.target.closest("button")) { if (keying()) leaveKeys(); pause(); seek(0); select(S.selected === e ? null : e); } };
    return li;
  }), ...fluid);
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

// ---------- The render queue ----------
// Every set of edits shown since the plate opened is a render. Its steps fall in three classes: the preview, the full-size
// passes with the full-quality review, and the export, which runs only when Export asks for it. One step runs at a time:
// every preview before any full size, every full size before any export, and
// within a class the render on show first, then the most recently shown (logic.nextRender). Nothing stops a step but
// Generate: a bypass, an undo or another edit lets it finish, keeps its result, and the render resumes at its next step
// later. Generate stops a full-size or export step in its first half (logic.stopsForEdit), and that step runs again later.
// The last RENDERS_WANTED renders go on in the background; what every job made is also in the job index on disk.
const YIELD = new Error("yield"); // a render step gives way to an edit, or to a step of a more urgent render

function freeze(e) { // what a render needs of an edit, as it is now: a later change to the edit never reaches the render
  return { src: e, id: e.id, version: e.version, tool: e.tool, prompt: e.prompt, seed: e.seed, caption: e.caption?.text ?? "",
    patch: e.patch, mask: e.mask && snap(e.mask, S.plate.track) };
}

function want(key) { // the set of edits on show becomes the most recently shown render, made from what it is now
  let r = S.renders.get(key);
  if (!r) {
    const active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
    if (!active.length) return null;
    r = { key, v: ++S.run, previews: {}, active: active.map(freeze), heroFrame: S.hero,
      cleanFrame: active.some((e) => e.tool === "erase") ? layered(S.edits.length, (e) => e.tool === "erase") : null };
    r.base = `paintaplate/${S.plate.id}/v${r.v}`;
    S.renders.set(key, r);
  }
  r.wanted = ++S.wants;
  return r;
}

function nextClass(r) { // the class of a render's next step: "preview", "full" or "export"; null when it waits or is done
  if (r.failed) return null;
  plan(r, r.active);
  const pv = r.previews[S.plate.shot.join("x")] ?? {}, exporting = !!S.wantDownload && r.key === S.heroKey;
  for (const st of STAGES) {
    if (r.skip.has(st.id) || (st.preview ? pv : r).done?.[st.id] !== undefined) continue;
    return !st.final ? "preview" : !st.onDemand ? "full" : exporting ? "export" : null;
  }
  return null;
}

function pickRender() { // the render whose step runs next, among the most recently shown
  const recent = [...S.renders.values()].filter((r) => r.wanted).sort((a, b) => b.wanted - a.wanted).slice(0, RENDERS_WANTED);
  const id = nextRender(recent.map((r) => ({ id: r.key, cls: nextClass(r), current: r.key === S.heroKey, wanted: r.wanted,
    urgent: !!S.wantDownload && r.key === S.heroKey })));
  return id === null ? null : S.renders.get(id);
}

function preempt() { // Generate: a full-size or export step in its first half stops for the new edit, and runs again later
  const st = S.stage, r = S.piping;
  if (!st || !r) return;
  const def = STAGES.find((x) => x.id === st.id), cls = !def.final ? "preview" : st.id === "export" ? "export" : "full", pct = Math.round(st.progress * 100);
  if (!stopsForEdit({ cls, progress: st.progress })) return void log(`Render v${r.v}: ${def.label} finishes first (${pct}% done), then the new edit runs`);
  log(`Render v${r.v}: ${def.label} stops for the new edit at ${pct}%; it runs again later`);
  cancel(...BACKGROUND);
}

function idle() { // one render step at a time, from the render queue; the edits on the first frame go first
  if (!S.plate || S.halted) return; // Esc stopped what generates: Enter goes on
  if ((S.draft && S.edits.includes(S.draft)) || S.running || S.queued) return touch(); // an edit of this render changes; a new edit being painted lets it run
  if (S.heroKey) want(S.heroKey);
  if (S.piping) return; // the running step finishes; its render gives way at its next step when another must go first
  const r = pickRender();
  if (!r) return;
  S.piping = r;
  pipeline(r).catch((e) => {
    if (e === YIELD || e?.message === "cancelled") return;
    const st = STAGES.find((x) => x.id === S.stage?.id), mine = r.key === S.heroKey;
    r.failed = st?.id ?? "render"; // it waits for Generate, which tries it again
    const err = explained(e, `${st?.label ?? "The render"}${mine ? "" : ` of v${r.v}, in the background,`}`);
    if (mine) { quiet(err); S.wantDownload = null; } else log(err.message, "error");
  }).finally(() => { S.piping = null; S.stage = null; hideLive(); stagesUI(); exportUI(); generateUI(); touch(); });
}

const liveEvery = () => (S.vram >= LIVE.vram ? LIVE.every : 0); // steps between live previews, 0 for none
const grow = (w, erase) => Math.max(4, Math.round(w / (erase ? COMPOSITE_GROW.erase : COMPOSITE_GROW.other))); // pixels at width w
const feather = (w) => Math.max(6, Math.round(w / COMPOSITE_FEATHER));

// Every step of a render, in order. `preview` steps run at the preview size, once per size, so going back to a size plays what
// it made at once. `final` steps run at full size right after them: the passes, then the full-quality review the viewer plays.
// The export (`onDemand`) writes the result for compositing software, only when Export asks for it.
const STAGES = [
  { id: "erase", label: "Track the erase", ref: 6 }, { id: "clean", label: "Erase pass", ref: 10, preview: true },
  { id: "shot", label: "Shot", ref: 20, preview: true }, { id: "track", label: "Track the paint", ref: 5, preview: true },
  { id: "comp", label: "Composite", ref: 14, preview: true },
  { id: "cleanfull", label: "Erase pass at full size", ref: 32, final: true }, { id: "full", label: "Shot at full size", ref: 45, final: true },
  { id: "trackfull", label: "Track at full size", ref: 5, final: true }, { id: "hdr", label: "SDR to HDR", ref: 45, final: true },
  { id: "review", label: "Full quality", ref: 12, final: true },
  { id: "export", label: "Export", ref: 10, final: true, onDemand: true },
];
const previewOf = (r) => r?.previews?.[S.plate.shot.join("x")]; // what this preview size made for a set of edits
const doneOf = (r, st) => (st.preview ? previewOf(r) : r)?.done?.[st.id]; // seconds a step took, if it ran
S.took = {}; // measured seconds per step, for this plate: the next estimates use them

function plan(r, active) { // the steps this set of edits needs: the erase pass for erases, Ripple for paint and light, no second size when the preview is full size
  const p = S.plate, [sw, sh] = p.shot, onePass = sw === p.work[0] && sh === p.work[1];
  const erase = active.some((e) => e.tool === "erase"), paint = active.some((e) => e.tool === "paint"), carry = active.some((e) => e.tool !== "erase");
  r.skip = new Set([!erase && "erase", !erase && "clean", !carry && "shot", !paint && "track", (onePass || !erase) && "cleanfull",
    (onePass || !carry) && "full", (onePass || !paint) && "trackfull",
    !(S.hdrReady && wantsHdr(p.spec, active.map((e) => e.tool), !r.key?.endsWith("|sdr"))) && "hdr"].filter(Boolean)); // the switch is in the key
  return r;
}

function estimate(id) { // seconds: what this step took last time, or a measured reference scaled to this plate
  if (S.took[id]) return S.took[id];
  const p = S.plate, ref = 928 * 512 * 97;
  const big = ["full", "cleanfull", "hdr", "review", "export"].includes(id);
  const size = big ? p.work : ["erase", "track", "trackfull"].includes(id) ? p.track : p.shot;
  const scale = (size[0] * size[1] * p.frames) / ref * (big ? 0.73 : 1);
  return STAGES.find((x) => x.id === id).ref * Math.max(0.25, scale);
}

async function step(r, id, work, store = r) { // run one step of a render, timed and shown; preview steps keep their result per size
  if (store.done?.[id] !== undefined || r.skip?.has(id)) return;
  if (S.running || S.queued || pickRender() !== r) throw YIELD; // an edit, or a step of a more urgent render, goes first
  const t0 = performance.now(), behind = r.key === S.heroKey ? "" : ", in the background";
  S.stage = { key: r.key, id, progress: 0, t0 };
  stagesUI();
  log(`Render v${r.v}: ${STAGES.find((x) => x.id === id).label} (about ${Math.round(estimate(id))} s)${behind}`);
  await work((f) => { if (S.stage?.id === id) { S.stage.progress = f; stagesUI(); } });
  hideLive();
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

async function pipeline(r) { // a render's steps in order; a step made already is skipped, so a render resumes where it stopped
  const p = S.plate, key = r.key, active = r.active, here = () => key === S.heroKey; // here: the render on show
  cancel("warm");
  plan(r, active);
  const [sw, sh] = p.shot, sized = `${sw}x${sh}`, pv = (r.previews[sized] ??= {}), base = r.base;
  const relight = active.some((e) => e.tool === "light"), erases = active.filter((e) => e.tool === "erase"), erase = erases.length > 0;
  const carry = active.some((e) => e.tool !== "erase"); // paint and light: Ripple carries them through the shot
  // what the erases make depends on the erases alone: kept by them, so a render with the same erases uses it again (a paint
  // added over an erase tracked and cleaned it all a second time, 28 Oct)
  const ekey = erases.map((e) => `${e.id}.${e.version}`).join(",");
  const E = erase ? S.erases.get(ekey) ?? S.erases.set(ekey, { sizes: {} }).get(ekey) : null;
  r.hero ??= await uploadCanvas(r.heroFrame, `hero_v${r.v}.png`);
  if (erase) r.clean0 ??= E.clean0 ??= await uploadCanvas(r.cleanFrame, `clean_v${r.v}.png`);
  const common = { config: S.ocio.config, color_space: p.cs, max_frames: p.frames, seed: active[0].seed };
  const prompt = shotPrompt(active.map((e) => ({ tool: e.tool, words: e.prompt })));
  const scene = erase ? erasePrompt(erases.map((e) => e.caption)) : ""; // the scene as it stays, never the erased object
  if (!r.told) {
    r.told = true;
    log(`Render v${r.v}: ${active.length} edit(s) (${active.map((e) => `${num(e.src)} ${NAME[e.tool]}`).join(", ")}), preview at ${sized}, seed ${common.seed}, steps: ${STAGES.filter((st) => !r.skip.has(st.id)).map((st) => st.id).join(" > ")}`);
    if (carry) log(`Render v${r.v}: LTX prompt: ${prompt}`);
    if (erase) log(`Render v${r.v}: erase pass prompt: ${scene || "none"}`);
  }
  // the erase is tracked on the plate first: the erase pass regenerates its areas, the composite keeps them
  if (E?.erased) reused(r, r, "erase", () => { r.erased = E.erased; });
  await step(r, "erase", async (progress) => { r.erased = E.erased = await track(active, null, base, "", progress, null, ["erase"]); });
  const cleanAt = async (size, progress, live) => { // the erase pass at `size`, kept by the erases: a preview, or the full size's first stage
    const at = `${size[0]}x${size[1]}`, kept = (E.sizes[at] ??= {}), show = live && here();
    if (kept.clean) return kept;
    const out = await run("clean", { ...common, seed: erases[0].seed, path: p.path, hero: r.clean0, hole: r.erased.found.matte_a, prompt: scene,
      width: size[0], height: size[1], prefix: `${base}/${at}/clean/f`, video_prefix: `${base}/${at}/clean`, live: show ? liveEvery() : 0 },
      { kind: "clean", progress, live: show ? showLive : null }).done;
    return Object.assign(kept, { clean: folderOf("clean", out, "frames"), raw: viewUrl(outputFile("clean", out, "video")) });
  };
  const passes = async (store, size, dir, final) => { // the erase pass makes a clean plate; Ripple carries paint and light over it
    const id = final ? "cleanfull" : "clean", kept = erase && (final ? E.full : E.sizes[`${size[0]}x${size[1]}`]);
    if (kept?.clean) reused(r, store, id, () => Object.assign(store, { clean: kept.clean, raw: kept.raw }));
    await step(r, id, async (progress) => {
      if (!final) return void Object.assign(store, await cleanAt(size, progress, true));
      // at full size, Lightricks' two stages: the erase pass at half the working size (the preview's own when it is that size),
      // then 2 steps at full size from it, without the reference video. 8 steps at full size took 181 s on a 1080p plate (28 Oct)
      const low = stageOne(p.work), first = await cleanAt(low, (f) => progress(f / 2), true);
      log(`Render v${r.v}: erase pass at full size, 2 steps from the erase pass at ${low.join(" x ")}`);
      const out = await run("cleanup", { ...common, seed: erases[0].seed, path: p.path, hero: r.clean0, hole: r.erased.found.matte_a, prompt: scene,
        low: first.clean, width: size[0], height: size[1], prefix: `${base}/${dir}/clean/f`, video_prefix: `${base}/${dir}/clean`, live: here() ? liveEvery() : 0 },
        { kind: "clean", progress: (f) => progress(0.5 + f / 2), live: here() ? showLive : null }).done;
      E.full = { clean: folderOf("cleanup", out, "frames"), raw: viewUrl(outputFile("cleanup", out, "video")) };
      Object.assign(store, E.full);
    }, store);
    await step(r, final ? "full" : "shot", async (progress) => {
      const plate = erase ? { path: store.clean, color_space: "@model" } : { path: p.path }, show = here();
      const out = await run("shot", { ...common, ...plate, hero: r.hero, prompt, width: size[0], height: size[1],
        prefix: `${base}/${dir}/shot/f`, video_prefix: `${base}/${dir}/raw`, live: show ? liveEvery() : 0 },
        { kind: "shot", progress, live: show ? showLive : null }).done;
      store.shot = folderOf("shot", out, "frames");
      store.raw = viewUrl(outputFile("shot", out, "video"));
    }, store);
    return carry ? store.shot : store.clean;
  };
  const made = await passes(pv, p.shot, sized, false);
  if (here() && !pv.comp && !r.review && S.shot?.url !== pv.raw) { // a rough look at once: the whole frame as the model made it, until the composite
    setShot(pv.raw, key, "@model");
    hud("Rough preview: Space plays it. The composite follows.", 2500);
  }
  await step(r, "track", async (progress) => { pv.painted = await track(active, made, base, `_${sized}`, progress, null, ["paint"],
    erase ? { path: pv.clean, cs: "@model" } : { path: p.path, cs: p.cs }, r.heroFrame); }, pv);
  pv.mattes = mattesOf({ ...r.erased?.found, ...pv.painted?.found });
  await step(r, "comp", async (progress) => {
    const comp = await run("comp", { path: p.path, config: S.ocio.config, color_space: p.cs, max_frames: p.frames, width: sw, height: sh, shot: made,
      ...pv.mattes.values, relight, grow: grow(sw, erase), feather: feather(sw), grain: 0, video_prefix: `${base}/${sized}/comp` },
      { kind: "comp", progress }).done;
    pv.comp = viewUrl(outputFile("comp", comp, "video"));
  }, pv);
  if (here() && !r.review && S.shot?.url !== pv.comp) {
    setShot(pv.comp, key, "@model");
    hud("The preview is ready: Space plays it. The full quality follows.", 2500);
    status("The preview is ready. The full-size passes and the full-quality review follow; Export writes the result when you need it.");
  }
  const onePass = sw === p.work[0] && sh === p.work[1];
  const final = onePass ? made : await passes(r, p.work, "full", true);
  if (here() && !onePass && !r.review && r.raw && S.shot?.url !== r.raw) { // the full-size shot as LTX made it, until the full quality:
    setShot(r.raw, key, "@model"); // the preview size can lose an effect that the full size keeps (a fire faded by 85% at 640, 28 Oct)
    hud("Full size: Space plays the shot as LTX made it. The full quality follows.", 2500);
    log(`Render v${r.v}: the viewer plays the full-size shot until the full quality is ready`);
  }
  await step(r, "trackfull", async (progress) => { r.full = await track(active, final, base, "_full", progress, pv.mattes, ["paint"],
    erase ? { path: onePass ? pv.clean : r.clean, cs: "@model" } : { path: p.path, cs: p.cs }, r.heroFrame); });
  r.full ??= pv.mattes;
  await step(r, "hdr", async (progress) => { // SDR to HDR: the full-size shot made again in scene-linear values; review fits it to the plate
    const out = await run("hdr", { path: final, config: S.ocio.config, max_frames: p.frames, fps: Math.round(p.fps), cond_fps: hdrFps(p.fps),
      prefix: `${base}/full/hdr/f`, live: here() ? liveEvery() : 0 }, { kind: "hdr", progress, live: here() ? showLive : null }).done;
    r.hdr = folderOf("hdr", out, "hdr");
  });
  const hdr = { hdr: r.hdr ?? "", hdr_grow: grow(p.spec.width, erase) + feather(p.spec.width) }; // HDR Match leaves the composite's edge out
  await step(r, "review", async (progress) => { // the full-size composite at the plate's quality, which the viewer plays once made
    const out = await run("review", { path: p.path, config: S.ocio.config, color_space: p.cs, max_frames: p.frames, shot: final, ...hdr, ...r.full.values,
      relight, grow: grow(p.spec.width, erase), feather: feather(p.spec.width), movie_space: p.deep ? "@model" : p.cs,
      review_prefix: `${base}/review`, frames_prefix: p.deep ? `${base}/review/frames` : "" }, { kind: "review", progress }).done;
    const movie = outputFile("review", out, "review"), frame = p.deep ? outputFile("review", out, "frames") : null;
    Object.assign(r, { review: viewUrl(movie), reviewSpace: p.deep ? "@model" : p.cs, run: movie?.subfolder ?? base, // the render's folder,
      reviewFrames: frame ? `output:${frame.subfolder}/${framePattern(frame.filename)}` : null }); // wherever the job index took it from
  });
  if (!here()) return log(`Render v${r.v}: the full quality is ready, in the background`);
  setShot(r.review, key, r.reviewSpace, r.reviewFrames);
  hud("Full quality: the viewer plays the full-size composite", 2500);
  stagesUI(); exportUI();
  if (!S.wantDownload) return status(`Full quality: the viewer plays the full-size composite${p.deep ? ", its EXR frames at full precision as they load" : ""}. Export writes the result for compositing software.`);
  await step(r, "export", async (progress) => { // only when Export asks: the plate's own format, and the matte, beside the review
    const dir = r.run ?? base, done = await run("export", { path: p.path, config: S.ocio.config, color_space: p.cs, max_frames: p.frames, shot: final, ...hdr,
      ...r.full.values, relight, keep_untouched: !relight, prefix: `${dir}/export`, matte_prefix: `${dir}/matte/matte`,
      grow: grow(p.spec.width, erase), feather: feather(p.spec.width) }, { kind: "export", progress }).done;
    const file = outputFile("export", done, "export"); // a job taken from the index keeps its own folder
    r.exported = { run: file ? file.subfolder.replace(/\/export$/, "") : dir, name: `${p.name}_paintaplate_v${r.v}`, text: outputText("export", done, "export") ?? "" };
  });
  S.exported = r.exported;
  stagesUI(); exportUI();
  status(`Exported to the output folder: ${S.exported.text.split("\n")[0]}.`);
  log(`Export v${r.v}: ${S.exported.text.replace(/\n/g, "; ")}`);
  const parts = S.wantDownload;
  S.wantDownload = null;
  download(parts);
}

function elementOf(zones, size, hero = S.hero) { // where the edits changed the first frame, inside the paint zones: the paint matte starts here
  const [w, h] = size, data = (c) => c.getContext("2d").getImageData(0, 0, w, h).data;
  const bits = changedMask(data(snap(hero, size)), data(snap(S.original, size)), data(zones), FOLLOW.seed);
  const c = canvas(size), x = c.getContext("2d"), img = x.createImageData(w, h);
  for (let i = 0; i < w * h; i++) img.data.fill(bits[i] ? 255 : 0, i * 4, i * 4 + 3), (img.data[i * 4 + 3] = 255);
  x.putImageData(img, 0, 0);
  return c;
}

async function track(active, shotPath, base, suffix, progress, previous, tools, under = null, hero = S.hero) { // SAM 3.1 follows a kind of edit through the shot; `under`: the plate the shot was made over
  const p = S.plate, found = { ...(previous?.found ?? {}) };
  for (const [key, tool, path, cs] of [["matte_a", "erase", p.path, p.cs], ["matte_b", "paint", shotPath, "@model"]]) {
    const edits = active.filter((e) => e.tool === tool);
    if (!edits.length || !tools.includes(tool)) continue; // the erase follows the plate; the paint follows the shot
    const size = tool === "erase" ? p.trackErase : p.track, [sw, sh] = size;
    const union = canvas(size), u = union.getContext("2d");
    u.fillStyle = "#000"; u.fillRect(0, 0, sw, sh);
    u.globalCompositeOperation = "lighten";
    for (const e of edits) u.drawImage(tool === "paint" ? whiteOf(e.patch) : e.mask, 0, 0, sw, sh);
    const compare = tool === "paint" && under ? { base: under.path, base_color_space: under.cs } : {}; // the paint matte follows what the shot changed
    if (tool === "paint") compare.seed = await uploadCanvas(elementOf(union, size, hero), `seed${suffix}.png`); // from what the edits changed
    const out = await run("matte", { path, config: S.ocio.config, color_space: cs, max_frames: p.frames, width: sw, height: sh, prefix: `${base}/${key}${suffix}/m`,
      mask: await uploadCanvas(union, `${key}${suffix}.png`), zone: FOLLOW.zone, threshold: FOLLOW.threshold, ...compare },
      { kind: "matte", progress }).done;
    const note = outputText("matte", out, "follow");
    if (note) log(`${tool === "erase" ? "Erase" : "Paint"} matte${suffix ? ` (${suffix.slice(1)})` : ""}: ${note}`);
    found[key] = folderOf("matte", out, "frames");
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

function renderLeft(finalToo = false) { // seconds until the preview, or the full quality (and the export once asked for), is ready
  const p = S.plate, r = S.renders.get(S.heroKey), exporting = !!S.wantDownload;
  if (!p || !S.heroKey || (finalToo ? (exporting ? r?.exported : r?.review) : previewOf(r)?.comp || r?.review)) return 0;
  const active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
  const skip = r?.skip ?? plan({}, active).skip;
  let t = 0;
  for (const st of STAGES) {
    if (st.final && !finalToo) break;
    if (skip.has(st.id) || doneOf(r, st) !== undefined || (st.onDemand && !exporting)) continue;
    const est = estimate(st.id);
    if (S.stage?.id === st.id && S.stage.key === S.heroKey) {
      const run = (performance.now() - S.stage.t0) / 1000, f = S.stage.progress;
      t += f > 0.05 ? Math.max(0, run * (1 - f) / f) : Math.max(est - run, est * 0.2);
    } else t += est;
  }
  return t;
}

function stagesUI() {
  hdrUI(); // the Render panel: every step, done, running or waiting, and the time left
  const list = $("#stages"), p = S.plate, r = S.renders.get(S.heroKey);
  const active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
  $("#render").hidden = !p || keying();
  list.hidden = !active.length;
  if (!p || !active.length) { $("#render-left").textContent = ""; return timelineBar(); }
  const skip = r?.skip ?? plan({}, active).skip, later = (st) => st.onDemand && !S.wantDownload; // the export waits for Export
  list.replaceChildren(...STAGES.filter((st) => !skip.has(st.id)).map((st) => {
    const li = document.createElement("li"), took = doneOf(r, st);
    const now = S.stage?.id === st.id && S.stage.key === S.heroKey;
    li.className = took !== undefined ? "done" : now ? "now" : later(st) ? "later" : "";
    li.innerHTML = '<span class="dot"></span><span class="name"></span><span class="time"></span>';
    li.children[1].textContent = st.label;
    li.children[2].textContent = took !== undefined ? `${Math.round(took)} s` : now ? `${Math.round(S.stage.progress * 100)}%`
      : later(st) ? "on Export" : `~${Math.round(estimate(st.id))} s`;
    return li;
  }));
  const pre = renderLeft(), all = renderLeft(true);
  const busy = S.stage?.key === S.heroKey, what = S.wantDownload ? "export" : "full quality";
  $("#render-left").textContent = stale() || !(previewOf(r)?.comp || r?.review) ? (pre ? `preview ${secs(pre)}` : busy ? "preview almost ready" : "")
    : r?.exported ? "exported" : r?.review && !S.wantDownload ? "full quality" : all ? `${what} ${secs(all)}` : busy ? `${what} almost ready` : "";
  timelineBar();
}

function timelineBar() { // the line under the timeline: the preview in gold, then the full quality in grey, green once it plays
  const bar = $("#tl-render"), r = S.renders.get(S.heroKey);
  bar.className = "tl-render";
  if (!S.plate || !S.heroKey || !r) { bar.style.width = "0"; if (S.heroKey && stale()) bar.classList.add("stale"); return; }
  const steps = STAGES.filter((st) => !r.skip?.has(st.id) && (!st.onDemand || S.wantDownload || r.exported));
  const total = steps.reduce((a, st) => a + estimate(st.id), 0);
  let done = steps.reduce((a, st) => a + (doneOf(r, st) !== undefined ? estimate(st.id) : 0), 0);
  if (S.stage?.key === S.heroKey) done += estimate(S.stage.id) * S.stage.progress;
  bar.style.width = `${Math.round((done / Math.max(1, total)) * 100)}%`;
  if (r.review) bar.classList.add("ready");
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
  $("#tl-key").hidden = keying() || !S.edits.some((e) => e.on && e.patch);
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
  const r = S.renders.get(S.heroKey), kind = S.plate.spec.kind;
  $("#x-format").textContent = kind === "video" ? `${S.plate.spec.codec} movie` : `${S.plate.spec.ext.slice(1).toUpperCase()} ${kind}`;
  $("#x-note").textContent = r?.exported ? "Written: the zip downloads at once."
    : r?.review ? "Export writes the result and its matte from the full-quality shot, in seconds, then the zip downloads."
    : `The full quality finishes first, ${secs(renderLeft(true)) || "in a moment"}; then the export is written and the zip downloads.`;
  $("#export").showModal();
}

function setTool(t) {
  if (keying() && t !== "paint") { // another tool closes the fluid's keyframes: it works on the plate the fluid shot made
    if (!S.fluid.result) return hud(`${NAME[t]} works on the fluid shot: generate it first (Enter)`, 3000);
    leaveKeys();
  }
  S.tool = t;
  S.rub = false;
  $("#rub-btn").setAttribute("aria-pressed", "false");
  $$(".tools [data-tool]").forEach((b) => b.classList.toggle("on", b.dataset.tool === t));
  $("#prompt").placeholder = keying() ? FLUID_HINT : HINT[t];
  colorUI();
  render();
}

function setSize(v) {
  S.size = Math.max(4, Math.min(320, Math.round(v)));
  $("#size").value = S.size;
  $("#size-out").textContent = S.size;
  render();
}

// ---------- The Open dialog: ComfyUI's files, an upload, a scene, a blank plate ----------
// One tab per source. ComfyUI files browses the input and output folders and their subfolders: videos, animated images and
// image sequences, each sequence named by its frame pattern. Items are drawn BROWSE_PAGE at a time as the list scrolls, and
// each thumbnail is fetched only when it shows, so a folder of thousands of outputs opens at once. A click reads one item.
const BROWSE_PAGE = 120;
const OPEN = { tab: "files", at: "", by: "name", ...saved("paintaplate.open"), items: [], shown: 0, chosen: null, scene: null };
const keepOpen = () => { try { localStorage.setItem("paintaplate.open", JSON.stringify({ tab: OPEN.tab, at: OPEN.at, by: $("#browse-sort").value })); } catch { /* this session only */ } };
const ITEM_ICON = { folder: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M3 7h6l2 2h10v10H3z"/></svg>',
  scene: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4 5h16v14H4zM4 9h16M9 5l-2 4M15 5l-2 4"/></svg>' };

function openDialog() {
  for (const id of ["#files", "#scene", "#path"]) $(id).value = "";
  Object.assign(OPEN, { chosen: null, scene: null });
  $("#browse-sort").value = OPEN.by;
  for (const id of ["#files-note", "#browse-info"]) $(id).textContent = "";
  blankNote(); showTab(OPEN.tab); $("#open").showModal();
  browse(OPEN.at).catch(() => browse("").catch(quiet));
  listScenes().catch(quiet);
}

function showTab(tab) {
  OPEN.tab = tab; keepOpen();
  for (const b of $$("#open [role=tab]")) b.setAttribute("aria-selected", String(b.dataset.tab === tab));
  for (const panel of $$("#open .tab")) panel.hidden = panel.dataset.tab !== tab;
  openGoUI();
}

function openGoUI() { // the Open button names what it opens, and waits for something to open
  const t = OPEN.tab, b = $("#open-go");
  b.textContent = { files: "Open", upload: "Upload and open", scenes: "Open the scene", blank: "Open a blank plate" }[t];
  b.disabled = t === "files" ? !(OPEN.chosen || $("#path").value.trim()) : t === "upload" ? !$("#files").files.length
    : t === "scenes" ? !(OPEN.scene || $("#scene").files.length) : !S.fluidReady;
}

async function browse(path) { // a folder of the input or output folder, listed with no file opened
  const r = await fetch(`/paintaplate/browse?${new URLSearchParams({ path })}`), got = await r.json();
  if (!r.ok) throw new Error(got.error ?? "No such folder");
  Object.assign(OPEN, { at: got.path, items: got.items, singles: got.singles, chosen: null });
  keepOpen();
  $("#crumbs").replaceChildren(...crumbs(got.path).map((c, i, all) => Object.assign(document.createElement("button"),
    { type: "button", textContent: c.label, disabled: i === all.length - 1, onclick: () => browse(c.path).catch(quiet) })));
  for (const b of $$("#open [data-root]")) b.classList.toggle("on", got.path.startsWith("output:") === (b.dataset.root === "output:"));
  $("#browse-info").textContent = "";
  drawBrowse();
  openGoUI();
}

const browseList = () => browseItems(OPEN.items, { query: $("#browse-find").value, by: $("#browse-sort").value });

function drawBrowse(more = false) { // the folder's items, sorted and filtered: BROWSE_PAGE more each time the list nears its end
  const box = $("#browse"), list = browseList();
  if (!more) { box.replaceChildren(); OPEN.shown = 0; box.scrollTop = 0; }
  const next = list.slice(OPEN.shown, OPEN.shown + BROWSE_PAGE);
  OPEN.shown += next.length;
  box.append(...next.map(browseItem));
  const singles = OPEN.singles ? ` ${OPEN.singles} single image${OPEN.singles === 1 ? " is" : "s are"} not listed: a plate is a video or a sequence.` : "";
  $("#browse-note").textContent = OPEN.items.length ? `${list.length} item${list.length === 1 ? "" : "s"}${list.length < OPEN.items.length ? ` of ${OPEN.items.length}` : ""}.${singles}`
    : `Nothing to open here.${singles}`;
}

function browseItem(it) {
  const b = document.createElement("button");
  Object.assign(b, { type: "button", className: `item ${it.kind}`, title: it.path });
  b.dataset.path = it.path;
  b.setAttribute("role", "option");
  b.innerHTML = '<span class="thumb"></span><span class="name"></span><small></small>';
  b.children[1].textContent = it.name;
  b.children[2].textContent = { folder: "Folder", scene: "Scene" }[it.kind] ?? (it.kind === "sequence" ? `${it.frames} frames · ${gb(it.size)}` : gb(it.size));
  if (it.kind === "video" || it.kind === "sequence") {
    const img = Object.assign(new Image(), { alt: "", loading: "lazy", decoding: "async", onerror: () => img.remove(),
      src: `/paintaplate/thumb?${new URLSearchParams({ path: it.path, v: Math.round(it.mtime) })}` });
    b.firstChild.append(img);
  } else b.firstChild.innerHTML = ITEM_ICON[it.kind];
  b.onclick = () => (it.kind === "folder" ? browse(it.path).catch(quiet) : chooseItem(it, b).catch(quiet));
  b.ondblclick = () => { if (it.kind !== "folder") $("#open-go").click(); };
  return b;
}

async function chooseItem(it, b) { // one click: the item's details, read from the file; a double click opens it
  OPEN.chosen = it;
  $("#path").value = "";
  for (const x of $$("#browse .item.on")) x.classList.remove("on");
  b.classList.add("on");
  openGoUI();
  const info = $("#browse-info");
  if (it.kind === "scene") return void (info.textContent = `${it.name}: a scene, opened with its plate and every edit`);
  info.textContent = `${it.name}: reading the file`;
  const r = await fetch(`/paintaplate/stat?${new URLSearchParams({ path: it.path, config: S.ocio.config })}`), st = await r.json();
  if (OPEN.chosen !== it) return;
  const fmt = st.kind === "video" ? `${st.codec} ${st.pix_fmt ?? ""}`.trim() : `${(st.ext ?? "").slice(1).toUpperCase()} frames`;
  info.textContent = r.ok ? `${it.name}: ${st.width} × ${st.height}, ${st.frames} frames${st.kind === "video" ? ` at ${Math.round(st.fps * 1000) / 1000} fps` : ""}, ${fmt}, ${gb(st.size)}. Colour space: ${st.color_space}.`
    : `${it.name} cannot be opened: ${st.error ?? r.status}`;
}

async function listScenes() { // scenes saved on this ComfyUI, newest first: a click picks one, a double click opens it
  const items = await (await fetch("/paintaplate/scenes")).json();
  $("#scenes").replaceChildren(...items.map((sc) => {
    const li = document.createElement("li"), b = document.createElement("button"), a = document.createElement("a");
    Object.assign(b, { type: "button", className: "scene" });
    b.innerHTML = '<span class="name"></span><small></small>';
    b.children[0].textContent = sc.name;
    b.children[1].textContent = `${sc.plate || "plate"} · ${sc.edits} edit${sc.edits === 1 ? "" : "s"} · ${new Date(sc.mtime * 1000).toLocaleString()}`;
    b.onclick = () => { OPEN.scene = sc.name; $("#scene").value = ""; for (const x of $$("#scenes .scene.on")) x.classList.remove("on"); b.classList.add("on"); openGoUI(); };
    b.ondblclick = () => { b.onclick(); $("#open-go").click(); };
    Object.assign(a, { href: `/paintaplate/scenes/${encodeURIComponent(sc.name)}`, download: `${sc.name}.paintaplate.json`, textContent: "Download" });
    li.append(b, a);
    return li;
  }));
  $("#scenes-empty").hidden = items.length > 0;
}

function filesUI() { // what the Upload tab will send
  const files = [...$("#files").files], total = files.reduce((a, f) => a + f.size, 0);
  $("#files-note").textContent = !files.length ? "" : files.length === 1 ? `${files[0].name}, ${gb(total)}` : `${files.length} files, ${gb(total)}: the frames of one sequence`;
  openGoUI();
}

const sceneFile = (path) => { // a scene found by browsing, read through ComfyUI's own /view
  const out = path.startsWith("output:"), rel = path.slice(out ? 7 : 0), i = rel.lastIndexOf("/");
  return viewUrl({ filename: rel.slice(i + 1), subfolder: i < 0 ? "" : rel.slice(0, i), type: out ? "output" : "input" });
};

// ---------- Scenes: the plate and every edit with its strokes, words and seed, in a file to open again ----------

// Strokes as drawn, in pixels of the working size the scene names (`work`, scene version 2): opened again on the same
// plate they come back exactly, so the images made from them are the same files and the job index knows their jobs.
// Version 1 kept fractions of the frame rounded to five places, which moved a stroke by a few thousandths of a pixel.
const packStrokes = (strokes) => strokes.map((s) => ({ tool: s.tool, color: s.color, size: s.size, points: s.points.map(([x, y, pr]) => [x, y, pr]) }));
const unpackStrokes = (saved, [W, H], from) => { // `from`: the scene's own working size; none for a version 1 scene
  const [kx, ky] = from ? [W / from[0], H / from[1]] : [W, H];
  return saved.map((s) => ({ tool: s.tool, color: s.color, size: s.size * kx, points: s.points.map(([x, y, pr]) => [x * kx, y * ky, pr]) }));
};

async function saveScene() { // on this ComfyUI: Open plate > Scenes opens it again, or downloads it
  const work = S.plate.work, f = S.fluid, { config, display, view, look: lk } = S.ocio;
  const scene = { ...SCENE, saved: new Date().toISOString(), work, ocio: { config, display, view, look: lk },
    plate: { path: S.fluid?.blankPath ?? S.plate.path, color_space: S.plate.cs, name: S.plate.name },
    preview: S.previewCap, hdr: S.toHdr, in: S.inPt, out: S.outPt,
    edits: S.edits.map((e) => ({ tool: e.tool, color: e.color, prompt: e.prompt, seed: e.seed, whole: !!e.whole, on: e.on,
      caption: e.caption?.text ?? "", strokes: packStrokes(e.strokes) })),
    ...(f ? { fluid: { prompt: keying() ? $("#prompt").value.trim() : f.prompt ?? "", seed: f.seed, depth: f.depth ?? 8, made: !!f.result, on: f.on !== false, keys: f.keys.map((k) => ({ frame: k.frame, strokes: packStrokes(k.strokes) })) } } : {}) };
  const name = (S.plate.name || "scene").replace(/[^\w.-]/g, "_").slice(0, 100), r = await post(`/paintaplate/scenes/${encodeURIComponent(name)}`, scene);
  if (!r.ok) throw new Error(`The scene was not saved: ${await r.text()}`);
  status(`Scene ${name} saved on this ComfyUI: Open plate > Scenes opens it again, or downloads it.`);
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
    plate: { path: p.path, cs: p.cs, frames: p.frames, fps: p.fps, work: p.work, prev: p.prev, track: p.track, trackErase: p.trackErase },
    render: { prompt: shotPrompt(active.map((e) => ({ tool: e.tool, words: e.prompt }))), seed: active[0].seed,
      erasePrompt: erasePrompt(active.filter((e) => e.tool === "erase").map((e) => e.caption?.text)),
      grow: grow(p.spec.width, erase), feather: feather(p.spec.width), prefix: `paintaplate/${p.id}/graph`,
      hdr: S.hdrReady && wantsHdr(p.spec, active.map((e) => e.tool), S.toHdr) } });
  const a = Object.assign(document.createElement("a"), { download: `${p.name}.comfyui.json`,
    href: URL.createObjectURL(new Blob([JSON.stringify(graph, null, 1)], { type: "application/json" })) });
  document.body.append(a); a.click(); a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
  status(`Saved ${a.download}: ${Object.keys(graph).length} nodes. Drop it on this ComfyUI to open it: it reads the plate and the strokes from the input folder.`);
}

async function openScene(text) { // the plate opens in its colour space, then every edit runs again with its own seed and words
  const scene = JSON.parse(text), o = scene.ocio;
  if (scene.format !== SCENE.format || !(scene.version <= SCENE.version)) throw new Error("This file is not a PaintAPlate scene.");
  if (o) { // its OCIO config and view, where this ComfyUI has them
    if (o.config && o.config !== S.ocio.config) await loadOcio(o.config).catch((err) => log(`${err.message}: the scene opens in the config in use`, "error"));
    const info = S.ocio.info;
    if (info.displays.some((d) => d.name === o.display && d.views.includes(o.view))) Object.assign(S.ocio, { display: o.display, view: o.view });
    S.ocio.look = info.looks.includes(o.look) ? o.look : "";
    look.setView(S.ocio); saveOcio();
  }
  if (scene.preview) setPreview(scene.preview);
  S.toHdr = scene.hdr !== false;
  const from = scene.version >= 2 && Array.isArray(scene.work) ? scene.work : null; // strokes in pixels of this working size
  await openPlate([], scene.plate.path, { cs: scene.version >= 3 ? scene.plate.color_space : undefined, // older scenes: read from the file
    ...(scene.fluid ? { fluid: { blankPath: scene.plate.path, seed: scene.fluid.seed, prompt: scene.fluid.prompt ?? "", on: scene.fluid.on !== false, depth: blankDepth(scene.fluid.depth) } } : {}) });
  if (scene.fluid) { // the fluid shot first: its keyframes, then the shot itself, the plate the edits were painted on
    S.fluid.keys = scene.fluid.keys.map((k) => { const key = newKey(k.frame); key.strokes = unpackStrokes(k.strokes, S.plate.work, from); redrawKey(key); return key; });
    fluidUI(); timelineUI(); historyUI(); render();
    if (scene.fluid.made && S.fluid.keys.length) await generateFluid(); // the machine that made it takes it back from the job index
    else if (!scene.edits.length) return status(`Scene opened: a fluid shot with ${S.fluid.keys.length} keyframe${S.fluid.keys.length === 1 ? "" : "s"}. Enter generates it.`);
  }
  for (const saved of scene.edits) {
    const e = Object.assign(newEdit(), { tool: saved.tool, color: saved.color, prompt: saved.prompt ?? "", seed: saved.seed,
      whole: !!saved.whole, on: saved.on !== false, state: "queued", launched: performance.now(), caption: saved.caption ? { key: "scene", text: saved.caption } : null,
      strokes: unpackStrokes(saved.strokes, S.plate.work, from) });
    redrawStrokes(e);
    e.thumb = strokesThumb(e);
    S.edits.push(e);
    if (e.on) queue(() => generate(e));
  }
  if (Number.isInteger(scene.in) && Number.isInteger(scene.out)) [S.inPt, S.outPt] = [scene.in, scene.out];
  queue(regenerateDependents);
  historyUI(); timelineUI();
  status(`Scene opened: ${scene.edits.length} edit${scene.edits.length === 1 ? "" : "s"} with their own seeds and captions. What this machine made for them comes back from the job index; the rest runs again.`);
}

function clearRange() { S.inPt = 0; S.outPt = S.plate.frames - 1; hud("In and out points cleared"); timelineUI(); }
function fullScreen() { if (document.fullscreenElement) document.exitFullscreen(); else document.documentElement.requestFullscreen(); }

// ---------- The viewer's colour, as in RV: OCIO, then exposure, contrast, gamma, saturation, hue, channels, invert ----------
// Display only, after OpenRV: each frame goes through one WebGL2 program before it is drawn (display.mjs), the strokes and
// marks after it: OCIO from the colour space its values are in to scene-linear, the colour tools there, then the look and
// the display and view. An image-sequence plate and its full-quality review are read in their own values (DeepFrames),
// so lower exposure brings back what lies above white in an EXR. The export itself never changes.
function wantDeep() { // an image sequence's own values around the playhead: the plate, and its review once it plays
  const p = S.plate;
  if (!p?.deep || !look.ready) return;
  fetchDeep(deep, p.path, p.name);
  if (S.shot?.frames) fetchDeep(deepShot, S.shot.frames, "the full-quality review");
}

function fetchDeep(cache, path, what) { // frames as RGB half floats from the frame route, ranked like the 8-bit cache
  const fresh = cache.fillDeep(async (first, count) => {
    const r = await fetch(`/paintaplate/frames?${new URLSearchParams({ path, first, count, side: DEEP_SIDE })}`);
    if (!r.ok) {
      log(`Full-precision frames stopped for ${what}: ${await r.text()}. The viewer plays the 8-bit movie.`);
      throw new Error("frames");
    }
    const [width, height] = r.headers.get("X-Frame-Size").split("x").map(Number);
    return { width, height, data: new Uint16Array(await r.arrayBuffer()) };
  }, path);
  if (fresh) log(`Full-precision frames: ${what} (${S.plate.cs}) at ${DEEP_SIDE} px on the long side, read in the background`);
}

function setDisplay(change) {
  Object.assign(S.display, change);
  const d = S.display, on = displayActive(d);
  $("#display-state").hidden = !on;
  $("#display-state").textContent = displayLabel(d);
  hud(S.mode ? `${PARAMS[S.mode].label} ${formatParam(S.mode, d[S.mode])}` : on ? displayLabel(d) : "Colour as shot", 1400);
  render();
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

// ---------- OCIO, as in RV: the plate's File Color Space, the look, the display and view, the config ----------

function saveOcio() { try { const { config, display, view, look: lk } = S.ocio; localStorage.setItem(OCIO_PREF, JSON.stringify({ config, display, view, look: lk })); } catch { /* this session only */ } }

async function loadOcio(name) { // the config's colour spaces, displays, views and looks; the view kept when the config has it
  const r = await fetch(`/paintaplate/ocio?${new URLSearchParams({ config: name ?? "" })}`), info = await r.json();
  if (!r.ok) throw new Error(info.error ?? `OCIO config ${name}`);
  const o = S.ocio, has = (d, v) => info.displays.some((x) => x.name === d && x.views.includes(v));
  Object.assign(o, { info, config: info.config });
  if (!has(o.display, o.view)) Object.assign(o, { display: info.display, view: info.view });
  if (o.look && !info.looks.includes(o.look)) o.look = "";
  look.setView(o); saveOcio();
  return info;
}

function setOcio(change) { // the display, the view or the look: the viewer only, at once, also while the shot plays
  Object.assign(S.ocio, change);
  look.setView(S.ocio); saveOcio();
  const v = `${S.ocio.display}: ${S.ocio.view}${S.ocio.look ? `, look ${S.ocio.look}` : ""}`;
  hud(v, 1800); log(`OCIO view: ${v}`); render();
}

async function setPlateSpace(cs) { // the plate's File Color Space, as RV calls it: the viewer at once, then the models and the export
  const p = S.plate;
  if (!p || p.cs === cs) return;
  log(`File Color Space: ${cs}, was ${p.cs}`);
  Object.assign(p, { cs, proxySpace: p.deep ? p.proxySpace : cs }); // a video plate's proxy holds its own values
  hud(`File Color Space: ${cs}`, 2000); render();
  const edits = S.edits.some((e) => e.on && e.state === "done");
  await openPlate([], p.path, { under: true, cs }); // the first frame in the model space again, and the edits made again on it
  if (edits) queue(regenerateDependents);
  status(`File Color Space ${cs}: the viewer shows it, and the first frame${edits ? " and the edits are" : " is"} made again in it. Switching back takes the earlier results from the job index.`);
}

async function setConfig(name) { // RV's Change Config: the viewer and the workflows use another OCIO config
  await loadOcio(name);
  log(`OCIO config: ${S.ocio.info.label}`);
  const p = S.plate;
  if (!p) return render();
  const st = knownSpace(p.cs) ? null : await fetch(`/paintaplate/stat?${new URLSearchParams({ path: p.path, config: S.ocio.config })}`).then((r) => r.json());
  const cs = st?.color_space ?? p.cs, edits = S.edits.some((e) => e.on && e.state === "done");
  await openPlate([], p.path, { under: true, cs });
  if (edits) queue(regenerateDependents);
}

function ocioItems() { // RV's OCIO menu (ocio_source_setup.py): the File Color Space tree by family, the look, the displays and views, the config
  const o = S.ocio, info = o.info, p = S.plate;
  const spaces = (node) => [...node.children.map((c) => [c.name, "", spaces(c)]),
    ...node.spaces.map((name) => [name, "", () => setPlateSpace(name).catch(quiet), !p, p?.cs === name])];
  return [["File Color Space", "", spaces(ocioTree(info.spaces)), !p],
    ["Look", "", [["None", "", () => setOcio({ look: "" }), false, !o.look], ...info.looks.map((lk) => [lk, "", () => setOcio({ look: lk }), false, o.look === lk])]],
    ["Displays", "", info.displays.map((d) => [d.name, "", d.views.map((v) => [v, "", () => setOcio({ display: d.name, view: v }), false, o.display === d.name && o.view === v])])],
    "-", ["Change Config", "", info.configs.map((c) => [c.label, "", () => setConfig(c.name).catch(quiet), false, c.name === info.config])]];
}

// ---------- The right-click menu, as RV's: every action of the page, with its key ----------

function menuItems() { // [group, [[label, key, action, disabled, checked] or "-", ...]]
  const p = !!S.plate, d = S.display, edits = S.edits.some((e) => e.on && e.patch);
  const chan = (c, key) => [CHANNEL_NAMES[c], key, () => setDisplay({ channel: c }), !p, d.channel === c];
  const param = (name, key) => [`${PARAMS[name].label}…`, key, () => colorMode(name), !p, S.mode === name];
  const step = (by) => () => { pause(); seek(S.frame + by); };
  const groups = [
    ["File", [["Open plate…", "", openDialog], ["Fluid keyframes", "", editFluid, !S.fluid || keying()],
      ["Save scene", "", () => saveScene().catch(quiet), !p], ["Export…", "", exportDialog, !edits],
      ["ComfyUI graph", "", () => saveGraph().catch(quiet), !edits]]],
    ["Edit", [["Undo", "Ctrl+Z", undo, !S.past.length], ["Redo", "Ctrl+Shift+Z", redo, !S.future.length], "-",
      ["New edit", "N", nextEdit, !p || keying() || (!S.draft && !S.selected)], ["Generate", "Enter", () => enter(false), $("#generate").disabled], ["Try another seed", "Ctrl+Enter", () => enter(true), !S.edits.length],
      ["SDR to HDR", "", () => setHdr(!S.toHdr), !p || !hdrPlate(p.spec) || !S.hdrReady, !!p && hdrPlate(p.spec) && S.hdrReady && S.toHdr],
      ["Stop generating", "Esc", stopGenerating, !generating()],
      ["Deselect", "Esc", () => select(null), !S.selected]]],
    ["Tools", [["Paint", "B", () => pickTool("paint"), !p, S.tool === "paint" && !S.rub], ["Erase", "E", () => pickTool("erase"), !p || (keying() && !S.fluid.result), S.tool === "erase" && !S.rub],
      ["Light", "L", () => pickTool("light"), !p || (keying() && !S.fluid.result), S.tool === "light" && !S.rub], ["Eraser", "X", () => setRub(!S.rub), !p, S.rub], ["Pick a colour", "I", () => picker(true), !p, !!S.picking], "-",
      ["Whole object", "", () => $("#whole").click(), !p, $("#whole").checked], ["Smaller brush", "-", () => setSize(S.size / 1.2), !p],
      ["Larger brush", "=", () => setSize(S.size * 1.2), !p]]],
    ["Control", [["Play or pause", "Space", () => (S.playing ? pause() : play()), !p, S.playing], ["Next frame", "Right", step(1), !p],
      ["Previous frame", "Left", step(-1), !p], "-", ["Go to the in point", "Home", () => { pause(); seek(S.inPt); }, !p],
      ["Go to the out point", "End", () => { pause(); seek(S.outPt); }, !p], ["Set the in point", "[", () => setIn(S.frame), !p],
      ["Set the out point", "]", () => setOut(S.frame), !p], ["Clear in and out", "\\", clearRange, !p]]],
    ["Colour", [param("exposure", "Shift+E"), param("contrast", "K"), param("gamma", "Y"), param("saturation", "Shift+S"), param("hue", "H"), "-",
      ["Invert", "Shift+I", () => setDisplay({ invert: !d.invert }), !p, d.invert], ["Reset all colour", "Shift+Home", resetDisplay, !displayActive(d)]]],
    ...(S.ocio.info ? [["OCIO", ocioItems()]] : []),
    ["View", [chan("rgb", "Shift+C"), chan("r", "Shift+R"), chan("g", "Shift+G"), chan("b", "Shift+B"), chan("l", "Shift+L"), "-",
      ["Fit", "F", () => zoomTo(1), !p], ["1:1", "1", () => zoomTo(S.plate.work[0] / S.fit.w), !p],
      ["Wipe", "F6", () => setWipe(S.wipe === null), !p, S.wipe !== null], ["Full screen", "`", fullScreen],
      ["Log", "", () => $("#log-btn").click(), false, !$("#log").hidden]]],
    ["Help", [["Keys", "?", () => $("#help").showModal()]]],
  ];
  const f = S.fluid;
  if (f && keying()) groups.splice(2, 0, ["Fluid", [["Generate", "Enter", () => generateFluid().catch(quiet), !f.keys.length],
    ["Another seed", "Ctrl+Enter", () => generateFluid(true).catch(quiet), !f.keys.length], "-",
    ["Copy keyframe", "Ctrl+C", copyKey, !keyHere()], ["Paste keyframe", "Ctrl+V", pasteKey, !S.clip], ["Delete keyframe", "Delete", () => deleteKey(), !keyHere()], "-",
    ["Previous keyframe", "Alt+Left", () => jumpKey(-1)], ["Next keyframe", "Alt+Right", () => jumpKey(1)]]]);
  return groups;
}

const SHEET = matchMedia("(max-width: 900px) and (orientation: portrait), (max-width: 600px), (max-height: 520px)"); // phones: the menu along the bottom

function menuList(items) { // a submenu: actions, separators, and nested submenus for items whose action is a list
  const sub = document.createElement("ul");
  sub.className = "sub";
  sub.setAttribute("role", "menu");
  for (const it of items) {
    const row = document.createElement("li");
    if (it === "-") { row.className = "sep"; sub.append(row); continue; }
    const [label, key, action, disabled = false, checked] = it;
    if (Array.isArray(action)) { sub.append(menuGroup(label, action, disabled)); continue; }
    const b = document.createElement("button");
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
  return sub;
}

function menuGroup(label, items, disabled = false) { // a row that opens its submenu on hover, or on a tap
  const li = document.createElement("li"), sub = menuList(items);
  li.className = disabled ? "group off" : "group";
  li.innerHTML = '<span></span><span class="arrow">▸</span>';
  li.firstChild.textContent = label;
  li.onmouseenter = () => { // a submenu that would leave the window opens on the left, or moves up
    sub.style.top = "";
    sub.classList.remove("left");
    const r = sub.getBoundingClientRect();
    if (r.right > innerWidth - 8) sub.classList.add("left");
    if (r.bottom > innerHeight - 8) sub.style.top = `${Math.round(innerHeight - 8 - r.bottom - 5)}px`;
  };
  li.append(sub);
  return li;
}

function openMenu(x, y) {
  const root = $("#ctx");
  root.replaceChildren(...menuItems().map(([group, items]) => menuGroup(group, items)));
  for (const g of root.querySelectorAll(".group")) g.onclick = (ev) => { // a tap opens a group: phones have no hover
    if (ev.target.closest("button") || ev.target.closest(".group") !== g) return;
    const open = !g.classList.contains("open");
    for (const o of g.parentElement.querySelectorAll(":scope > .group.open")) o.classList.remove("open");
    g.classList.toggle("open", open);
  };
  root.classList.toggle("sheet", SHEET.matches);
  root.hidden = false;
  if (SHEET.matches) { root.style.left = root.style.top = ""; return; }
  root.style.left = `${Math.max(8, Math.min(x, innerWidth - root.offsetWidth - 8))}px`;
  root.style.top = `${Math.max(8, Math.min(y, innerHeight - root.offsetHeight - 8))}px`;
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
  await loadOcio(S.ocio.config).catch((err) => { log(`${err.message}: the default OCIO config is used instead`, "error"); return loadOcio(""); });
  const needs = { PaintAPlate_LoadPlate: "this pack", PaintAPlate_ColorSpace: "this pack, restart ComfyUI after an update",
    PaintAPlate_FollowMatte: "this pack, restart ComfyUI after an update", PaintAPlate_LevelFill: "this pack, restart ComfyUI after an update",
    LTXAddVideoICLoRAGuide: "ComfyUI-LTXVideo",
    LTXVInpaintPreprocess: "ComfyUI-LTXVideo", SAM3_VideoTrack: "ComfyUI 0.42 or newer", ReferenceMultiLatent: "ComfyUI 0.41 or newer",
    TextGenerate: "ComfyUI 0.41 or newer" };
  const models = new Map(); // every model file the workflows load, by loader and input
  for (const wf of Object.values(WF)) for (const n of Object.values(wf.prompt))
    for (const [k, v] of Object.entries(n.inputs)) if (typeof v === "string" && v.endsWith(".safetensors")) models.set(v, [n.class_type, k]);
  const HDR_NODES = ["ImageColorSpace", "LTXVVAEForceFloat32", "LTXVLoadConditioning", "LTXVHDRDecodePostprocess"]; // SDR to HDR is optional
  const classes = [...new Set([...Object.keys(needs), ...[...models.values()].map(([cls]) => cls), "PaintAPlate_KeyframeVideo", ...HDR_NODES])];
  const info = Object.fromEntries(await Promise.all(classes.map(async (cls) => [cls, await objectInfo(cls)]))); // one round trip for all
  const missing = Object.entries(needs).filter(([cls]) => !info[cls]).map(([cls, from]) => `${cls} (${from})`);
  if (missing.length) return status(`Missing nodes: ${missing.join(", ")}. Install them, then reload this page.`);
  const absent = []; // only lists count: a file named in a text input is optional (the live preview's decoder)
  for (const [file, [cls, input]] of models) { const options = combo(info[cls]?.input.required[input]); if (options.length && !options.includes(file)) absent.push(file); }
  const fluidFiles = new Set(Object.values(WF.fluid.prompt).flatMap((n) => Object.values(n.inputs)).filter((v) => typeof v === "string" && v.endsWith(".safetensors")));
  const only = (file) => fluidFiles.has(file) && !Object.entries(WF).some(([name, wf]) => name !== "fluid" && JSON.stringify(wf.prompt).includes(file));
  S.fluidReady = !absent.some(only) && !!info.PaintAPlate_KeyframeVideo && !!info.LTXICLoRALoaderModelOnly; // fluid shots are optional
  if (!S.fluidReady) log(`Fluid shots are off: ${absent.filter(only).join(", ") || "update this pack and ComfyUI-LTXVideo"} (blank plates need ainvfx-fluid in models/loras).`);
  const hdrFiles = new Set(Object.values(WF.hdr.prompt).flatMap((n) => Object.values(n.inputs)).filter((v) => typeof v === "string" && v.endsWith(".safetensors")));
  const onlyHdr = (file) => hdrFiles.has(file) && !Object.entries(WF).some(([name, wf]) => name !== "hdr" && JSON.stringify(wf.prompt).includes(file));
  S.hdrReady = !absent.some(onlyHdr) && HDR_NODES.every((cls) => info[cls]);
  if (!S.hdrReady) log(`SDR to HDR is off: ${absent.filter(onlyHdr).join(", ") || "update ComfyUI and ComfyUI-LTXVideo"}. ${HDR_MISSING}`);
  const missingFiles = absent.filter((file) => !only(file) && !onlyHdr(file));
  if (missingFiles.length) return status(`Missing model files: ${missingFiles.join(", ")}. tools/pod_setup.sh lists each one with its models folder and downloads it.`);
  log(`Page ready in ${Math.round(performance.now() - t0)} ms: ${WORKFLOWS.length} workflows, ${classes.length} node classes and ${models.size} model files checked`);
  log(`OCIO: ${S.ocio.info.label}, viewed on ${S.ocio.display} through ${S.ocio.view}${S.ocio.config === "$OCIO" ? " ($OCIO)" : ""}`);
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
$("#pick").onclick = () => picker(!S.picking);

// The colour picker (I, or the pipette by the swatches): the next click on the frame takes the colour under it, as shot
// (before the viewer's colour tools), averaged over 5 x 5 pixels of the working size. The brush then paints with it; with
// Erase, which has no colour, the tool becomes Paint.
const PICK_SIDE = 5;
function picker(on) {
  S.picking = on && !!S.plate;
  view.classList.toggle("picking", S.picking);
  $("#pick").setAttribute("aria-pressed", String(S.picking));
  if (S.picking) hud("Pick a colour: click the frame. Esc cancels.", 4000);
  render();
}
function pickAt(e) {
  const [x, y] = frameAt(e), [W, H] = S.plate.work;
  const first = !S.playing && S.frame === 0 && (!S.shot?.url || stale() || editingFirst()); // as render() chooses
  const plate = S.frame === 0 ? S.hero : caches.get(plateVid).get(S.frame) || plateVid;
  const src = keying() || first || !S.shot?.url ? plate : shotFrame() || plate;
  const kx = (src.videoWidth || src.width) / W, ky = (src.videoHeight || src.height) / H, n = PICK_SIDE;
  const c = canvas([n, n]), d = c.getContext("2d", { willReadFrequently: true });
  d.drawImage(src, (x - n / 2) * kx, (y - n / 2) * ky, n * kx, n * ky, 0, 0, n, n);
  const color = pickedColor(d.getImageData(0, 0, n, n).data);
  picker(false);
  if (!color) return;
  if (S.tool === "erase") pickTool("paint");
  setColor(color);
  hud(`${S.tool === "light" ? "Light" : "Paint"} colour ${color}`, 2000);
}
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
  if (keying()) return staleFluid(); // new words for a fluid shot: the one on show used the old ones
  const cur = S.selected;
  if (!S.draft && cur) { mark(); if (busy(cur)) reopen(cur); else reopenDone(cur); }
  if (S.draft) prepareSoon(true); else generateUI();
};
$("#editing").onclick = () => select(null);
$("#new-edit").onclick = () => nextEdit();

for (const id of ["#b-width", "#b-height", "#b-fps", "#b-frames"]) $(id).oninput = blankNote;
$("#generate").onclick = () => enter(false);
$("#fluid-again").onclick = () => generateFluid(true).catch(quiet);
$("#display-state").onclick = () => resetDisplay();
$("#undo-btn").onclick = () => undo();
$("#redo-btn").onclick = () => redo();
$("#save-btn").onclick = () => S.plate && saveScene().catch(quiet);
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

$("#x-go").onclick = () => {
  const parts = ["export", ...["matte", "review", "shot"].filter((k) => $(`#x-${k}`).checked)];
  const r = S.renders.get(S.heroKey);
  if (r?.exported) return download(parts);
  S.wantDownload = parts;
  status("Writing the export in the plate's own format: the zip downloads when it is done.");
  exportUI(); stagesUI(); touch();
};
$("#log-btn").onclick = () => {
  const open = $("#log").hidden;
  $("#log").hidden = !open;
  $("#log-btn").setAttribute("aria-expanded", String(open));
  $("#log-btn").classList.remove("alert");
  $("#split-log").hidden = !open;
  layoutUI();
  if (open) $("#log").scrollTop = $("#log").scrollHeight;
};

// The layout: the side panel and the log resize from their dividers. The ResizeObserver on #viewport refits the frame.
const LAYOUT = saved(LAYOUT_PREF); // { side, log } in CSS px, as last dragged
function layoutUI() { // the sizes on the page, kept inside the window as it is now; returns them
  const view = { width: innerWidth, height: innerHeight }, open = !$("#log").hidden;
  const bar = $(".log").offsetHeight - (open ? $("#log").offsetHeight : 0);
  const around = { side: $(".tools").offsetWidth, log: $(".top").offsetHeight + bar };
  const size = (kind, first) => panelSize(kind, LAYOUT[kind] ?? first, view, { least: PANEL_LEAST[kind], stage: STAGE_LEAST[kind], around: around[kind] });
  const shown = { side: size("side", SIDE_W), log: size("log", LOG_H) };
  document.body.style.setProperty("--side-w", `${shown.side}px`);
  document.body.style.setProperty("--log-h", `${shown.log}px`);
  $("#split-side").setAttribute("aria-valuenow", shown.side);
  $("#split-log").setAttribute("aria-valuenow", shown.log);
  return shown;
}
function keepLayout(kind, value) { // value undefined: back to the first size
  if (value === undefined) delete LAYOUT[kind];
  else { LAYOUT[kind] = value; LAYOUT[kind] = layoutUI()[kind]; } // kept as shown: inside the window
  layoutUI();
  try { localStorage.setItem(LAYOUT_PREF, JSON.stringify(LAYOUT)); } catch { /* this session only */ }
}
function divider(el, kind) { // drag it, or the arrow keys once focused; a double-click gives the first size back
  const along = (e) => (kind === "side" ? e.clientX : e.clientY);
  const size = () => (kind === "side" ? $(".side").offsetWidth : $("#log").offsetHeight);
  el.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    e.preventDefault(); el.setPointerCapture(e.pointerId);
    const start = along(e), from = size();
    el.classList.add("dragging"); document.body.classList.add("resizing");
    const move = (m) => { LAYOUT[kind] = from - (along(m) - start); layoutUI(); }; // the panels sit right and below: toward them shrinks
    const end = () => {
      el.classList.remove("dragging"); document.body.classList.remove("resizing");
      for (const [t, f] of [["pointermove", move], ["pointerup", end], ["pointercancel", end]]) el.removeEventListener(t, f);
      keepLayout(kind, size());
    };
    for (const [t, f] of [["pointermove", move], ["pointerup", end], ["pointercancel", end]]) el.addEventListener(t, f);
  });
  el.addEventListener("dblclick", () => keepLayout(kind, undefined));
  el.addEventListener("keydown", (e) => { // left and up grow the panel; nothing reaches the page's own keys
    const sign = { ArrowLeft: 1, ArrowUp: 1, ArrowRight: -1, ArrowDown: -1 }[e.key];
    if (sign === undefined) return;
    e.preventDefault(); e.stopPropagation();
    keepLayout(kind, size() + sign * PANEL_STEP);
  });
}
divider($("#split-side"), "side");
divider($("#split-log"), "log");
layoutUI();
for (const b of $$("#open [role=tab]")) b.onclick = () => showTab(b.dataset.tab);
for (const b of $$("#open [data-root]")) b.onclick = () => browse(b.dataset.root).catch(quiet);
$("#browse-find").oninput = () => drawBrowse();
$("#browse-sort").onchange = () => { keepOpen(); drawBrowse(); };
$("#browse").onscroll = (e) => { const el = e.currentTarget; if (el.scrollTop + el.clientHeight > el.scrollHeight - 240 && OPEN.shown < browseList().length) drawBrowse(true); };
$("#path").oninput = () => { OPEN.chosen = null; for (const x of $$("#browse .item.on")) x.classList.remove("on"); openGoUI(); };
$("#files").onchange = filesUI;
$("#scene").onchange = () => { OPEN.scene = null; openGoUI(); };
$("#drop").ondragover = (e) => { e.preventDefault(); e.currentTarget.classList.add("over"); };
$("#drop").ondragleave = (e) => e.currentTarget.classList.remove("over");
$("#drop").ondrop = (e) => { e.preventDefault(); e.stopPropagation(); e.currentTarget.classList.remove("over"); $("#files").files = e.dataTransfer.files; filesUI(); };
$("#open-go").onclick = () => { // what the tab on show holds
  const t = OPEN.tab, typed = $("#path").value.trim(), it = OPEN.chosen, go = (job) => { $("#open").close(); job.catch(quiet); };
  if (t === "blank") return go(openBlank());
  if (t === "upload") return go(openPlate([...$("#files").files], ""));
  if (t === "scenes") return go(($("#scene").files[0]?.text() ?? fetch(`/paintaplate/scenes/${encodeURIComponent(OPEN.scene)}`).then((r) => r.text())).then(openScene));
  if (!typed && it?.kind === "scene") return go(fetch(sceneFile(it.path)).then((r) => r.text()).then(openScene));
  return go(openPlate([], typed || it.path));
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
  if (list.length) openPlate(list, "").catch(quiet);
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
  if (k === "Home" && e.shiftKey && !mod) { resetDisplay(); hud("Colour reset"); return e.preventDefault(); } // RV's Reset All Color
  if (S.mode && modeKey(k, combo)) return e.preventDefault();
  if (S.picking && k === "Escape") { picker(false); return e.preventDefault(); }
  if (!mod && !e.altKey && combo === "i") { if (!e.repeat) picker(!S.picking); return e.preventDefault(); } // the colour picker, as in Photoshop
  if (!mod && !e.altKey && COLOR_KEYS[combo]) { colorMode(COLOR_KEYS[combo]); return e.preventDefault(); }
  if (!mod && !e.altKey && CHANNEL_KEYS[combo]) { setDisplay({ channel: CHANNEL_KEYS[combo] }); return e.preventDefault(); }
  if (!mod && combo === "Shift+i") { setDisplay({ invert: !S.display.invert }); return e.preventDefault(); }
  if (keying() && mod && !e.shiftKey && (low === "c" || low === "v") && !getSelection().toString()) { if (low === "c") copyKey(); else pasteKey(); return e.preventDefault(); }
  if (keying() && !mod && (k === "Delete" || k === "Backspace")) { deleteKey(); return e.preventDefault(); }
  if (keying() && e.altKey && (k === "ArrowLeft" || k === "ArrowRight")) { jumpKey(k === "ArrowLeft" ? -1 : 1); return e.preventDefault(); }
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
  else if (k === "Escape") escape();
  else if (low === "z" && mod) e.shiftKey ? redo() : undo();
  else if (low === "y" && mod) redo();
  else if (low === "o" && !mod) { if (!S.compare) { S.compare = true; render(); hud("Plate"); } }
  else return;
  e.preventDefault();
});
addEventListener("keyup", (e) => { if (e.key.toLowerCase() === "o" && S.compare) { S.compare = false; render(); } });
function enter(another) { // Generate (Enter): the edit in progress, then its shot; nothing already made runs again. Ctrl+Enter: another seed
  const resumed = S.halted;
  S.halted = false; // a stop (Esc) lasts until Enter
  if (keying()) return void generateFluid(another).catch(quiet); // a fluid shot: generate it, Ctrl+Enter with another seed
  if (S.draft) return launch(S.draft);
  if (another) { const target = S.selected ?? S.edits.at(-1); if (target) again(target); return; }
  if (resumed || renderPending()) { // a stopped or failed render goes on
    const r = S.renders.get(S.heroKey); if (r) r.failed = null; touch(0); return hud(resumed ? "Generating again from where it stopped" : "The shot renders now", 2000);
  }
  hud(S.edits.length ? "Nothing changed since the last result. Ctrl+Enter tries another seed." : "Paint on the frame first, then Generate.", 3000);
}

function renderPending() { // the render of the edits on show failed, or never started: Generate starts it again
  const r = S.renders.get(S.heroKey);
  return !!S.plate && !keying() && !!S.heroKey && !S.running && !S.queued && (S.halted || (r ? !!r.failed : !S.piping));
}

function generateUI() { // the Generate button is live when Enter has something to start
  const b = $("#generate"), f = keying() ? S.fluid : null;
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
