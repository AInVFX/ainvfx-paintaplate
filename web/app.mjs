// AInVFX PaintAPlate: paint on the first frame, pick an option, get the shot back in the plate's format.
// The page runs on the ComfyUI server that serves it. Every step is a workflow from ./workflows.

const $ = (q) => document.querySelector(q);
const $$ = (q) => [...document.querySelectorAll(q)];
const CLIENT = crypto.randomUUID();
const WF = {};
const live = new Set(); // jobs not finished yet
const byId = new Map(); // prompt id -> job, for WebSocket messages
const early = new Map(); // results that arrived before /prompt answered
let running = null; // the prompt ComfyUI is executing now
const TOOLS = { b: "paint", e: "erase", l: "light", r: "restore" };
const PLACEHOLDER = {
  paint: "What did you paint? A fire, a wooden desk, a splashing wave",
  erase: "Erase needs no words: paint over what should go",
  light: "Optional: describe the light. Warm sunset, neon sign, torch",
  restore: "Restore brings back the plate under the brush",
};
const Q = new URLSearchParams(location.search);
const REFINE_STEPS = +Q.get("refine") || 8; // full-size steps after a pick; previews use 8 at preview size
const S = { plate: null, cursor: null, hero: null, original: null, heroVersion: 0, heroInputs: {}, stack: [], edit: null,
  tool: "paint", size: 48, color: "#f5b800", run: 0, shot: null, shotDirty: false, compare: false };

const view = $("#view"), ctx = view.getContext("2d"), player = $("#player");
const paint = document.createElement("canvas"), mask = document.createElement("canvas");

// ---------- ComfyUI ----------

const post = (path, body) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

async function upload(blob, name) {
  const form = new FormData();
  form.append("image", blob, name);
  form.append("subfolder", `paintaplate/${S.plate.id}`);
  form.append("overwrite", "true");
  const r = await fetch("/upload/image", { method: "POST", body: form });
  if (!r.ok) throw new Error(`Upload failed: ${name}`);
  const j = await r.json();
  return j.subfolder ? `${j.subfolder}/${j.name}` : j.name;
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
  // A prompt served entirely from ComfyUI's cache reports no outputs: reuse those of the identical prompt before.
  if (files(out).length || texts(out).length) memo.set(job.key, out);
  else out = memo.get(job.key) ?? out;
  if (memo.size > 64) memo.delete(memo.keys().next().value);
  job.resolve(out);
}
const memo = new Map(); // prompt -> outputs

function drop(job) { // interrupt only the prompt that is running; anything queued is simply removed
  if (job.id && job.id === running) post("/interrupt", { prompt_id: job.id });
  else if (job.id) post("/queue", { delete: [job.id] });
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
  ws.onopen = () => ws.send(JSON.stringify({ type: "feature_flags", data: { supports_preview_metadata: true } }));
  ws.onclose = () => setTimeout(connect, 1000);
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
    if (type === "execution_start") { running = d.prompt_id; byId.get(d.prompt_id)?.progress?.(0); } // the status moves as soon as a job starts
    else if (type === "progress") byId.get(d.prompt_id)?.progress?.(d.value / d.max);
    else if (type === "execution_success") finish(d.prompt_id);
    else if (type === "execution_error") finish(d.prompt_id, `${d.node_type}: ${d.exception_message}`);
    else if (type === "execution_interrupted") finish(d.prompt_id, "cancelled");
  };
}

const files = (out) => Object.values(out).flatMap((o) => [...(o.images ?? []), ...(o.gifs ?? []), ...(o.video ?? [])]);
const texts = (out) => Object.values(out).flatMap((o) => o.text ?? []);
const url = (f) => `/view?${new URLSearchParams({ filename: f.filename, subfolder: f.subfolder, type: f.type })}`;
const asInput = (f) => `${f.subfolder ? `${f.subfolder}/` : ""}${f.filename} [${f.type}]`;
const isVideo = (f) => /\.(mp4|webm|mov)$/i.test(f.filename);
const quiet = (e) => e?.message !== "cancelled" && status(e?.message ?? String(e));

