// AInVFX PaintAPlate: one viewer to play a plate, paint edits on its first frame and watch the edited shot.
// The page runs on the ComfyUI server that serves it. Every step is a workflow from ./workflows, run by comfy.mjs;
// pure rules live in logic.mjs (tested in Node), canvas helpers in canvas.mjs, the frame cache in frames.mjs.

import { bounds, blob, canvas, loadImage, snap, whiteOf } from "./canvas.mjs";
import { WF, cancel, connect, loadWorkflows, objectInfo, onNotice, outputFile, outputText, run, upload, viewUrl } from "./comfy.mjs";
import { FrameCache } from "./frames.mjs";
import { caption, dark, dependsOnChange, fitSize, gb, secs } from "./logic.mjs";

const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];
const Q = new URLSearchParams(location.search);

// ---------- Tuning: every number that sets a size, a delay or a budget ----------
const WAIT = +Q.get("wait") || 2000; // ms after the last stroke before an edit starts
// FLUX 3 Image Klein: a quick pass at EDIT_SIDE, then a full-size pass that refines it with a light denoise
const QUICK = { steps: 8, denoise: 1, lightDenoise: 0.65, feather: 6, sigma: 3 };
const FULL = { steps: +Q.get("refine") || 8, denoise: 0.35, feather: 12, sigma: 6 };
const CACHE_MB = +Q.get("cache") || 384; // decoded frames kept per video: about 180 frames at 960 x 544
const WORK_SIDE = 1920, EDIT_SIDE = 768, TRACK_SIDE = 960; // long sides: full-size edits, quick edits, SAM tracking
const PREVIEW_SIDES = [960, 640, 448]; // the preview sizes offered: Standard, Fast, Draft
const EDIT_GROW = { erase: 24, paint: 48, light: 48 }; // an edit mask grows by the frame width over this
const HOLE_EDGE = 16; // the erased object filled before LTX: grown and softened by the width over this
const COMPOSITE_GROW = { erase: 24, other: 160 }, COMPOSITE_FEATHER = 96; // the composite's matte edge, same rule
const IDLE_MS = 1500; // quiet time after editing before a render starts
const WORKFLOWS = ["ingest", "edit", "snap", "shot", "matte", "comp", "export"];
const BACKGROUND = ["shot", "matte", "comp", "export"]; // job kinds a new stroke cancels

const TOOLS = { b: "paint", e: "erase", l: "light" };
const NAME = { paint: "Paint", erase: "Erase", light: "Light" };
const HINT = {
  paint: "Describe what to paint, then paint it on the frame. A fire, a wooden desk, a red umbrella",
  erase: "Optional: name what to remove, then paint over it. A red umbrella, a man in a coat",
  light: "Optional: describe the light, then paint where it comes from. Warm sunset, neon sign",
};

const S = {
  plate: null, original: null, hero: null,
  edits: [], draft: null, running: null, removed: [], ids: 0, count: 0, chain: Promise.resolve(), queued: 0,
  tool: "paint", size: 48, colors: { paint: "#000000", light: "#ffd890" }, rub: false,
  get color() { return this.colors[this.tool] ?? "#000000"; },
  frame: 0, playing: false, inPt: 0, outPt: 0, wipe: null, compare: false,
  fit: { w: 0, h: 0, x: 0, y: 0 }, zoom: { k: 1, x: 0, y: 0 },
  shot: null, shotDirty: false, stage: null, run: 0, exported: null, wantDownload: null,
  background: (() => { try { return localStorage.getItem("paintaplate.background") !== "0"; } catch { return true; } })(), // prepare the export after each change
  previewCap: (() => { try { return +localStorage.getItem("paintaplate.preview") || PREVIEW_SIDES[0]; } catch { return PREVIEW_SIDES[0]; } })(), // long side of the shot preview
  heroKey: "", renders: new Map(), // set of edits -> what has been rendered for it
  uploads: new Map(), timer: 0,
};

const view = $("#view"), ctx = view.getContext("2d");
const plateVid = $("#plate-video"), shotVid = $("#shot-video");
const fx = document.createElement("canvas"); // scratch layer for masked overlays

const quiet = (e) => { if (e?.message === "cancelled") return; console.error(e); status(e?.message ?? String(e)); };
const uploadCanvas = async (c, name) => upload(await blob(c), name, `paintaplate/${S.plate.id}`);

// ---------- What Klein sees ----------

function editImage(e, before, size) { // what Klein sees: the strokes over the frame; for an erase, the frame itself
  const c = snap(before, size);
  if (e.tool === "erase") return c; // told to remove the object, Klein cleans it; shown a filled hole, it drew a new object there
  c.getContext("2d").drawImage(e.paint, 0, 0, size[0], size[1]);
  return c;
}

const maskAt = (e, size) => (e.tool === "light" ? snap(null, size, "#fff") : snap(e.mask, size, "#000"));

function captionOf(e) { // the instruction and layout table for an edit
  const colors = e.strokes.filter((s) => s.tool !== "rub").map((s) => s.color); // eraser strokes have no colour
  return caption({ tool: e.tool, words: e.prompt, colors, color: e.color, bbox: bounds(e.mask) });
}

// ---------- Plate ----------

