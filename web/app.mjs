// AInVFX PaintAPlate: one viewer to play a plate, paint edits on its first frame and watch the edited shot.
// The page runs on the ComfyUI server that serves it. Every step is a workflow from ./workflows.

const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];
const CLIENT = crypto.randomUUID();
const WF = {}; // name -> { prompt, slots, outputs }
const live = new Set(); // jobs not finished yet
const byId = new Map(); // prompt id -> job, for WebSocket messages
const early = new Map(); // results that arrived before /prompt answered
const memo = new Map(); // prompt -> outputs, for prompts ComfyUI serves entirely from its cache
let running = null; // the prompt ComfyUI is executing now
let socket = false; // the WebSocket is open: when it is not, finished prompts are found by polling /history

const Q = new URLSearchParams(location.search);
const WAIT = +Q.get("wait") || 2000; // pause after the last stroke before the edit starts, in ms
const REFINE_STEPS = +Q.get("refine") || 8; // full-size steps after the quick pass
const TOOLS = { b: "paint", e: "erase", l: "light" };
const NAME = { paint: "Paint", erase: "Erase", light: "Light" };
const HINT = {
  paint: "Describe what to paint, then paint it on the frame. A fire, a wooden desk, a red umbrella",
  erase: "Erase needs no words: paint over what should go",
  light: "Optional: describe the light, then paint where it comes from. Warm sunset, neon sign",
};
const BACKGROUND = ["shot", "matte", "comp", "export"];

const S = {
  plate: null, original: null, hero: null, heroVersion: 0,
  edits: [], draft: null, running: null, removed: [], ids: 0, count: 0, chain: Promise.resolve(), queued: 0,
  tool: "paint", size: 48, color: "#f5b800",
  frame: 0, playing: false, inPt: 0, outPt: 0, wipe: null, compare: false,
  fit: { w: 0, h: 0, x: 0, y: 0 }, zoom: { k: 1, x: 0, y: 0 },
  shot: null, shotDirty: false, stage: { phase: "none" }, run: 0, exported: null, wantDownload: false,
  heroKey: "", renders: new Map(), // set of edits -> what has been rendered for it
  uploads: new Map(), timer: 0,
};

const view = $("#view"), ctx = view.getContext("2d");
const plateVid = $("#plate-video"), shotVid = $("#shot-video");
const fx = document.createElement("canvas"); // scratch layer for masked overlays

// ---------- ComfyUI ----------

const post = (path, body) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function upload(blob, name, sub = `paintaplate/${S.plate.id}`) {
  const form = new FormData();
  form.append("image", blob, name);
  form.append("subfolder", sub);
  form.append("overwrite", "true");
  const r = await fetch("/upload/image", { method: "POST", body: form });
  if (!r.ok) throw new Error(`Upload failed: ${name}`);
  const j = await r.json();
  return j.subfolder ? `${j.subfolder}/${j.name}` : j.name;
}

function parse(prompt) { // slots and outputs are written in each node's _meta by tools/build_workflows.py
  const slots = {}, outputs = {};
  for (const [id, node] of Object.entries(prompt)) {
    for (const [input, name] of Object.entries(node._meta?.slots ?? {})) (slots[name] ??= []).push([id, input]);
    if (node._meta?.output) outputs[node._meta.output] = id;
  }
  return { prompt, slots, outputs };
}

function run(name, values, { kind = name, preview, progress, front = false, edit } = {}) {
  const wf = structuredClone(WF[name]);
  for (const [slot, value] of Object.entries(values))
    for (const [id, input] of wf.slots[slot] ?? []) wf.prompt[id].inputs[input] = value;
  edit?.(wf);
  const job = { kind, preview, progress, retries: 1, key: JSON.stringify(wf.prompt) };
  job.done = new Promise((resolve, reject) => Object.assign(job, { resolve, reject }));
  job.submit = () => post("/prompt", { prompt: wf.prompt, client_id: CLIENT, front }).then((r) => r.json()).then((j) => {
    if (!j.prompt_id) throw new Error(rejection(j));
    job.id = j.prompt_id;
    job.heard = Date.now();
    if (job.cancelled) return void drop(job); // cancelled while it was being posted
    byId.set(job.id, job);
    if (early.has(job.id)) finish(job.id, early.get(job.id));
  }).catch((e) => job.reject(e));
  live.add(job);
  job.submit();
  return job;
}