// ---------- Images ----------

const canvas = ([w, h]) => Object.assign(document.createElement("canvas"), { width: w, height: h });
const blob = (c) => new Promise((r) => c.toBlob(r, "image/png"));
const fit = (w, h, long, step) => [w, h].map((v) => Math.max(step, Math.round((v * long) / Math.max(w, h) / step) * step));
const loadImage = (src) => new Promise((res, rej) => Object.assign(new Image(), { onload() { res(this); }, onerror: rej, src }));

function snap(src, size, fill) {
  const c = canvas(size), x = c.getContext("2d");
  if (fill) { x.fillStyle = fill; x.fillRect(0, 0, c.width, c.height); }
  if (src) x.drawImage(src, 0, 0, c.width, c.height);
  return c;
}

const maskAt = (size, full) => (full ? snap(null, size, "#fff") : snap(mask, size, "#000"));

function overlay(size) {
  const c = snap(S.hero, size);
  c.getContext("2d").drawImage(paint, 0, 0, c.width, c.height);
  return c;
}

function fillHole(size) { // push-pull: the erased area takes coarser and coarser averages of its surroundings
  let level = snap(S.hero, size);
  const cut = level.getContext("2d");
  cut.globalCompositeOperation = "destination-out";
  cut.drawImage(mask, 0, 0, size[0], size[1]);
  const pyramid = [level];
  while (Math.min(level.width, level.height) > 8) pyramid.push(level = snap(level, [Math.ceil(level.width / 2), Math.ceil(level.height / 2)]));
  pyramid.push(snap(level, [level.width, level.height], "#808080")); // an opaque base under the coarsest level
  for (let i = pyramid.length - 2; i >= 0; i--) {
    const x = pyramid[i].getContext("2d");
    x.globalCompositeOperation = "destination-over";
    x.drawImage(pyramid[i + 1], 0, 0, pyramid[i].width, pyramid[i].height);
  }
  return pyramid[0];
}

const editImage = (e, size) => (e.tool === "erase" ? fillHole(size) : overlay(size)); // what Klein sees

function heroInput(size) {
  const key = `${S.heroVersion}:${size}`;
  return (S.heroInputs[key] ??= blob(snap(S.hero, size)).then((b) => upload(b, `hero_${key.replace(/\W/g, "_")}.png`)));
}