async function openPlate(list, typed, cs) {
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
    work: fitSize(w, h, WORK_SIDE, 32), prev: fitSize(w, h, EDIT_SIDE, 16), shot: fitSize(w, h, S.previewCap, 32),
    track: fitSize(w, h, TRACK_SIDE, 32) }; // SAM tracks at one size whatever the preview size: the export's mattes use it
  if (Q.get("shot") === "full") S.plate.shot = S.plate.work;
  S.original = snap(await loadImage(viewUrl(outputFile("ingest", out, "hero"))), S.plate.work);
  Object.assign(S, { hero: S.original, edits: [], draft: null, running: null, removed: [], count: 0,
    frame: 0, inPt: 0, outPt: S.plate.frames - 1, shot: null, shotDirty: false, exported: null, wantDownload: null,
    stage: { phase: "none" }, zoom: { k: 1, x: 0, y: 0 }, wipe: null, heroKey: "" });
  S.uploads.clear(); S.renders.clear();
  [view.width, view.height] = S.plate.work;
  view.classList.add("painting");
  plateVid.src = viewUrl(outputFile("ingest", out, "proxy"));
  plateVid.addEventListener("canplaythrough", () => { if (OPENING.at === "load") { OPENING.at = "done"; status("Ready to play. Describe the edit at the top, then paint on the frame."); } }, { once: true });
  shotVid.removeAttribute("src"); shotVid.load();
  for (const b of ["#play-btn", "#wipe-btn"]) $(b).disabled = false;
  const kind = spec.kind === "video" ? spec.codec : `${spec.ext.slice(1).toUpperCase()} ${spec.kind}`;
  $("#spec").textContent = `${S.plate.name}: ${kind}, ${w} × ${h}, ${Math.round(S.plate.fps * 1000) / 1000} fps, ${spec.frames} frames, ${cs}`;
  document.activeElement?.blur();
  S.took = {};
  fitView(); historyUI(); timelineUI(); stagesUI(); exportUI(); render();
  warm();
  const offered = [...$("#cs").options].some((o) => o.value === spec.color_space_guess);
  const gaps = spec.missing?.length ? ` ${spec.missing.length} frame${spec.missing.length > 1 ? "s are" : " is"} missing (${spec.missing.slice(0, 4).map((n) => n).join(", ")}${spec.missing.length > 4 ? "…" : ""}): the frame before holds, as in RV.` : "";
  if (gaps) setTimeout(() => status(gaps.trim()), 50);
  status(spec.color_space_guess === cs ? "Describe the edit at the top, then paint on the frame."
    : offered ? `The file suggests ${spec.color_space_guess}. Reopen with it if colours look wrong.`
    : `The file suggests ${spec.color_space_guess}, which this ComfyUI does not offer yet: update ComfyUI past v0.42.5.`);
}

function stopEverything() {
  pause();
  clearTimeout(S.timer); clearTimeout(idleTimer);
  for (const e of S.edits) e.token = (e.token ?? 0) + 1;
  cancel("edit", "snap", "warm", ...BACKGROUND);
}