function rejection(j) {
  const node = Object.values(j.node_errors ?? {})[0];
  const err = node?.errors?.[0];
  return node ? `${node.class_type}: ${err?.details || err?.message}` : j.error?.message ?? "Workflow rejected";
}

async function finish(id, error) {
  if (id === running) running = null;
  const job = byId.get(id);
  if (!job) return void early.set(id, error);
  byId.delete(id);
  early.delete(id);
  // An interrupt can land on the next prompt when the one it targeted had just finished: run it again once.
  if (error === "cancelled" && !job.cancelled && job.retries-- > 0) return job.submit();
  live.delete(job);
  if (error) return job.reject(new Error(error));
  const history = await (await fetch(`/history/${id}`)).json();
  let out = history[id]?.outputs ?? {};
  if (files(out).length || texts(out).length) memo.set(job.key, out);
  else out = memo.get(job.key) ?? out;
  if (memo.size > 64) memo.delete(memo.keys().next().value);
  job.resolve(out);
}

function drop(job) { // remove it from the queue, and stop it if it is the one running (ComfyUI checks the id)
  if (!job.id) return;
  post("/queue", { delete: [job.id] });
  post("/interrupt", { prompt_id: job.id });
}

function cancel(...kinds) {
  for (const job of live) {
    if (!kinds.includes(job.kind)) continue;
    Object.assign(job, { cancelled: true });
    live.delete(job);
    byId.delete(job.id);
    job.reject(new Error("cancelled"));
    drop(job);
  }
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?clientId=${CLIENT}`);
  ws.binaryType = "arraybuffer";
  ws.onopen = () => { socket = true; ws.send(JSON.stringify({ type: "feature_flags", data: { supports_preview_metadata: true } })); };
  ws.onclose = () => { socket = false; setTimeout(connect, 2000); };
  ws.onmessage = ({ data }) => {
    if (typeof data !== "string") { // step preview with metadata: [type=4][length][json][image]
      const v = new DataView(data);
      if (v.getUint32(0) !== 4) return;
      const n = v.getUint32(4);
      const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(data, 8, n)));
      byId.get(meta.prompt_id)?.preview?.(new Blob([new Uint8Array(data, 8 + n)], { type: meta.image_type }));
      return;
    }
    const { type, data: d } = JSON.parse(data);
    const heard = byId.get(d?.prompt_id);
    if (heard) heard.heard = Date.now();
    if (type === "execution_start") { running = d.prompt_id; byId.get(d.prompt_id)?.progress?.(0); }
    else if (type === "progress") byId.get(d.prompt_id)?.progress?.(d.value / d.max);
    else if (type === "execution_success") finish(d.prompt_id);
    else if (type === "execution_error") finish(d.prompt_id, `${d.node_type}: ${d.exception_message}`);
    else if (type === "execution_interrupted") finish(d.prompt_id, "cancelled");
  };
}

// Some networks block WebSockets: then, and for any prompt not heard of for 15 s, ask /history whether it finished.
setInterval(async () => {
  for (const job of [...byId.values()]) {
    if (socket && Date.now() - job.heard < 15000) continue;
    let st;
    try { st = (await (await fetch(`/history/${job.id}`)).json())[job.id]?.status; } catch { continue; }
    if (!st || !byId.has(job.id)) continue;
    job.heard = Date.now();
    const err = st.messages?.find((m) => m[0] === "execution_error")?.[1];
    if (st.status_str === "error") finish(job.id, st.messages?.some((m) => m[0] === "execution_interrupted") ? "cancelled"
      : err ? `${err.node_type}: ${err.exception_message}` : "The workflow failed");
    else if (st.completed) finish(job.id);
  }
}, 1500);

const files = (out) => Object.values(out).flatMap((o) => [...(o.images ?? []), ...(o.gifs ?? []), ...(o.video ?? [])]);
const texts = (out) => Object.values(out).flatMap((o) => o.text ?? []);
const fileOf = (name, out, key) => files({ x: out[WF[name].outputs[key]] ?? {} })[0];
const textOf = (name, out, key) => out[WF[name].outputs[key]]?.text?.[0];
const url = (f) => `/view?${new URLSearchParams({ filename: f.filename, subfolder: f.subfolder, type: f.type })}`;
const quiet = (e) => e?.message !== "cancelled" && status(e?.message ?? String(e));

// ---------- Images ----------

const canvas = ([w, h]) => Object.assign(document.createElement("canvas"), { width: w, height: h });
const blob = (c) => new Promise((r) => c.toBlob(r, "image/png"));
const loadImage = (src) => new Promise((res, rej) => Object.assign(new Image(), { onload() { res(this); }, onerror: rej, src }));
const uploadCanvas = async (c, name) => upload(await blob(c), name);

function snap(src, size, fill) {
  const c = canvas(size), x = c.getContext("2d");
  if (fill) { x.fillStyle = fill; x.fillRect(0, 0, c.width, c.height); }
  if (src) x.drawImage(src, 0, 0, c.width, c.height);
  return c;
}

// Sizes in multiples of `step` (what the models need) that keep the plate's aspect within 1.5%, as large as allowed.
function fitSize(w, h, cap, step) {
  const long = Math.max(w, h), short = Math.min(w, h), aspect = long / short;
  const top = Math.max(step, Math.floor(Math.min(cap, long) / step) * step);
  let best = null;
  for (let L = top; L >= Math.max(step, top * 0.75); L -= step) {
    const s = Math.max(step, Math.round((short * L) / long / step) * step), err = Math.abs(L / s - aspect) / aspect;
    if (!best || err < best.err) best = { L, s, err };
    if (err <= 0.015) { best = { L, s, err }; break; }
  }
  return w >= h ? [best.L, best.s] : [best.s, best.L];
}

function editImage(e, before, size) { // what Klein sees: the strokes over the frame; for an erase, the frame itself
  const c = snap(before, size);
  if (e.tool === "erase") return c; // told to remove the object, Klein cleans it; shown a filled hole, it drew a new object there
  c.getContext("2d").drawImage(e.paint, 0, 0, size[0], size[1]);
  return c;
}

const maskAt = (e, size) => (e.tool === "light" ? snap(null, size, "#fff") : snap(e.mask, size, "#000"));

function bounds(mask) { // painted area as FLUX 3 box coordinates: [y_min, x_min, y_max, x_max] on 0..1000
  const c = snap(mask, [256, Math.max(1, Math.round((256 * mask.height) / mask.width))]);
  const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
  let [x0, y0, x1, y1] = [c.width, c.height, -1, -1];
  for (let i = 3; i < d.length; i += 4) {
    if (d[i] < 16) continue;
    const p = (i - 3) / 4, x = p % c.width, y = (p / c.width) | 0;
    x0 = Math.min(x0, x); x1 = Math.max(x1, x); y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  return x1 < 0 ? [0, 0, 1000, 1000] : [y0 / c.height, x0 / c.width, (y1 + 1) / c.height, (x1 + 1) / c.width].map((v) => Math.round(v * 1000));
}

const dark = (hex) => [1, 3, 5].reduce((a, i, k) => a + [0.2126, 0.7152, 0.0722][k] * parseInt(hex.slice(i, i + 2), 16), 0) < 60;

function colorName(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  if (max - min < 0.12) return max > 0.6 ? "white" : "soft grey";
  const h = (max === r ? (g - b) / (max - min) : max === g ? 2 + (b - r) / (max - min) : 4 + (r - g) / (max - min)) * 60;
  return ["red", "warm orange", "golden yellow", "green", "cyan", "cool blue", "violet", "magenta"][Math.floor(((h + 360 + 22) % 360) / 45)];
}

function caption(e) { // the same text and table FLUX 3 Image Layout Prompt writes, built here per edit
  const words = e.prompt;
  const text = {
    erase: "Remove the object inside <obj_1> completely, with its shadow and its reflection. Show the surface and the background that continue behind it, with matching detail, light, shadows and focus. Add no new object. Keep everything else unchanged.",
    paint: `Replace the rough coloured drawing inside <obj_1> with ${words || "a realistic object of that shape and colour"}, in exactly the same style, lighting, perspective and grain as the rest of the image. Keep everything else unchanged.`,
    light: `Relight the whole scene with ${words || `${colorName(e.strokes.find((s) => !dark(s.color))?.color ?? e.color)} light`} coming from <obj_1>, with physically consistent shadows and reflections.${e.strokes.some((s) => dark(s.color)) ? " Dark strokes are hints of where shadows fall: make every shadow agree with the light." : ""} Keep the content, framing and textures unchanged.`,
  }[e.tool];
  const desc = { erase: "object to remove", paint: words || "the drawn object", light: "light source" }[e.tool];
  return `${text} ${JSON.stringify([{ id: "obj_1", bbox: bounds(e.mask), desc }])}`;
}

// ---------- Plate ----------

async function openPlate(list, typed, cs) {
  if (!list.length && !typed) return status("Choose files, or type a path in ComfyUI's input folder.");
  stopEverything();
  Object.assign(S, { plate: null, hero: null, original: null }); // nothing to draw while the new plate loads
  const id = Date.now().toString(36), sub = `paintaplate/${id}`;
  let path = typed, out;
  try {
    if (list.length) {
      for (const [i, f] of list.entries()) { status(`Uploading ${i + 1} of ${list.length}`); await upload(f, f.name, sub); }
      path = list.length === 1 ? `${sub}/${list[0].name}` : sub;
    }
    status("Reading the plate");
    out = await run("ingest", { path, color_space: cs, prefix: `${sub}/hero`, video_prefix: `${sub}/proxy` }).done;
  } catch (err) {
    $("#empty").hidden = false;
    for (const b of ["#play-btn", "#wipe-btn"]) $(b).disabled = true;
    throw err;
  }
  const spec = JSON.parse(textOf("ingest", out, "spec"));
  const [w, h] = [spec.width, spec.height];
  const stem = (spec.kind === "video" ? spec.source : spec.first_file ?? spec.source ?? "plate").split(/[\\/]/).pop()
    .replace(/\.[^.]+$/, "").replace(/[._]?\d+$/, "") || "plate";
  S.plate = { id, path, cs, spec, frames: spec.frames, fps: spec.fps || 24, name: stem,
    first: spec.kind === "video" ? 1 : spec.first_frame ?? 1,
    work: fitSize(w, h, 1920, 32), prev: fitSize(w, h, 768, 16), shot: fitSize(w, h, 960, 32) };
  if (Q.get("shot") === "full") S.plate.shot = S.plate.work;
  S.original = snap(await loadImage(url(fileOf("ingest", out, "hero"))), S.plate.work);
  Object.assign(S, { hero: S.original, heroVersion: 0, edits: [], draft: null, running: null, removed: [], count: 0,
    frame: 0, inPt: 0, outPt: S.plate.frames - 1, shot: null, shotDirty: false, exported: null, wantDownload: false,
    stage: { phase: "none" }, zoom: { k: 1, x: 0, y: 0 }, wipe: null, heroKey: "" });
  S.uploads.clear(); S.renders.clear();
  [view.width, view.height] = S.plate.work;
  view.classList.add("painting");
  plateVid.src = url(fileOf("ingest", out, "proxy"));
  shotVid.removeAttribute("src"); shotVid.load();
  $("#empty").hidden = true;
  for (const b of ["#play-btn", "#wipe-btn"]) $(b).disabled = false;
  const kind = spec.kind === "video" ? spec.codec : `${spec.ext.slice(1).toUpperCase()} ${spec.kind}`;
  $("#spec").textContent = `${S.plate.name}: ${kind}, ${w} × ${h}, ${Math.round(S.plate.fps * 1000) / 1000} fps, ${spec.frames} frames, ${cs}`;
  document.activeElement?.blur();
  fitView(); historyUI(); timelineUI(); stageUI(); exportUI(); render();
  warm();
  const offered = [...$("#cs").options].some((o) => o.value === spec.color_space_guess);
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
  const done = S.stage.phase === "preview" ? `, the edited shot is ${Math.round((S.stage.progress ?? 0) * 100)}% done` : "";
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
  if (!S.playing) for (const v of [plateVid, shotVid]) if (v.getAttribute("src") && v.readyState) v.currentTime = time(S.frame);
  render(); timelineUI();
}

for (const v of [plateVid, shotVid]) {
  v.addEventListener("seeked", () => !S.playing && render());
  v.addEventListener("error", () => v.getAttribute("src") &&
    status(`This browser cannot play the ${v === plateVid ? "plate" : "shot"} preview (H.264 MP4). Chrome, Edge, Safari and Firefox can.`));
}
plateVid.addEventListener("loadeddata", () => seek(S.frame));
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
  S.heroVersion++;
  const key = S.edits.filter((e) => e.on && e.patch && e.state !== "generating").map((e) => `${e.id}.${e.version}`).join(",");
  if (key === S.heroKey) return;
  S.heroKey = key;
  const r = S.renders.get(key); // a set of edits seen before plays at once (a bypass turned back on, for example)
  S.exported = r?.exported ?? null;
  if (r?.comp) setShot(r.comp, key);
  else if (!key) setShot(null, key);
  S.shotDirty = !!key && !r?.exported;
  stageUI(); exportUI();
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
  const draw = (src) => { if (!(src instanceof HTMLVideoElement) || src.readyState >= 2) ctx.drawImage(src, 0, 0, W, H); };
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
  const key = `${e.strokes.length}:${e.snapped ?? 0}`;
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
  ctx.strokeStyle = S.tool === "erase" ? "#ff8070" : S.color;
  ctx.beginPath(); ctx.arc(S.cursor[0], S.cursor[1], S.size / 2, 0, 2 * Math.PI); ctx.stroke();
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
  if (e.button !== 0) return;
  if (S.playing) pause();
  if (S.frame !== 0) { seek(0); hud("Edits are painted on the first frame"); }
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
  schedule();
});

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

function redrawStrokes(d) {
  for (const c of [d.paint, d.mask]) c.getContext("2d").clearRect(0, 0, c.width, c.height);
  for (const s of d.strokes) drawStroke(d, s);
  d.snapped = 0;
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
    if (edit.tool === "erase" && edit.whole && edit.snapped !== edit.strokes.length) {
      edit.snapped = edit.strokes.length;
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
    const values = { base, reference, start: light ? base : reference, caption: caption(edit), steps: 8, seed: edit.seed,
      mask: await uploadCanvas(maskAt(edit, size), `${tag}_mask.png`), denoise: light ? 0.65 : 1,
      grow: Math.round(size[0] / reach(edit)), feather: 6, sigma: 3 };
    const quick = await run("edit", values, { kind: "edit", front: true, preview: show, progress: (f) => editProgress(edit, f / 2) }).done;
    if (!alive()) return;
    edit.preview = await loadImage(url(fileOf("edit", quick, "patch")));
    edit.shown ??= performance.now();
    edit.latent = null; render();
    // 2. The same seed at full size, starting from the quick pass: it resolves in place.
    status(`Edit ${edit.n}: ${NAME[edit.tool].toLowerCase()}, full size`);
    const work = p.work, start = snap(before, work);
    start.getContext("2d").drawImage(edit.preview, 0, 0, work[0], work[1]);
    const full = await run("edit", { ...values, base: await baseUpload(edit, before, work),
      start: await uploadCanvas(start, `${tag}_start.png`), reference: await uploadCanvas(editImage(edit, before, work), `${tag}_ref_full.png`),
      mask: await uploadCanvas(maskAt(edit, work), `${tag}_mask_full.png`), steps: REFINE_STEPS, denoise: 0.35,
      grow: Math.round(work[0] / reach(edit)), feather: 12, sigma: 6 }, { kind: "edit", front: true,
      progress: (f) => editProgress(edit, 0.5 + f / 2) }).done;
    if (!alive()) return;
    edit.patch = await loadImage(url(fileOf("edit", full, "patch")));
    Object.assign(edit, { preview: null, latent: null, state: "done", version: edit.version + 1, force: false, kept: undefined });
    edit.foot = footprint(edit);
    edit.basis = activeBefore(edit).map((e) => ({ id: e.id, v: e.version, tool: e.tool, foot: e.foot }));
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

const reach = (e) => (e.tool === "erase" ? 24 : 48); // the edit mask grows by the frame width over this

async function snapErase(edit, before) { // SAM 3.1 grows the erase strokes to the whole object under them
  const size = S.plate.prev, k = size[0] / S.plate.work[0];
  const pts = edit.strokes.flatMap((s) => s.points);
  const picks = [...new Set([0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * (pts.length - 1))))]; // up to five points
  const points = picks.map((i) => ({ x: Math.round(pts[i][0] * k), y: Math.round(pts[i][1] * k) }));
  status("Finding the object under the stroke");
  const out = await run("snap", { image: await uploadCanvas(snap(before, size), `e${edit.id}_snap.png`), points: JSON.stringify(points) },
    { kind: "snap", front: true }).done;
  const pixels = (c) => c.getContext("2d").getImageData(0, 0, size[0], size[1]).data;
  const sam = snap(await loadImage(url(fileOf("snap", out, "mask"))), size), s = pixels(sam), m = pixels(maskAt(edit, size));
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
  edit.mask.getContext("2d").drawImage(sam, 0, 0, edit.mask.width, edit.mask.height);
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

const overlap = (a, b) => !!a && !!b && a.bits.some((v, i) => v && b.bits[i]);

function needsRegen(edit) { // an edit is made again when something it saw has changed: a light, or an overlapping edit
  const now = activeBefore(edit), was = edit.basis;
  const nowKeys = new Set(now.map((e) => `${e.id}.${e.version}`)), wasKeys = new Set(was.map((b) => `${b.id}.${b.v}`));
  const changed = [...now.filter((e) => !wasKeys.has(`${e.id}.${e.version}`)), ...was.filter((b) => !nowKeys.has(`${b.id}.${b.v}`))];
  if (!changed.length) return false;
  return edit.tool === "light" || changed.some((c) => c.tool === "light" || overlap(c.foot, edit.foot));
}

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
    d.strokes.pop();
    if (d.strokes.length) { redrawStrokes(d); render(); schedule(); }
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
    if (d.kept !== undefined) { d.strokes.length = d.kept; redrawStrokes(d); d.snapped = d.strokes.length; }
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
function touch() { clearTimeout(idleTimer); idleTimer = setTimeout(idle, 1500); }

function idle() {
  if (!S.plate) return;
  if (S.draft || S.running || S.queued || stroke) return touch();
  if (S.shotDirty) pipeline().catch((e) => {
    if (e?.message === "cancelled") { S.shotDirty = true; touch(); }
    else { quiet(e); stage({ phase: "none" }); }
  });
}

const grow = (w, erase) => Math.max(4, Math.round(w / (erase ? 24 : 160))); // composite edge, in pixels of that size
const feather = (w) => Math.max(6, Math.round(w / 96));

async function pipeline() {
  S.shotDirty = false;
  cancel(...BACKGROUND);
  const p = S.plate, key = S.heroKey, active = S.edits.filter((e) => e.on && e.patch && e.state === "done");
  if (!key || !active.length) return;
  const fresh = () => key === S.heroKey;
  let r = S.renders.get(key);
  if (!r) { r = { v: ++S.run }; r.base = `paintaplate/${p.id}/v${r.v}`; S.renders.set(key, r); }
  const base = r.base, relight = active.some((e) => e.tool === "light"), [sw, sh] = p.shot;
  const erase = active.some((e) => e.tool === "erase");
  const pct = (phase, label) => (f) => fresh() && stage({ phase, label, progress: f });
  r.hero ??= await uploadCanvas(S.hero, `hero_v${r.v}.png`);
  const common = { path: p.path, color_space: p.cs, max_frames: p.frames, hero: r.hero, seed: active[0].seed };
  if (!r.shot) {
    pct("preview", "Rendering the shot")(0);
    await run("shot", { ...common, width: sw, height: sh, prefix: `${base}/shot/f`, video_prefix: `${base}/raw` },
      { kind: "shot", progress: pct("preview", "Rendering the shot") }).done;
    r.shot = `output:${base}/shot`;
  }
  if (!fresh()) return;
  r.mattes ??= await track(active, r.shot, base, "", pct("preview", "Tracking the edits"));
  if (!fresh()) return;
  if (!r.comp) {
    const comp = await run("comp", { path: p.path, color_space: p.cs, max_frames: p.frames, width: sw, height: sh, shot: r.shot,
      ...r.mattes.values, relight, grow: grow(sw, erase), feather: feather(sw), video_prefix: `${base}/comp` },
      { kind: "comp", progress: pct("preview", "Compositing"), edit: (wf) => { if (!r.mattes.any) dropMattes(wf); } }).done;
    r.comp = url(fileOf("comp", comp, "video"));
  }
  if (!fresh()) return;
  if (S.shot?.url !== r.comp) {
    setShot(r.comp, key);
    hud("The edited shot is ready: Space plays it", 2500);
    status("The edited shot is ready. The export renders next, at full size.");
  }
  if (!r.final) {
    if (sw !== p.work[0] || sh !== p.work[1]) {
      await run("shot", { ...common, width: p.work[0], height: p.work[1], prefix: `${base}/full/f`, video_prefix: `${base}/full` },
        { kind: "shot", progress: pct("export", "Rendering at full size") }).done;
      r.final = `output:${base}/full`;
    } else r.final = r.shot;
  }
  if (!fresh()) return;
  r.full ??= r.final !== r.shot && active.some((e) => e.tool === "paint")
    ? await track(active, r.final, base, "_full", pct("export", "Tracking at full size"), r.mattes) : r.mattes;
  if (!fresh()) return;
  if (!r.exported) {
    const done = await run("export", { path: p.path, color_space: p.cs, max_frames: p.frames, shot: r.final, ...r.full.values, relight,
      keep_untouched: !relight, prefix: `${base}/export`, matte_prefix: `${base}/matte/matte`, grow: grow(p.spec.width, erase),
      feather: feather(p.spec.width) }, { kind: "export", progress: pct("export", "Exporting at full quality"),
      edit: (wf) => { if (!r.full.any) dropMattes(wf); } }).done;
    r.exported = { run: base, name: `${p.name}_paintaplate_v${r.v}`, text: textOf("export", done, "export") ?? "" };
  }
  if (!fresh()) return;
  S.exported = r.exported;
  stage({ phase: "ready" }); exportUI();
  status(`Exported to the output folder: ${S.exported.text.split("\n")[0]}. Export downloads it as a zip.`);
  if (S.wantDownload) { S.wantDownload = false; download(); }
}

async function track(active, shotPath, base, suffix, progress, previous) { // SAM 3.1 follows each kind of edit through the shot
  const p = S.plate, [sw, sh] = p.shot, found = { ...(previous?.found ?? {}) };
  for (const [key, tool, path, cs] of [["matte_a", "erase", p.path, p.cs], ["matte_b", "paint", shotPath, "sRGB"]]) {
    const edits = active.filter((e) => e.tool === tool);
    if (!edits.length || (previous && tool === "erase")) continue; // the erase matte follows the plate: it does not change
    const union = canvas(p.shot), u = union.getContext("2d");
    u.fillStyle = "#000"; u.fillRect(0, 0, sw, sh);
    u.globalCompositeOperation = "lighten";
    for (const e of edits) u.drawImage(tool === "paint" ? whiteOf(e.patch) : e.mask, 0, 0, sw, sh);
    await run("matte", { path, color_space: cs, max_frames: p.frames, width: sw, height: sh, prefix: `${base}/${key}${suffix}/m`,
      mask: await uploadCanvas(union, `${key}${suffix}_${S.run}.png`) }, { kind: "matte", progress }).done;
    found[key] = `output:${base}/${key}${suffix}`;
  }
  const a = found.matte_a ?? found.matte_b, b = found.matte_b ?? found.matte_a;
  return { found, any: !!a, values: { matte_a: a ?? "", matte_b: b ?? "" } };
}

function whiteOf(img, tint) { // a patch's alpha (where the edit put new pixels) as a white mask, or as a tint
  const c = snap(img, [img.width, img.height]), x = c.getContext("2d", { willReadFrequently: true });
  const d = x.getImageData(0, 0, c.width, c.height);
  const [r, g, b] = tint ? [1, 3, 5].map((i) => parseInt(tint.slice(i, i + 2), 16)) : [255, 255, 255];
  for (let i = 0; i < d.data.length; i += 4) {
    const on = d.data[i + 3] > 127;
    [d.data[i], d.data[i + 1], d.data[i + 2]] = on ? [r, g, b] : [0, 0, 0];
    d.data[i + 3] = tint ? (on ? 255 : 0) : 255;
  }
  x.putImageData(d, 0, 0);
  return c;
}

function dropMattes(wf) { // relight only: no matte, so nothing to composite and no matte to save
  for (const [id, input] of wf.slots.fit_mask ?? []) delete wf.prompt[id].inputs[input];
  const gone = new Set([...(wf.slots.matte_a ?? []), ...(wf.slots.matte_b ?? [])].map(([id]) => id));
  if (wf.outputs.matte) gone.add(wf.outputs.matte);
  for (let grew = true; grew;) {
    grew = false;
    for (const [id, node] of Object.entries(wf.prompt)) {
      if (gone.has(id) || !Object.values(node.inputs).some((v) => Array.isArray(v) && gone.has(String(v[0])))) continue;
      gone.add(id); grew = true;
    }
  }
  for (const id of gone) delete wf.prompt[id];
}

function download() {
  const a = Object.assign(document.createElement("a"), {
    href: `/paintaplate/download?${new URLSearchParams({ run: S.exported.run, name: S.exported.name })}`,
    download: `${S.exported.name}.zip` });
  document.body.append(a); a.click(); a.remove();
  status(`Downloading ${S.exported.name}.zip: the export in the plate's format, and its matte.`);
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

function stage(s) { S.stage = s; stageUI(); exportUI(); }

function stageUI() {
  const bar = $("#tl-render"), note = $("#render-note"), s = S.stage;
  bar.className = "tl-render";
  bar.style.width = "0";
  note.textContent = "";
  if (s.phase === "preview" || s.phase === "export") {
    bar.classList.toggle("export", s.phase === "export");
    bar.style.width = `${Math.round((s.progress ?? 0) * 100)}%`;
    note.textContent = `${s.label} ${Math.round((s.progress ?? 0) * 100)}%`;
  } else if (s.phase === "ready") { bar.classList.add("ready"); note.textContent = "Exported"; }
  if (stale() && s.phase !== "preview") bar.classList.add("stale");
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
  $("#tl-key").style.left = pos(0);
  $("#frame-now").textContent = p.first + S.frame;
  $("#frame-total").textContent = `/ ${p.first + n - 1}`;
  $("#fps").textContent = `${Math.round(p.fps * 100) / 100} fps`;
  const t = $("#timeline");
  t.setAttribute("aria-valuemin", p.first); t.setAttribute("aria-valuemax", p.first + n - 1); t.setAttribute("aria-valuenow", p.first + S.frame);
  stageUI();
}

function exportUI() {
  const b = $("#export-btn"), edits = S.edits.some((e) => e.on && e.patch);
  b.disabled = !S.plate || (!edits && !S.exported);
  const s = S.stage;
  b.textContent = S.exported ? "Export" : s.phase === "export" ? `Export ${Math.round((s.progress ?? 0) * 100)}%` : "Export";
  b.title = S.exported ? "Download the export and its matte as one zip" : "Renders the export in the plate's format, then downloads it";
}

function setTool(t) {
  S.tool = t;
  $$(".tools [data-tool]").forEach((b) => b.classList.toggle("on", b.dataset.tool === t));
  $("#tool-name").textContent = NAME[t];
  $("#prompt").placeholder = HINT[t];
  render();
}

function setSize(v) {
  S.size = Math.max(4, Math.min(320, Math.round(v)));
  $("#size").value = S.size;
  $("#size-out").textContent = S.size;
  render();
}

function openDialog() { $("#files").value = ""; $("#open").showModal(); }

async function boot() {
  for (const name of ["ingest", "edit", "snap", "shot", "matte", "comp", "export"]) WF[name] = parse(await (await fetch(`workflows/${name}.json`)).json());
  connect();
  const info = async (cls) => (await (await fetch(`/object_info/${cls}`)).json())[cls];
  const src = (await info("ImageColorSpace"))?.input.required.source ?? [["sRGB"]];
  const spaces = Array.isArray(src[0]) ? src[0] : src[1]?.options ?? ["sRGB"]; // V1 or V3 combo
  $("#cs").replaceChildren(...spaces.map((s) => new Option(s, s)));
  const needs = { PaintAPlate_LoadPlate: "this pack", LTXAddVideoICLoRAGuide: "ComfyUI-LTXVideo", SAM3_VideoTrack: "ComfyUI 0.42 or newer", ReferenceMultiLatent: "ComfyUI 0.41 or newer" };
  const missing = [];
  for (const [cls, from] of Object.entries(needs)) if (!(await info(cls))) missing.push(`${cls} (${from})`);
  if (missing.length) return status(`Missing nodes: ${missing.join(", ")}. Install them, then reload this page.`);
  const models = new Map(); // every model file the workflows load, by loader and input
  for (const wf of Object.values(WF)) for (const n of Object.values(wf.prompt))
    for (const [k, v] of Object.entries(n.inputs)) if (typeof v === "string" && v.endsWith(".safetensors")) models.set(v, [n.class_type, k]);
  const absent = [];
  for (const [file, [cls, input]] of models) {
    const spec = (await info(cls))?.input.required[input];
    const options = Array.isArray(spec?.[0]) ? spec[0] : spec?.[1]?.options ?? [];
    if (!options.includes(file)) absent.push(file);
  }
  status(absent.length ? `Missing model files: ${absent.join(", ")}. See the README for where to put them.` : "Ready. Open a plate to start.");
}

$$(".tools [data-tool]").forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
$("#size").oninput = (e) => setSize(+e.target.value);
$("#color").oninput = (e) => (S.color = e.target.value);
$("#whole").onchange = () => setTool("erase");
$("#prompt").oninput = () => { if (S.draft && !stroke) schedule(); };
$("#open-btn").onclick = $("#empty-open").onclick = openDialog;
$("#help-btn").onclick = () => $("#help").showModal();
$("#play-btn").onclick = () => (S.playing ? pause() : play());
$("#wipe-btn").onclick = () => setWipe(S.wipe === null);
$("#export-btn").onclick = () => {
  if (S.exported && !S.shotDirty && S.renders.get(S.heroKey)?.exported === S.exported) return download();
  S.wantDownload = true;
  status("The download starts when the export is ready.");
  touch();
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
new ResizeObserver(fitView).observe($("#viewport"));

setTool("paint");
setSize(48);
boot().catch(quiet);