function bounds() { // painted area as FLUX 3 box coordinates: [y_min, x_min, y_max, x_max] on 0..1000
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

function caption(e) { // the same text and table FLUX 3 Image Layout Prompt writes, built here per stroke
  const words = e.prompt?.trim();
  const text = {
    erase: "Fill the blurred patch inside <obj_1> with the background that continues around it, with matching detail, light and focus. Add no new object. Keep everything else unchanged.",
    paint: `Replace the rough coloured drawing inside <obj_1> with ${words || "a realistic object of that shape and colour"}, in exactly the same style, lighting, perspective and grain as the rest of the image. Keep everything else unchanged.`,
    light: `Relight the whole scene with ${words || `${colorName(e.strokes.find((s) => !dark(s.color))?.color ?? e.color)} light`} coming from <obj_1>, with physically consistent shadows and reflections.${e.strokes.some((s) => dark(s.color)) ? " Dark strokes are hints of where shadows fall: make every shadow agree with the light." : ""} Keep the content, framing and textures unchanged.`,
  }[e.tool];
  const desc = { erase: "area to clean", paint: words || "the drawn object", light: "light source" }[e.tool];
  return `${text} ${JSON.stringify([{ id: "obj_1", bbox: bounds(), desc }])}`;
}

// ---------- Plate ----------

async function openPlate(list, typed, cs) {
  S.plate = { id: Date.now().toString(36) };
  let path = typed;
  if (list.length) {
    for (const [i, f] of list.entries()) { status(`Uploading ${i + 1} of ${list.length}`); await upload(f, f.name); }
    path = list.length === 1 ? `paintaplate/${S.plate.id}/${list[0].name}` : `paintaplate/${S.plate.id}`;
  }
  status("Reading the plate");
  const out = await run("ingest", { path, color_space: cs, prefix: `paintaplate/${S.plate.id}/hero`,
    video_prefix: `paintaplate/${S.plate.id}/proxy` }).done;
  const spec = JSON.parse(texts(out)[0]);
  const all = files(out);
  const long = Math.max(spec.width, spec.height), size = (cap, step) => fit(spec.width, spec.height, Math.min(cap, long), step);
  Object.assign(S.plate, { path, cs, spec, frames: spec.frames, work: size(1920, 64), prev: size(768, 16), shotSize: size(960, 32) });
  if (new URLSearchParams(location.search).get("shot") === "full") S.plate.shotSize = S.plate.work;
  S.original = snap(await loadImage(url(all.find((f) => !isVideo(f)))), S.plate.work);
  Object.assign(S, { hero: S.original, heroVersion: 0, heroInputs: {}, stack: [], edit: null, shot: null });
  for (const c of [view, paint, mask]) [c.width, c.height] = S.plate.work;
  fitView();
  player.src = url(all.find(isVideo));
  $("#empty").hidden = true;
  $("#view-shot").disabled = $("#export-btn").disabled = true;
  showView("paint");
  stackUI(); tiles(); render();
  const kind = spec.kind === "video" ? spec.codec : `${spec.ext.slice(1).toUpperCase()} ${spec.kind}`;
  $("#spec").textContent = `${kind}, ${spec.width} × ${spec.height}, ${Math.round(spec.fps * 1000) / 1000} fps, ${spec.frames} frames, ${cs}`;
  const offered = [...$("#cs").options].some((o) => o.value === spec.color_space_guess);
  warm();
  status(spec.color_space_guess === cs ? "Paint on the frame"
    : offered ? `The file suggests ${spec.color_space_guess}. Reopen with it if colours look wrong.`
    : `The file suggests ${spec.color_space_guess}, which this ComfyUI does not offer yet: update ComfyUI past v0.42.5.`);
}

async function warm() { // load the image model while the user looks at the frame, so the first stroke is quick
  const size = S.plate.prev, base = await heroInput(size);
  const mask = await upload(await blob(snap(null, size, "#000")), "warm_mask.png");
  run("edit", { base, reference: base, start: base, mask, caption: "warm up", seed: 0, steps: 1, denoise: 1,
    grow: 0, feather: 1, sigma: 1 }, { kind: "warm" }).done.catch(() => {});
}

// ---------- Painting ----------

let stroke = null;

view.addEventListener("pointerdown", (e) => {
  if (!S.hero || !$("#player").hidden) return;
  if (S.tool === "restore" ? !S.edit : S.edit && S.edit.tool !== S.tool)
    return status(S.edit ? `Finish this ${S.edit.tool} edit first: pick an option, or press Esc.` : "Nothing to restore yet.");
  if (!S.edit && S.stack.length >= 3) return status("Three edits is the limit for now. Remove one to add another.");
  if (!S.edit) { cancel("shot", "matte", "export"); S.shotDirty = S.stack.length > 0; } // the GPU goes to the new edit
  S.edit ??= { tool: S.tool, color: S.color, prompt: $("#prompt").value, seed: (Math.random() * 2 ** 31) | 0, strokes: [], options: [null, null], refined: [null, null] };
  view.setPointerCapture(e.pointerId);
  stroke = { tool: S.tool, color: S.color, size: S.size, points: [] };
  S.edit.strokes.push(stroke);
  addPoint(e);
});
view.addEventListener("pointermove", (e) => {
  if (stroke) return addPoint(e);
  const r = view.getBoundingClientRect();
  S.cursor = [((e.clientX - r.left) * view.width) / r.width, ((e.clientY - r.top) * view.height) / r.height];
  requestAnimationFrame(render);
});
view.addEventListener("pointerleave", () => { S.cursor = null; requestAnimationFrame(render); });
view.addEventListener("pointerup", () => { if (stroke) { stroke = null; schedulePreview(); } });

function addPoint(e) {
  const r = view.getBoundingClientRect();
  stroke.points.push([((e.clientX - r.left) * view.width) / r.width, ((e.clientY - r.top) * view.height) / r.height, e.pressure || 0.5]);
  draw(stroke, stroke.points.length - 1);
  render();
}

function draw(s, from = 0) {
  const pc = paint.getContext("2d"), mc = mask.getContext("2d");
  for (let i = from; i < s.points.length; i++) {
    const [x, y, p] = s.points[i], [px, py] = s.points[Math.max(i - 1, 0)], r = (s.size * (0.5 + p)) / 2;
    if (s.tool === "restore") { erase(pc, px, py, x, y, r); erase(mc, px, py, x, y, r); continue; }
    line(mc, px, py, x, y, r, "#fff");
    if (s.tool === "paint") line(pc, px, py, x, y, r, s.color);
    if (s.tool === "light") dark(s.color) ? line(pc, px, py, x, y, r, "#000000a0") : glow(pc, x, y, r * 2.5, s.color);
  }
}

function line(c, x0, y0, x1, y1, r, color) {
  Object.assign(c, { strokeStyle: color, lineWidth: 2 * r, lineCap: "round", lineJoin: "round" });
  c.beginPath(); c.moveTo(x0, y0); c.lineTo(x1, y1); c.stroke();
}

function erase(c, ...args) {
  c.globalCompositeOperation = "destination-out";
  line(c, ...args, "#000");
  c.globalCompositeOperation = "source-over";
}

function glow(c, x, y, r, color) {
  const g = c.createRadialGradient(x, y, 0, x, y, r);
  g.addColorStop(0, `${color}cc`); g.addColorStop(1, `${color}00`);
  c.globalCompositeOperation = "lighter"; c.fillStyle = g; c.fillRect(x - r, y - r, 2 * r, 2 * r);
  c.globalCompositeOperation = "source-over";
}

function redraw() {
  for (const c of [paint, mask]) c.getContext("2d").clearRect(0, 0, c.width, c.height);
  for (const s of S.edit?.strokes ?? []) draw(s);
}

const tint = document.createElement("canvas");
function render() {
  if (!S.hero) return;
  ctx.globalAlpha = 1;
  ctx.drawImage(S.compare ? S.original : S.hero, 0, 0);
  if (!S.edit || S.compare) return drawCursor();
  if (S.edit.tool === "erase") { // show the area to clean in red
    [tint.width, tint.height] = [mask.width, mask.height];
    const t = tint.getContext("2d");
    t.drawImage(mask, 0, 0); t.globalCompositeOperation = "source-in"; t.fillStyle = "#ff5040"; t.fillRect(0, 0, tint.width, tint.height);
    ctx.globalAlpha = 0.45; ctx.drawImage(tint, 0, 0);
  } else { ctx.globalAlpha = 0.9; ctx.drawImage(paint, 0, 0); }
  ctx.globalAlpha = 1;
  drawCursor();
}

function drawCursor() { // the brush outline, at its real size on the frame
  if (!S.cursor || stroke) return;
  ctx.lineWidth = Math.max(1.5, view.width / 900);
  ctx.strokeStyle = S.tool === "restore" ? "#ffffff" : S.color;
  ctx.beginPath(); ctx.arc(S.cursor[0], S.cursor[1], S.size / 2, 0, 2 * Math.PI); ctx.stroke();
}

// ---------- Options: two seeds, live ----------

let previewTimer;
function schedulePreview(delay = 120) { clearTimeout(previewTimer); previewTimer = setTimeout(() => previews().catch(quiet), delay); touch(); }

async function previews() {
  const e = S.edit;
  if (!e?.strokes.length) return;
  cancel("preview", "spec");
  const gen = (e.gen = (e.gen ?? 0) + 1); // results from an older stroke are ignored
  e.options = [null, null]; e.refined = [null, null];
  tiles();
  const size = S.plate.prev, light = e.tool === "light";
  if (e.tool === "erase" && $("#whole").checked && e.snapped !== e.strokes.length) {
    e.snapped = e.strokes.length;
    await snapErase(e, size, gen);
    if (gen !== e.gen) return;
  }
  const base = await heroInput(size);
  const reference = await upload(await blob(editImage(e, size)), "reference.png");
  const values = { base, reference, start: light ? base : reference, caption: caption(e), steps: 8,
    mask: await upload(await blob(maskAt(size, light)), "mask.png"), denoise: light ? 0.65 : 1,
    grow: Math.round(size[0] / 48), feather: 6, sigma: 3 };
  status("Previewing");
  await Promise.all([0, 1].map((i) => run("edit", { ...values, seed: e.seed + i },
    { kind: "preview", front: true, preview: (b) => gen === e.gen && tile(i, URL.createObjectURL(b)) }).done.then((out) => {
    if (gen !== e.gen) return;
    e.options[i] = files(out)[0];
    tile(i, url(e.options[i]), true);
  })));
  if (gen === e.gen) status("Pick an option: click it, or press 1 or 2");
  touch();
}

async function snapErase(e, size, gen) { // SAM 3.1 grows the latest erase stroke to the whole object under it
  const pts = e.strokes.at(-1).points, k = size[0] / view.width;
  const picks = [...new Set([0, 0.25, 0.5, 0.75, 1].map((f) => Math.round(f * (pts.length - 1))))]; // up to five points along the stroke
  const points = picks.map((i) => ({ x: Math.round(pts[i][0] * k), y: Math.round(pts[i][1] * k) }));
  status("Finding the object under the stroke");
  const out = await run("snap", { image: await heroInput(size), points: JSON.stringify(points) }, { kind: "snap" }).done;
  if (gen !== e.gen) return;
  const pixels = (c) => c.getContext("2d").getImageData(0, 0, size[0], size[1]).data;
  const sam = snap(await loadImage(url(files(out)[0])), size), s = pixels(sam), m = pixels(maskAt(size));
  let area = 0, painted = 0, both = 0;
  for (let i = 0; i < s.length; i += 4) {
    if (m[i] > 127) painted++;
    if (s[i] > 127) { area++; if (m[i] > 127) both++; }
  }
  // accept one object that holds the stroke: not a whole wall or shopfront grown from a small stroke
  if (!area || area > 0.12 * size[0] * size[1] || area > 40 * painted || both < 0.5 * painted)
    return status("Erasing only what you painted: no single object under the stroke.");
  const d = sam.getContext("2d"), img = d.getImageData(0, 0, size[0], size[1]);
  for (let i = 0; i < img.data.length; i += 4) { img.data[i + 3] = img.data[i]; img.data[i] = img.data[i + 1] = img.data[i + 2] = 255; }
  d.putImageData(img, 0, 0);
  mask.getContext("2d").drawImage(sam, 0, 0, mask.width, mask.height); // the object joins the erase mask, at working size
  render();
}

function tiles() { $$(".option").forEach((b) => { b.className = "option"; b.querySelector("img").removeAttribute("src"); }); }
function tile(i, src, ready) { const b = $$(".option")[i]; b.querySelector("img").src = src; b.classList.toggle("ready", !!ready); }

async function refine(e, i, kind = "refine") { // the picked option at working size, same seed, light denoise
  const size = S.plate.work, light = e.tool === "light";
  const start = await upload(await blob(snap(await loadImage(url(e.options[i])), size)), `start_${i}.png`);
  const base = await heroInput(size);
  const out = await run("edit", { base, start, caption: caption(e), seed: e.seed + i, steps: REFINE_STEPS, denoise: 0.35,
    reference: await upload(await blob(editImage(e, size)), "reference_full.png"),
    mask: await upload(await blob(maskAt(size, light)), "mask_full.png"),
    grow: Math.round(size[0] / 48), feather: 12, sigma: 6 }, { kind }).done;
  return files(out)[0];
}

async function pick(i) {
  const e = S.edit;
  if (!e?.options[i]) return;
  $$(".option").forEach((b, j) => b.classList.toggle("picked", i === j));
  cancel("preview");
  status(`Refining option ${i + 1}`);
  try {
    const f = await (e.refined[i] ??= refine(e, i)).catch(() => (e.refined[i] = refine(e, i)));
    await commit(e, f);
  } catch (err) { quiet(err); }
}

async function commit(e, f) {
  const before = S.hero;
  S.hero = snap(await loadImage(url(f)), S.plate.work);
  S.heroVersion++;
  S.stack.push({ tool: e.tool, prompt: e.prompt, seed: e.seed, input: asInput(f), thumb: url(f), before,
    mask: e.tool === "light" ? null : maskAt(S.plate.shotSize) });
  S.edit = null;
  $("#prompt").value = "";
  redraw(); tiles(); stackUI(); render();
  S.shotDirty = true;
  status("Edit added. The shot renders when you pause.");
  touch();
}

function discard() { cancel("preview", "spec"); S.edit = null; redraw(); tiles(); render(); status("Edit discarded"); }

function stackUI() {
  $("#stack").replaceChildren(...S.stack.map((e, i) => {
    const li = document.createElement("li");
    li.innerHTML = "<img alt=''><div><span></span><small></small></div>";
    li.querySelector("img").src = e.thumb;
    li.querySelector("span").textContent = { paint: "Paint", erase: "Erase", light: "Light" }[e.tool];
    li.querySelector("small").textContent = e.prompt || "No words";
    if (i === S.stack.length - 1) {
      const b = Object.assign(document.createElement("button"), { textContent: "Remove", title: "Remove the last edit" });
      b.onclick = () => { S.hero = S.stack.pop().before; S.heroVersion++; S.shotDirty = S.stack.length > 0; stackUI(); render(); touch(); };
      li.append(b);
    }
    return li;
  }));
}

// ---------- Idle time: refine both options, then the shot, mattes and export ----------

let idleTimer;
function touch() { clearTimeout(idleTimer); idleTimer = setTimeout(idle, 1500); }

function idle() {
  const e = S.edit;
  if (e?.options.every(Boolean)) {
    e.options.forEach((_, i) => {
      if (e.refined[i]) return;
      const p = (e.refined[i] = refine(e, i, "spec"));
      p.catch(() => { if (e.refined[i] === p) e.refined[i] = null; });
    });
  } else if (!e && S.shotDirty && S.stack.length) shot().catch(quiet);
}

async function shot() { // half size to watch soon, then full size for the export, both in idle time
  S.shotDirty = false;
  cancel("shot", "matte", "export");
  const p = S.plate, base = `paintaplate/${p.id}/v${++S.run}`, [width, height] = p.shotSize;
  const common = { path: p.path, color_space: p.cs, max_frames: p.frames, hero: S.stack.at(-1).input, seed: S.stack[0].seed };
  const pct = (label) => (f) => status(`${label}, ${Math.round(f * 100)}%`);
  const watch = (out) => {
    player.src = S.shot = url(files(out).find(isVideo));
    $("#view-shot").disabled = false;
    $("#view-shot").classList.toggle("new", player.hidden);
  };
  watch(await run("shot", { ...common, width, height, prefix: `${base}/shot/f`, video_prefix: `${base}/preview` },
    { kind: "shot", progress: pct("Rendering the shot preview") }).done);
  let final = `output:${base}/shot`;
  if (width !== p.work[0]) {
    status("Shot preview ready: click Shot to watch it. The full-size shot renders next.");
    watch(await run("shot", { ...common, width: p.work[0], height: p.work[1], prefix: `${base}/full/f`, video_prefix: `${base}/full` },
      { kind: "shot", progress: pct("Rendering the shot at full size") }).done);
    final = `output:${base}/full`;
  }
  const mattes = {};
  for (const [key, tool, path, cs, label] of [["matte_a", "erase", p.path, p.cs, "Tracking the erased areas"],
    ["matte_b", "paint", final, "sRGB", "Tracking the new elements"]]) {
    const edits = S.stack.filter((e) => e.tool === tool);
    if (!edits.length) continue;
    const union = canvas(p.shotSize), u = union.getContext("2d");
    u.globalCompositeOperation = "lighten";
    for (const e of edits) u.drawImage(e.mask, 0, 0);
    await run("matte", { path, color_space: cs, max_frames: p.frames, width, height, prefix: `${base}/${key}/m`,
      mask: await upload(await blob(union), `${key}.png`) }, { kind: "matte", progress: pct(label) }).done;
    mattes[key] = `output:${base}/${key}`;
  }
  const relight = S.stack.some((e) => e.tool === "light");
  const a = mattes.matte_a ?? mattes.matte_b, b = mattes.matte_b ?? mattes.matte_a;
  const done = await run("export", { path: p.path, color_space: p.cs, max_frames: p.frames, shot: final, matte_a: a ?? "",
    matte_b: b ?? "", relight, keep_untouched: !relight, prefix: `${base}/export` }, { kind: "export",
    progress: pct("Exporting at full quality"), edit: (wf) => { if (!a) dropMattes(wf); } }).done;
  S.exported = texts(done)[0] ?? "";
  $("#export-btn").disabled = false;
  status(`Exported: ${S.exported.split("\n")[0]}`);
}

function dropMattes(wf) { // relight only: no matte, so nothing to composite
  for (const [id, input] of wf.slots.fit_mask) delete wf.prompt[id].inputs[input];
  const gone = new Set([...wf.slots.matte_a, ...wf.slots.matte_b].map(([id]) => id));
  for (let grew = true; grew;) {
    grew = false;
    for (const [id, node] of Object.entries(wf.prompt)) {
      if (gone.has(id) || !Object.values(node.inputs).some((v) => Array.isArray(v) && gone.has(String(v[0])))) continue;
      gone.add(id); grew = true;
    }
  }
  for (const id of gone) delete wf.prompt[id];
}

// ---------- Interface ----------

function status(text) { $("#status").textContent = text; }

function fitView() { // the frame fills the stage at any plate size; pointer maths stays 1:1 with the element box
  if (!S.plate) return;
  const stage = $(".stage").getBoundingClientRect(), [w, h] = S.plate.work;
  const k = Math.min((stage.width - 32) / w, (stage.height - 32) / h);
  for (const el of [view, player]) Object.assign(el.style, { width: `${Math.floor(w * k)}px`, height: `${Math.floor(h * k)}px` });
}
addEventListener("resize", fitView);

function setTool(t) {
  S.tool = t;
  $$(".tools [data-tool]").forEach((b) => b.classList.toggle("on", b.dataset.tool === t));
  $("#prompt").placeholder = PLACEHOLDER[t];
  $("#whole-wrap").hidden = t !== "erase";
}

function showView(v) {
  if (v === "shot") $("#view-shot").classList.remove("new");
  $("#view-paint").classList.toggle("on", v === "paint");
  $("#view-shot").classList.toggle("on", v === "shot");
  player.hidden = v !== "shot";
  view.hidden = v === "shot";
  if (v === "shot") player.play(); else player.pause();
}

function openDialog() { $("#files").value = ""; $("#open").showModal(); }

async function boot() {
  for (const name of ["ingest", "edit", "snap", "shot", "matte", "export"]) WF[name] = await (await fetch(`workflows/${name}.json`)).json();
  connect();
  const info = async (cls) => (await (await fetch(`/object_info/${cls}`)).json())[cls];
  const src = (await info("ImageColorSpace"))?.input.required.source ?? [["sRGB"]];
  const spaces = Array.isArray(src[0]) ? src[0] : src[1]?.options ?? ["sRGB"]; // V1 or V3 combo
  $("#cs").replaceChildren(...spaces.map((s) => new Option(s, s)));
  const needs = { PaintAPlate_LoadPlate: "this pack", LTXAddVideoICLoRAGuide: "ComfyUI-LTXVideo", SAM3_VideoTrack: "ComfyUI 0.42 or newer", ReferenceMultiLatent: "ComfyUI 0.41 or newer" };
  const missing = [];
  for (const [cls, from] of Object.entries(needs)) if (!(await info(cls))) missing.push(`${cls} (${from})`);
  if (missing.length) return status(`Missing nodes: ${missing.join(", ")}. Install them, then reload this page.`);
  const files = new Map(); // every model file the workflows load, by loader and input
  for (const wf of Object.values(WF)) for (const n of Object.values(wf.prompt))
    for (const [k, v] of Object.entries(n.inputs)) if (typeof v === "string" && v.endsWith(".safetensors")) files.set(v, [n.class_type, k]);
  const absent = [];
  for (const [file, [cls, input]] of files) {
    const spec = (await info(cls))?.input.required[input];
    const options = Array.isArray(spec?.[0]) ? spec[0] : spec?.[1]?.options ?? [];
    if (!options.includes(file)) absent.push(file);
  }
  status(absent.length ? `Missing model files: ${absent.join(", ")}. See the README for where to put them.` : "Ready. Open a plate to start.");
}

$$(".tools [data-tool]").forEach((b) => (b.onclick = () => setTool(b.dataset.tool)));
$("#size").oninput = (e) => (S.size = +e.target.value);
$("#color").oninput = (e) => (S.color = e.target.value);
$("#prompt").oninput = (e) => { if (S.edit) { S.edit.prompt = e.target.value; schedulePreview(450); } };
$$(".option").forEach((b) => (b.onclick = () => pick(+b.dataset.i)));
$("#reroll").onclick = () => { if (S.edit) { S.edit.seed += 2; schedulePreview(0); } };
$("#open-btn").onclick = $("#empty-open").onclick = openDialog;
$("#files").onchange = (e) => { const ext = e.target.files[0]?.name.split(".").pop().toLowerCase(); $("#cs").value = ext === "exr" ? "linear" : "sRGB"; };
$("#open-go").onclick = () => openPlate([...$("#files").files], $("#path").value.trim(), $("#cs").value).catch(quiet);
$("#view-paint").onclick = () => showView("paint");
$("#view-shot").onclick = () => showView("shot");
$("#export-btn").onclick = () => status(S.exported ? `Exported: ${S.exported.replace(/\n/g, ", ")}` : "Export runs after the shot");
document.addEventListener("dragover", (e) => e.preventDefault());
document.addEventListener("drop", (e) => {
  e.preventDefault();
  const list = [...e.dataTransfer.files];
  if (list.length) openPlate(list, "", /\.exr$/i.test(list[0].name) ? "linear" : "sRGB").catch(quiet);
});

addEventListener("keydown", (e) => {
  if (e.target.matches("input, select") && !["Enter", "Escape"].includes(e.key)) return;
  const k = e.key.toLowerCase();
  if (TOOLS[k] && !e.ctrlKey && !e.metaKey) setTool(TOOLS[k]);
  else if (k === "[" || k === "]") $("#size").value = S.size = Math.round(S.size * (k === "]" ? 1.2 : 1 / 1.2));
  else if (k === "1" || k === "2") pick(+k - 1);
  else if (k === "enter") $("#reroll").click();
  else if (k === "escape") discard();
  else if (k === "o") { S.compare = true; render(); }
  else if (k === "?" || (k === "/" && e.shiftKey)) $("#help").open ? $("#help").close() : $("#help").show();
  else if (k === "z" && (e.ctrlKey || e.metaKey) && S.edit) { S.edit.strokes.pop(); redraw(); render(); S.edit.strokes.length ? schedulePreview() : discard(); }
  else if (k === " " && !player.hidden) player.paused ? player.play() : player.pause();
  else return;
  e.preventDefault();
});
addEventListener("keyup", (e) => { if (e.key.toLowerCase() === "o") { S.compare = false; render(); } });

setTool("paint");
boot().catch(quiet);