async function warm() { // load the image model while the user looks at the frame, so the first edit is quick
  const size = S.plate.prev, base = await uploadCanvas(snap(S.original, size), "warm.png");
  const mask = await uploadCanvas(snap(null, size, "#000"), "warm_mask.png");
  run("edit", { base, reference: base, start: base, mask, caption: "warm up", seed: 0, steps: 1, denoise: 1,
    grow: 0, feather: 1, sigma: 1 }, { kind: "warm" }).done.catch(() => {});
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
    const cache = caches.get(shotReady() ? shotVid : plateVid);
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

function setIn(f) { S.inPt = Math.min(f, S.outPt); hud(`In point: frame ${S.plate.first + S.inPt}`); timelineUI(); }
function setOut(f) { S.outPt = Math.max(f, S.inPt); hud(`Out point: frame ${S.plate.first + S.outPt}`); timelineUI(); }

// ---------- The picture ----------

function fitView() { // the frame fills the viewport with the plate's own aspect; zoom and pan sit on top
  if (!S.plate) return;
  const box = $("#viewport").getBoundingClientRect(), aspect = S.plate.spec.width / S.plate.spec.height;
  let w = box.width - 24, h = w / aspect;
  if (h > box.height - 24) { h = box.height - 24; w = h * aspect; }
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

function layered(upto = S.edits.length) { // the first frame with the active edits before index `upto`
  const c = snap(S.original, S.plate.work), x = c.getContext("2d");
  for (const e of S.edits.slice(0, upto)) if (e.on && e.patch && e.state !== "generating") x.drawImage(e.patch, 0, 0, c.width, c.height);
  return c;
}

function recompose() {
  S.hero = layered();
  const key = S.edits.filter((e) => e.on && e.patch && e.state !== "generating").map((e) => `${e.id}.${e.version}`).join(",");
  if (key === S.heroKey) return;
  S.heroKey = key;
  const r = S.renders.get(key); // a set of edits seen before plays at once (a bypass turned back on, for example)
  S.exported = r?.exported ?? null;
  if (r?.comp) setShot(r.comp, key);
  else if (!key) setShot(null, key);
  S.shotDirty = !!key && !r?.exported;
  stagesUI(); exportUI();
}

function setShot(src, key) {
  S.shot = src ? { url: src, key } : null;
  if (src) { if (shotVid.getAttribute("src") !== src) shotVid.src = src; }
  else { shotVid.removeAttribute("src"); shotVid.load(); }
  render(); timelineUI();
}

function render() {
  if (!S.plate || !S.hero) return;
  const W = view.width, H = view.height;
  const first = S.frame === 0 && !S.playing;
  const edited = first ? S.hero : shotReady() ? shotVid : plateVid;
  const plate = first ? S.original : plateVid;
  const draw = (src) => {
    const cached = src instanceof HTMLVideoElement && !S.playing && caches.get(src).get(S.frame);
    if (cached) ctx.drawImage(cached, 0, 0, W, H);
    else if (!(src instanceof HTMLVideoElement) || src.readyState >= 2) ctx.drawImage(src, 0, 0, W, H);
  };
  ctx.globalAlpha = 1;
  if (S.compare) draw(plate);
  else if (S.wipe !== null) {
    draw(plate);
    ctx.save(); ctx.beginPath(); ctx.rect(S.wipe * W, 0, W - S.wipe * W, H); ctx.clip();
    draw(edited); if (first) overlays(W, H);
    ctx.restore();
  } else { draw(edited); if (first) overlays(W, H); }
  drawCursor();
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
  if (S.hover && S.hover !== e && S.hover.tool !== "light" && S.hover.strokes.length) strokes(S.hover, 0.55); // History: which edit is which
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
  if (!S.cursor || stroke || S.playing) return;
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

$("#wipe .grip").addEventListener("pointerdown", (e) => {
  e.preventDefault();
  const grip = e.currentTarget;
  grip.setPointerCapture(e.pointerId);
  const move = (ev) => {
    const r = view.getBoundingClientRect();
    S.wipe = Math.max(0, Math.min(1, (ev.clientX - r.left) / r.width));
    placeWipe(); render();
  };
  grip.addEventListener("pointermove", move);
  grip.addEventListener("pointerup", () => grip.removeEventListener("pointermove", move), { once: true });
});

let hudTimer;
function hud(text, ms = 1600) {
  const el = $("#hud");
  el.textContent = text;
  el.classList.add("on");
  clearTimeout(hudTimer);
  hudTimer = setTimeout(() => el.classList.remove("on"), ms);
}

// ---------- Painting: the edit starts by itself when the strokes stop ----------

let stroke = null, nav = null;

view.addEventListener("pointerdown", (e) => {
  if (!S.plate) return;
  if (e.button === 1 || (e.button === 0 && (e.altKey || e.ctrlKey || e.metaKey))) return navigate(e);
  const rub = S.rub || (e.pointerType === "pen" && (e.buttons & 32)); // the eraser tool, or a pen's eraser end
  if (e.button !== 0 && !rub) return;
  if (S.playing) pause();
  if (S.frame !== 0) { seek(0); hud("Edits are painted on the first frame"); }
  if (rub) return rubOut(e);
  cancel(...BACKGROUND); // the GPU goes to the edit
  clearTimeout(S.timer);
  let d = S.draft;
  if (!d && S.running && S.running === S.last && S.running.tool === S.tool && S.running === S.edits.at(-1)) d = reopen(S.running);
  if (d && d.tool !== S.tool) { launch(d); d = null; }
  if (!d) d = S.draft = newEdit();
  view.setPointerCapture(e.pointerId);
  stroke = { tool: d.tool, color: S.color, size: S.size, points: [] };
  d.strokes.push(stroke);
  addPoint(d, e);
});

view.addEventListener("pointermove", (e) => {
  if (nav) return navigateMove(e);
  if (stroke && S.draft) return addPoint(S.draft, e);
  S.cursor = frameAt(e);
  if (!S.playing) requestAnimationFrame(render);
});
view.addEventListener("pointerleave", () => { S.cursor = null; if (!S.playing) requestAnimationFrame(render); });
view.addEventListener("pointerup", () => {
  if (nav) { nav = null; view.classList.remove("panning"); return; }
  if (!stroke) return;
  stroke = null;
  if (S.draft && !painted(S.draft)) return discard(); // everything was rubbed out
  schedule();
});

function rubOut(e) { // the eraser works on the strokes in progress, or on the edit just made
  let d = S.draft;
  if (!d && S.last && S.last === S.edits.at(-1) && S.last.strokes.length) d = S.running === S.last ? reopen(S.last) : reopenDone(S.last);
  if (!d) return hud("Nothing to rub out: the eraser takes away strokes you just painted");
  cancel(...BACKGROUND);
  clearTimeout(S.timer);
  view.setPointerCapture(e.pointerId);
  stroke = { tool: "rub", size: S.size, points: [] };
  d.strokes.push(stroke);
  addPoint(d, e);
}

function reopenDone(edit) { // the eraser on a finished edit: it becomes strokes again, and runs again 2 s later
  edit.kept = edit.strokes.length;
  edit.state = "drawing";
  historyUI();
  return (S.draft = edit);
}

function schedule() { // run the draft once the strokes have stopped for WAIT ms
  clearTimeout(S.timer);
  if (!S.draft) return;
  S.timer = setTimeout(() => S.draft && launch(S.draft), WAIT);
  hud(`The edit starts in ${Math.round(WAIT / 1000)} s. Enter starts it now, Esc cancels.`, WAIT);
}

function newEdit() {
  return { id: ++S.ids, n: 0, tool: S.tool, color: S.color, prompt: "", seed: (Math.random() * 2 ** 31) | 0,
    strokes: [], on: true, state: "drawing", version: 0, basis: [],
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

// ---------- Edits: generate, keep, bypass, remove ----------

function queue(fn) {
  S.queued++;
  S.chain = S.chain.then(fn).catch(quiet).finally(() => { S.queued--; touch(); });
}

function launch(edit) {
  if (S.draft === edit) S.draft = null;
  clearTimeout(S.timer);
  if (!edit.strokes.length) return;
  edit.prompt = $("#prompt").value.trim();
  if (edit.tool === "erase") edit.whole = $("#whole").checked;
  if (!S.edits.includes(edit)) { edit.n = ++S.count; S.edits.push(edit); }
  edit.state = "queued";
  edit.launched = performance.now();
  S.last = edit; // the edit the next strokes may still join
  edit.thumb ??= strokesThumb(edit);
  S.removed = [];
  historyUI(); render();
  queue(() => generate(edit));
}

function reopen(edit) { // more strokes on the edit being generated: stop it and keep drawing
  edit.token = (edit.token ?? 0) + 1;
  cancel("edit", "snap");
  edit.state = "drawing"; edit.preview = edit.latent = null;
  edit.kept = edit.strokes.length;
  S.running = null;
  historyUI();
  return (S.draft = edit);
}

function activeBefore(edit) {
  return S.edits.slice(0, S.edits.indexOf(edit)).filter((e) => e.on && e.patch);
}

async function baseUpload(edit, before, size) { // the frame under an edit, uploaded once per set of edits below it
  const key = `${activeBefore(edit).map((e) => `${e.id}.${e.version}`).join(",") || "plate"}@${size}`;
  if (!S.uploads.has(key)) S.uploads.set(key, uploadCanvas(snap(before, size), `base_${S.uploads.size}.png`));
  return S.uploads.get(key);
}

async function generate(edit) {
  if (!S.edits.includes(edit) || !edit.on) return;
  const token = (edit.token = (edit.token ?? 0) + 1);
  const alive = () => edit.token === token && S.edits.includes(edit) && edit.on;
  const p = S.plate, light = edit.tool === "light", tag = `e${edit.id}_${token}`;
  S.running = edit;
  Object.assign(edit, { state: "generating", preview: null, latent: null, shown: null });
  recompose(); historyUI(); render();
  try {
    const before = layered(S.edits.indexOf(edit));
    if (edit.tool === "erase" && edit.whole && edit.snapped !== painted(edit)) {
      edit.snapped = painted(edit);
      edit.sam = null; redrawStrokes(edit);
      await snapErase(edit, before);
      if (!alive()) return;
    }
    const show = (b) => alive() && createImageBitmap(b).then((bm) => {
      if (!alive() || edit.preview) return;
      edit.latent = bm;
      edit.shown ??= performance.now();
      render();
    });
    // 1. A quick pass at preview size: its steps appear live inside the strokes.
    status(`Edit ${edit.n}: ${NAME[edit.tool].toLowerCase()}, first look`);
    const size = p.prev, base = await baseUpload(edit, before, size);
    const reference = await uploadCanvas(editImage(edit, before, size), `${tag}_ref.png`);
    const values = { base, reference, start: light ? base : reference, caption: captionOf(edit), steps: QUICK.steps, seed: edit.seed,
      mask: await uploadCanvas(maskAt(edit, size), `${tag}_mask.png`), denoise: light ? QUICK.lightDenoise : QUICK.denoise,
      grow: Math.round(size[0] / reach(edit)), feather: QUICK.feather, sigma: QUICK.sigma };
    const quick = await run("edit", values, { kind: "edit", front: true, preview: show, progress: (f) => editProgress(edit, f / 2) }).done;
    if (!alive()) return;
    edit.preview = await loadImage(viewUrl(outputFile("edit", quick, "patch")));
    edit.shown ??= performance.now();
    edit.latent = null; render();
    // 2. The same seed at full size, starting from the quick pass: it resolves in place.
    status(`Edit ${edit.n}: ${NAME[edit.tool].toLowerCase()}, full size`);
    const work = p.work, start = snap(before, work);
    start.getContext("2d").drawImage(edit.preview, 0, 0, work[0], work[1]);
    const startName = await uploadCanvas(start, `${tag}_start.png`);
    const full = await run("edit", { ...values, base: await baseUpload(edit, before, work), start: startName,
      // an erase refines the quick result, which has no object left: shown the original, Klein drew part of it back
      reference: edit.tool === "erase" ? startName : await uploadCanvas(editImage(edit, before, work), `${tag}_ref_full.png`),
      mask: await uploadCanvas(maskAt(edit, work), `${tag}_mask_full.png`), steps: FULL.steps, denoise: FULL.denoise,
      grow: Math.round(work[0] / reach(edit)), feather: FULL.feather, sigma: FULL.sigma }, { kind: "edit", front: true,
      progress: (f) => editProgress(edit, 0.5 + f / 2) }).done;
    if (!alive()) return;
    edit.patch = await loadImage(viewUrl(outputFile("edit", full, "patch")));
    Object.assign(edit, { preview: null, latent: null, state: "done", version: edit.version + 1, force: false, kept: undefined });
    edit.foot = footprint(edit);
    edit.basis = activeBefore(edit).map(record);
    S.running = null;
    recompose();
    edit.thumb = thumbOf(edit);
    historyUI(); render(); timelineUI();
    status(`Edit ${edit.n} is on the first frame. The shot renders when you stop editing.`);
  } catch (err) {
    if (edit.token === token) {
      Object.assign(edit, { state: edit.patch ? "done" : "failed", preview: null, latent: null });
      S.running = null; recompose(); historyUI(); render();
    }
    if (err?.message !== "cancelled") throw err;
  }
}

const reach = (e) => EDIT_GROW[e.tool];

async function snapErase(edit, before) { // SAM 3.1 grows the erase strokes to the whole object under them
  const size = S.plate.prev, k = size[0] / S.plate.work[0];
  const pts = edit.strokes.flatMap((s) => s.points);
  const picks = [...new Set([0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * (pts.length - 1))))]; // up to five points
  const points = picks.map((i) => ({ x: Math.round(pts[i][0] * k), y: Math.round(pts[i][1] * k) }));
  status("Finding the object under the stroke");
  const out = await run("snap", { image: await uploadCanvas(snap(before, size), `e${edit.id}_snap.png`), points: JSON.stringify(points) },
    { kind: "snap", front: true }).done;
  const pixels = (c) => c.getContext("2d").getImageData(0, 0, size[0], size[1]).data;
  const sam = snap(await loadImage(viewUrl(outputFile("snap", out, "mask"))), size), s = pixels(sam), m = pixels(maskAt(edit, size));
  let area = 0, painted = 0, both = 0;
  for (let i = 0; i < s.length; i += 4) {
    if (m[i] > 127) painted++;
    if (s[i] > 127) { area++; if (m[i] > 127) both++; }
  }
  // one object that holds the stroke: not a whole wall or shopfront grown from a small stroke
  if (!area || area > 0.12 * size[0] * size[1] || area > 40 * painted || both < 0.5 * painted)
    return status("Erasing only what you painted: no single object under the stroke.");
  const d = sam.getContext("2d"), img = d.getImageData(0, 0, size[0], size[1]);
  for (let i = 0; i < img.data.length; i += 4) { img.data[i + 3] = img.data[i]; img.data[i] = img.data[i + 1] = img.data[i + 2] = 255; }
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
  S.last = null;
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
  edit.on = !edit.on;
  if (!edit.on && S.running === edit) stopEdit(edit);
  status(edit.on ? `Edit ${edit.n} is back on.` : `Edit ${edit.n} is bypassed.`);
  rebuild();
}

function removeEdit(edit) {
  const i = S.edits.indexOf(edit);
  if (i < 0) return;
  if (S.running === edit) stopEdit(edit);
  if (S.draft === edit) S.draft = null;
  S.edits.splice(i, 1);
  if (edit.patch) S.removed.push({ edit, i });
  status(`Edit ${edit.n} removed.${edit.patch ? " Ctrl+Shift+Z brings it back." : ""}`);
  rebuild();
}

function again(edit) { // a new seed for one edit; the edits above it follow if they depend on it
  if (!edit.strokes.length || edit.state === "drawing") return;
  Object.assign(edit, { seed: (Math.random() * 2 ** 31) | 0, on: true, force: true, launched: 0 });
  status(`Edit ${edit.n}: another try.`);
  rebuild();
}

function stopEdit(edit) {
  edit.token = (edit.token ?? 0) + 1;
  cancel("edit", "snap");
  if (S.running === edit) S.running = null;
}

function undo() {
  const d = S.draft;
  if (d) {
    const gone = d.strokes.pop();
    if (gone?.tool !== "rub") { d.sam = null; d.snapped = 0; }
    if (painted(d)) { redrawStrokes(d); render(); schedule(); }
    else discard();
    return;
  }
  const last = S.edits.at(-1);
  if (last) removeEdit(last);
}

function redo() {
  const r = S.removed.pop();
  if (!r) return status("Nothing to bring back.");
  S.edits.splice(Math.min(r.i, S.edits.length), 0, r.edit);
  status(`Edit ${r.edit.n} is back.`);
  rebuild();
}

function discard() { // Esc: drop the strokes in progress, or stop the edit being generated
  clearTimeout(S.timer);
  const d = S.draft ?? S.running;
  if (!d) return;
  stopEdit(d);
  if (S.draft === d) S.draft = null;
  if (d.patch) { // it had a result: go back to it
    if (d.kept !== undefined) { d.strokes.length = d.kept; redrawStrokes(d); d.snapped = painted(d); }
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
  const list = $("#history");
  $("#history-empty").hidden = S.edits.length > 0;
  list.replaceChildren(...[...S.edits].reverse().map((e) => {
    const li = document.createElement("li");
    li.dataset.id = e.id;
    li.className = [e.on ? "" : "off", e.state === "generating" || e.state === "queued" || e.state === "drawing" ? "busy" : "",
      e.state === "failed" ? "failed" : ""].join(" ").trim();
    li.innerHTML = `<img class="thumb" alt=""><div class="what"><span class="title"></span><small></small></div>
      <div class="acts"><button class="eye" aria-pressed="${e.on}" title="${e.on ? "Bypass this edit" : "Turn this edit back on"}">${e.on ? ICON.eye : ICON.off}</button>
      <button class="again" title="Try another">${ICON.again}</button><button class="del" title="Remove this edit">${ICON.del}</button></div>`;
    const img = li.querySelector(".thumb");
    if (e.thumb) img.src = e.thumb; else img.removeAttribute("src");
    li.querySelector(".title").textContent = `${e.n || "New"}. ${NAME[e.tool]}`;
    const what = e.tool === "erase" ? (e.whole ? "Whole object" : "Painted area") : e.prompt || (e.tool === "light" ? "From the strokes" : "No words");
    const small = li.querySelector("small");
    if (STATE[e.state] && e.on) {
      small.innerHTML = '<span class="state"></span>';
      small.firstChild.textContent = STATE[e.state];
    } else small.textContent = e.on ? what : `Bypassed: ${what}`;
    small.title = what;
    li.querySelector(".eye").onclick = () => toggle(e);
    li.querySelector(".again").onclick = () => again(e);
    li.querySelector(".del").onclick = () => removeEdit(e);
    li.querySelector(".again").disabled = e.state === "drawing" || !e.strokes.length;
    li.onmouseenter = () => { S.hover = e; render(); };
    li.onmouseleave = () => { S.hover = null; render(); };
    li.onclick = (ev) => { if (!ev.target.closest("button")) { pause(); seek(0); } };
    return li;
  }));
  exportUI(); timelineUI();
}

function editProgress(edit, f) { // the state line of one History row, without rebuilding the list
  const el = $(`#history li[data-id="${edit.id}"] .state`);
  if (el) el.textContent = `Generating ${Math.round(f * 100)}%`;
}

// ---------- In idle time: the shot, its mattes, the composite to play, then the export ----------

let idleTimer;
function touch() { clearTimeout(idleTimer); idleTimer = setTimeout(idle, IDLE_MS); }

function idle() { // one pipeline at a time: a running one goes on, unless the set of edits changed under it
  if (!S.plate) return;
  if (S.draft || S.running || S.queued || stroke) return touch();
  if (S.piping) { if (S.shotDirty && S.piping !== S.heroKey) cancel(...BACKGROUND); return; }
  const r = S.renders.get(S.heroKey);
  if (!S.shotDirty && !((S.background || S.wantDownload) && S.heroKey && !r?.exported)) return;
  S.piping = S.heroKey || "-";
  pipeline().catch((e) => {
    if (e?.message === "cancelled") S.shotDirty = true;
    else { quiet(e); S.stage = null; S.wantDownload = null; stagesUI(); exportUI(); }
  }).finally(() => { S.piping = null; touch(); });
}

const grow = (w, erase) => Math.max(4, Math.round(w / (erase ? COMPOSITE_GROW.erase : COMPOSITE_GROW.other))); // pixels at width w
const feather = (w) => Math.max(6, Math.round(w / COMPOSITE_FEATHER));

// Every step of a render, in order. `final` steps make the export; they run after the preview when the export is
// prepared in the background, or when Export asks for them.
const STAGES = [
  { id: "erase", label: "Track the erase", ref: 6 }, { id: "shot", label: "Shot", ref: 20 }, { id: "track", label: "Track the paint", ref: 5 },
  { id: "comp", label: "Composite", ref: 14 },
  { id: "full", label: "Shot at full size", ref: 45, final: true }, { id: "trackfull", label: "Track at full size", ref: 5, final: true },
  { id: "export", label: "Export", ref: 18, final: true },
];
S.took = {}; // measured seconds per step, for this plate: the next estimates use them

function plan(r, active) { // the steps this set of edits needs: no tracking for a relight alone, no second pass when the preview is full size
  const p = S.plate, [sw, sh] = p.shot, onePass = sw === p.work[0] && sh === p.work[1];
  const erase = active.some((e) => e.tool === "erase"), paint = active.some((e) => e.tool === "paint");
  r.skip = new Set([!erase && "erase", !paint && "track", onePass && "full", (onePass || !paint) && "trackfull"].filter(Boolean));
  return r;
}

function estimate(id) { // seconds: what this step took last time, or a measured reference scaled to this plate
  if (S.took[id]) return S.took[id];
  const p = S.plate, ref = 928 * 512 * 97;
  const size = ["full", "export"].includes(id) ? p.work : ["erase", "track", "trackfull"].includes(id) ? p.track : p.shot;
  const scale = (size[0] * size[1] * p.frames) / ref * (["full", "export"].includes(id) ? 0.73 : 1);
  return STAGES.find((x) => x.id === id).ref * Math.max(0.25, scale);
}

async function step(r, id, work) { // run one step of a render, timed and shown
  if (r.done?.[id] !== undefined || r.skip?.has(id)) return;
  const t0 = performance.now();
  S.stage = { key: S.heroKey, id, progress: 0, t0 };
  stagesUI();
  await work((f) => { if (S.stage?.id === id) { S.stage.progress = f; stagesUI(); } });
  const dt = (performance.now() - t0) / 1000;
  (r.done ??= {})[id] = dt;
  S.took[id] = dt;
  S.stage = null;
  stagesUI();
}

async function pipeline() {
  S.shotDirty = false;
  cancel(...BACKGROUND);
  const p = S.plate, key = S.heroKey, active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
  if (!key || !active.length) return;
  const fresh = () => key === S.heroKey;
  let r = S.renders.get(key);
  if (!r) { r = { v: ++S.run }; r.base = `paintaplate/${p.id}/v${r.v}`; S.renders.set(key, r); }
  plan(r, active);
  const base = r.base, relight = active.some((e) => e.tool === "light"), [sw, sh] = p.shot;
  const erase = active.some((e) => e.tool === "erase");
  r.hero ??= await uploadCanvas(S.hero, `hero_v${r.v}.png`);
  const common = { path: p.path, color_space: p.cs, max_frames: p.frames, hero: r.hero, seed: active[0].seed };
  // the erase is tracked on the plate first: its matte also clears the erased objects from the frames LTX follows
  await step(r, "erase", async (progress) => { r.erased = await track(active, null, base, "", progress, null, ["erase"]); });
  // a large, soft hole: filled tight to the object, its outline above a man in the rain read as an umbrella to LTX
  const hole = r.erased?.found.matte_a ?? "", holed = (size) => ({ hole, hole_grow: Math.round(size[0] / HOLE_EDGE), hole_feather: Math.round(size[0] / HOLE_EDGE) });
  await step(r, "shot", async (progress) => {
    const out = await run("shot", { ...common, ...holed(p.shot), width: sw, height: sh, prefix: `${base}/shot/f`, video_prefix: `${base}/raw` },
      { kind: "shot", progress }).done;
    r.shot = `output:${base}/shot`;
    r.raw = viewUrl(outputFile("shot", out, "video"));
  });
  if (!fresh()) return;
  if (!r.comp && S.shot?.url !== r.raw) { // a rough look at once: the whole frame as the model made it, until the composite
    setShot(r.raw, key);
    hud("Rough preview: Space plays it. The composite follows.", 2500);
  }
  await step(r, "track", async (progress) => { r.painted = await track(active, r.shot, base, "", progress, null, ["paint"]); });
  r.mattes = mattesOf({ ...r.erased?.found, ...r.painted?.found });
  if (!fresh()) return;
  await step(r, "comp", async (progress) => {
    const comp = await run("comp", { path: p.path, color_space: p.cs, max_frames: p.frames, width: sw, height: sh, shot: r.shot,
      ...r.mattes.values, relight, grow: grow(sw, erase), feather: feather(sw), grain: 0, video_prefix: `${base}/comp` },
      { kind: "comp", progress }).done;
    r.comp = viewUrl(outputFile("comp", comp, "video"));
  });
  if (!fresh()) return;
  if (S.shot?.url !== r.comp) {
    setShot(r.comp, key);
    hud("The edited shot is ready: Space plays it", 2500);
    status(S.background ? "The edited shot is ready. The export is prepared next, at full quality."
      : "The edited shot is ready. Export renders it at full quality when you need it.");
  }
  if (!S.background && !S.wantDownload) return stagesUI();
  await step(r, "full", async (progress) => {
    await run("shot", { ...common, ...holed(p.work), width: p.work[0], height: p.work[1], prefix: `${base}/full/f`, video_prefix: `${base}/full` },
      { kind: "shot", progress }).done;
  });
  r.final = r.skip.has("full") ? r.shot : `output:${base}/full`;
  if (!fresh()) return;
  await step(r, "trackfull", async (progress) => { r.full = await track(active, r.final, base, "_full", progress, r.mattes, ["paint"]); });
  r.full ??= r.mattes;
  if (!fresh()) return;
  await step(r, "export", async (progress) => {
    const done = await run("export", { path: p.path, color_space: p.cs, max_frames: p.frames, shot: r.final, ...r.full.values, relight,
      keep_untouched: !relight, prefix: `${base}/export`, matte_prefix: `${base}/matte/matte`, grow: grow(p.spec.width, erase),
      feather: feather(p.spec.width) }, { kind: "export", progress }).done;
    r.exported = { run: base, name: `${p.name}_paintaplate_v${r.v}`, text: outputText("export", done, "export") ?? "" };
  });
  if (!fresh()) return;
  S.exported = r.exported;
  stagesUI(); exportUI();
  status(`Exported to the output folder: ${S.exported.text.split("\n")[0]}.`);
  if (S.wantDownload) { const parts = S.wantDownload; S.wantDownload = null; download(parts); }
}

async function track(active, shotPath, base, suffix, progress, previous, tools) { // SAM 3.1 follows a kind of edit through the shot
  const p = S.plate, [sw, sh] = p.track, found = { ...(previous?.found ?? {}) };
  for (const [key, tool, path, cs] of [["matte_a", "erase", p.path, p.cs], ["matte_b", "paint", shotPath, "sRGB"]]) {
    const edits = active.filter((e) => e.tool === tool);
    if (!edits.length || !tools.includes(tool)) continue; // the erase follows the plate; the paint follows the shot
    const union = canvas(p.track), u = union.getContext("2d");
    u.fillStyle = "#000"; u.fillRect(0, 0, sw, sh);
    u.globalCompositeOperation = "lighten";
    for (const e of edits) u.drawImage(tool === "paint" ? whiteOf(e.patch) : e.mask, 0, 0, sw, sh);
    await run("matte", { path, color_space: cs, max_frames: p.frames, width: sw, height: sh, prefix: `${base}/${key}${suffix}/m`,
      mask: await uploadCanvas(union, `${key}${suffix}_${S.run}.png`) }, { kind: "matte", progress }).done;
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

function status(text) {
  $("#status").textContent = text;
  const li = document.createElement("li");
  li.innerHTML = "<time></time><span></span>";
  li.firstChild.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  li.lastChild.textContent = text;
  const log = $("#log");
  log.append(li);
  while (log.children.length > 200) log.firstChild.remove();
  log.scrollTop = log.scrollHeight;
}

function renderLeft(finalToo = false) { // seconds until the preview (or the export) is ready, from the steps still to run
  const p = S.plate, r = S.renders.get(S.heroKey);
  if (!p || !S.heroKey || (finalToo ? r?.exported : r?.comp)) return 0;
  const active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
  const skip = r?.skip ?? plan({}, active).skip;
  let t = 0;
  for (const st of STAGES) {
    if (st.final && !finalToo) break;
    if (skip.has(st.id) || r?.done?.[st.id] !== undefined) continue;
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
  $("#render").hidden = !p;
  list.hidden = !active.length;
  if (!p || !active.length) { $("#render-left").textContent = ""; return timelineBar(); }
  const skip = r?.skip ?? plan({}, active).skip, waiting = !S.background && !S.wantDownload;
  list.replaceChildren(...STAGES.filter((st) => !skip.has(st.id)).map((st) => {
    const li = document.createElement("li"), took = r?.done?.[st.id];
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
  $("#render-left").textContent = stale() || !r?.comp ? (pre ? `preview ${secs(pre)}` : busy ? "preview almost ready" : "")
    : r?.exported ? "export ready" : waiting ? "preview ready" : all ? `export ${secs(all)}` : busy ? "export almost ready" : "";
  timelineBar();
}

function timelineBar() { // the line under the timeline: the preview in gold, then the export in grey, green when exported
  const bar = $("#tl-render"), r = S.renders.get(S.heroKey);
  bar.className = "tl-render";
  if (!S.plate || !S.heroKey || !r) { bar.style.width = "0"; if (S.heroKey && stale()) bar.classList.add("stale"); return; }
  const steps = STAGES.filter((st) => !r.skip?.has(st.id) && (!st.final || S.background || S.wantDownload || r.exported));
  const total = steps.reduce((a, st) => a + estimate(st.id), 0);
  let done = steps.reduce((a, st) => a + (r.done?.[st.id] !== undefined ? estimate(st.id) : 0), 0);
  if (S.stage?.key === S.heroKey) done += estimate(S.stage.id) * S.stage.progress;
  bar.style.width = `${Math.round((done / Math.max(1, total)) * 100)}%`;
  if (r.exported) bar.classList.add("ready");
  else if (r.comp) bar.classList.add("export");
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
  $("#tl-key").hidden = !S.edits.some((e) => e.on && e.patch);
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
  $("#preview-size").value = String(cap);
  if (!S.plate) return;
  const [w, h] = [S.plate.spec.width, S.plate.spec.height];
  S.plate.shot = fitSize(w, h, cap, 32);
  S.renders.clear(); S.exported = null;
  if (S.shot) S.shot.key = ""; // what plays now is from the other size until the new preview is ready
  S.shotDirty = !!S.heroKey;
  status(`Previews at ${S.plate.shot[0]} × ${S.plate.shot[1]}. The export stays at full size.`);
  stagesUI(); exportUI(); touch();
}

function exportUI() {
  const b = $("#export-btn"), edits = S.edits.some((e) => e.on && e.patch);
  b.disabled = !S.plate || !edits;
  b.textContent = S.wantDownload ? `Exporting${renderLeft(true) ? `, ${secs(renderLeft(true))}` : ""}` : "Export";
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
  S.tool = t;
  S.rub = false;
  $("#rub-btn").setAttribute("aria-pressed", "false");
  $$(".tools [data-tool]").forEach((b) => b.classList.toggle("on", b.dataset.tool === t));
  $("#prompt").placeholder = HINT[t];
  colorUI();
  render();
}

function setSize(v) {
  S.size = Math.max(4, Math.min(320, Math.round(v)));
  $("#size").value = S.size;
  $("#size-out").textContent = S.size;
  render();
}

function openDialog() { $("#files").value = ""; $("#open").showModal(); }

async function boot() { // the workflows, the WebSocket, then what this ComfyUI lacks: nodes, then model files
  onNotice(status);
  await loadWorkflows(WORKFLOWS);
  connect();
  const combo = (spec) => (Array.isArray(spec?.[0]) ? spec[0] : spec?.[1]?.options ?? []); // V1 or V3 schema
  const spaces = combo((await objectInfo("ImageColorSpace"))?.input.required.source);
  $("#cs").replaceChildren(...(spaces.length ? spaces : ["sRGB"]).map((s) => new Option(s, s)));
  const needs = { PaintAPlate_LoadPlate: "this pack", PaintAPlate_FillMatte: "this pack, restart ComfyUI after an update",
    LTXAddVideoICLoRAGuide: "ComfyUI-LTXVideo", SAM3_VideoTrack: "ComfyUI 0.42 or newer", ReferenceMultiLatent: "ComfyUI 0.41 or newer" };
  const missing = [];
  for (const [cls, from] of Object.entries(needs)) if (!(await objectInfo(cls))) missing.push(`${cls} (${from})`);
  if (missing.length) return status(`Missing nodes: ${missing.join(", ")}. Install them, then reload this page.`);
  const models = new Map(); // every model file the workflows load, by loader and input
  for (const wf of Object.values(WF)) for (const n of Object.values(wf.prompt))
    for (const [k, v] of Object.entries(n.inputs)) if (typeof v === "string" && v.endsWith(".safetensors")) models.set(v, [n.class_type, k]);
  const absent = [];
  for (const [file, [cls, input]] of models) if (!combo((await objectInfo(cls))?.input.required[input]).includes(file)) absent.push(file);
  status(absent.length ? `Missing model files: ${absent.join(", ")}. See the README for where to put them.` : "Ready. Open a plate to start.");
}

$$(".tools [data-tool]").forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
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
$("#whole").onchange = () => setTool("erase");
$("#prompt").oninput = () => { if (S.draft && !stroke) schedule(); };
$("#open-btn").onclick = $("#empty-open").onclick = openDialog;
$("#help-btn").onclick = () => $("#help").showModal();
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
};
$("#files").onchange = (e) => { const ext = e.target.files[0]?.name.split(".").pop().toLowerCase(); $("#cs").value = ext === "exr" ? "linear" : "sRGB"; };
$("#open-go").onclick = () => openPlate([...$("#files").files], $("#path").value.trim(), $("#cs").value).catch(quiet);

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
    if (e.key === "Enter" && e.target.id === "prompt") { if (S.draft) launch(S.draft); e.target.blur(); e.preventDefault(); }
    else if (e.key === "Escape") e.target.blur();
    return;
  }
  if (e.key === "?" && $("#help").open) { $("#help").close(); return e.preventDefault(); }
  if ($("dialog[open]")) return;
  const k = e.key, low = k.toLowerCase(), mod = e.ctrlKey || e.metaKey;
  if (!S.plate && !["?", "F6"].includes(k)) return;
  if (k === " " || k === "ArrowDown") S.playing ? pause() : play();
  else if (k === "ArrowLeft" || k === "ArrowRight") { pause(); seek(S.frame + (k === "ArrowLeft" ? -1 : 1)); }
  else if (k === "Home") { pause(); seek(S.inPt); }
  else if (k === "End") { pause(); seek(S.outPt); }
  else if (k === "[") setIn(S.frame);
  else if (k === "]") setOut(S.frame);
  else if (k === "\\") { S.inPt = 0; S.outPt = S.plate.frames - 1; hud("In and out points cleared"); timelineUI(); }
  else if (k === "F6") setWipe(S.wipe === null);
  else if (low === "f" && !mod) zoomTo(1);
  else if (k === "1" && !mod) zoomTo(S.plate.work[0] / S.fit.w);
  else if (k === "`") document.fullscreenElement ? document.exitFullscreen() : document.documentElement.requestFullscreen();
  else if (k === "?") $("#help").showModal();
  else if (TOOLS[low] && !mod) setTool(TOOLS[low]);
  else if (low === "x" && !mod) setRub(!S.rub);
  else if (k === "-" || k === "_") setSize(S.size / 1.2);
  else if (k === "=" || k === "+") setSize(S.size * 1.2);
  else if (k === "Enter") { if (S.draft) launch(S.draft); else if (S.edits.length) again(S.edits.at(-1)); }
  else if (k === "Escape") discard();
  else if (low === "z" && mod) e.shiftKey ? redo() : undo();
  else if (low === "y" && mod) redo();
  else if (low === "o" && !mod) { if (!S.compare) { S.compare = true; render(); hud("Plate"); } }
  else return;
  e.preventDefault();
});
addEventListener("keyup", (e) => { if (e.key.toLowerCase() === "o" && S.compare) { S.compare = false; render(); } });
new ResizeObserver(() => { fitView(); cacheUI(); }).observe($("#viewport"));

setTool("paint");
setSize(48);
boot().catch(quiet);
