// Pure functions of the page: workflows as data, sizes, captions, time, edit dependencies, the frame cache's ranking.
// No DOM and no state here, so tests/js runs every one of them in Node (node --test).

// ---------- Workflows as data ----------

// Optional links: when every source slot is left empty, the link goes, with every node that fed it. The same rule as
// tools/build_workflows.py (OPTIONAL there; a test checks they match): a relight alone has
// no matte to composite with, nor to save (the export's "matte" output goes with it).
export const OPTIONAL = { fit_mask: ["matte_a", "matte_b"], named: ["words"], relit_frame: ["relight"] };

export function parseWorkflow(prompt) { // slots, outputs and the progress node, from each node's _meta
  const slots = {}, outputs = {}, progress = new Set();
  for (const [id, node] of Object.entries(prompt)) {
    for (const [input, name] of Object.entries(node._meta?.slots ?? {})) (slots[name] ??= []).push([id, input]);
    if (node._meta?.output) outputs[node._meta.output] = id;
    if (node._meta?.progress) progress.add(id);
  }
  return { prompt, slots, outputs, progress };
}

export function fillWorkflow(wf, values) { // a copy with the slots set and the unused optional links dropped
  const out = structuredClone(wf);
  for (const [slot, value] of Object.entries(values))
    for (const [id, input] of out.slots[slot] ?? []) out.prompt[id].inputs[input] = value;
  for (const [link, sources] of Object.entries(OPTIONAL))
    if (out.slots[link] && !sources.some((s) => values[s])) dropLink(out, link, sources, link === "fit_mask" ? out.outputs.matte : null);
  return out;
}

export function dropLink(wf, link, sources, extra) { // cut the input `link` names, and every node that only fed it
  for (const [id, input] of wf.slots[link] ?? []) delete wf.prompt[id].inputs[input];
  const gone = new Set(sources.flatMap((k) => (wf.slots[k] ?? []).map(([id]) => id)));
  if (extra) gone.add(extra);
  for (let grew = true; grew;) {
    grew = false;
    for (const [id, node] of Object.entries(wf.prompt)) {
      if (gone.has(id) || !Object.values(node.inputs).some((v) => Array.isArray(v) && gone.has(String(v[0])))) continue;
      gone.add(id); grew = true;
    }
  }
  for (const id of gone) delete wf.prompt[id];
}

// ---------- Sizes and time ----------

// Multiples of `step` (what the models need) that keep the plate's aspect within `tol` (1.5%), as large as `cap` allows.
export function fitSize(w, h, cap, step, tol = 0.015) {
  const long = Math.max(w, h), short = Math.min(w, h), aspect = long / short;
  const top = Math.max(step, Math.floor(Math.min(cap, long) / step) * step);
  let best = null;
  for (let L = top; L >= Math.max(step, top * 0.75); L -= step) {
    const s = Math.max(step, Math.round((short * L) / long / step) * step), err = Math.abs(L / s - aspect) / aspect;
    if (!best || err < best.err) best = { L, s, err };
    if (err <= tol) { best = { L, s, err }; break; }
  }
  return w >= h ? [best.L, best.s] : [best.s, best.L];
}

// ---------- Preview sizes: from the plate's own size, never a fixed list ----------
// The shot preview at `cap` on its long side, for a plate of native size `plate` edited at working size `work` (its
// multiples-of-32 size, 1920 at most): an exact half, third or quarter of the working size when one sits within 12.5%
// under the cap and keeps the plate's aspect (it divides the working pixels evenly), else the largest multiples of `step`
// under the cap within `tol` of the plate's aspect (2.5%: a preview is for looking; the export never depends on it).
// A cap at or above the working size is the working size itself: one pass, as the export.
export function previewSize(plate, work, cap, step = 32, tol = 0.025) {
  const [W, H] = work, long = Math.max(W, H), aspect = plate[0] / plate[1];
  if (cap >= long) return [W, H];
  for (const k of [2, 3, 4]) {
    const fits = W % (step * k) === 0 && H % (step * k) === 0 && long / k <= cap && long / k >= cap * 0.875;
    if (fits && Math.abs(W / H - aspect) / aspect <= tol) return [W / k, H / k];
  }
  return fitSize(plate[0], plate[1], cap, step, tol);
}

export const PREVIEW_CAPS = [["Standard", 960], ["Fast", 640], ["Draft", 448]];

// The Preview size menu for a plate: Full, then each cap below the working size, with the size it gives and the whole
// number it divides the working size by (0 when it does not divide it). Two caps that give one size are listed once.
export function previewSizes(plate, work, step = 32) {
  const long = Math.max(...work), out = [];
  for (const [label, cap] of [["Full", long], ...PREVIEW_CAPS.filter(([, c]) => c < long)]) {
    const size = previewSize(plate, work, cap, step), k = work[0] / size[0];
    if (out.some((o) => o.size[0] === size[0] && o.size[1] === size[1])) continue;
    out.push({ label, cap, size, div: Number.isInteger(k) && work[1] / size[1] === k ? k : 0 });
  }
  return out;
}

export const gb = (n) => (n > 1e9 ? `${(n / 1e9).toFixed(2)} GB` : `${Math.round(n / 1e6)} MB`);

export function secs(t) { // "about 40 s left", "about 1 min 40 s left": rounded to 10 s past a minute
  if (t == null || !isFinite(t)) return "";
  if (t < 60) return `about ${Math.max(1, Math.round(t))} s left`;
  const r = Math.round(t / 10) * 10, m = Math.floor(r / 60), s = r % 60;
  return m >= 10 || !s ? `about ${Math.round(t / 60)} min left` : `about ${m} min ${s} s left`;
}

// ---------- Captions: the text and table FLUX 3 Image Layout Prompt writes, per edit ----------

export const dark = (hex) => [1, 3, 5].reduce((a, i, k) => a + [0.2126, 0.7152, 0.0722][k] * parseInt(hex.slice(i, i + 2), 16), 0) < 60;

export function colorName(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b);
  if (max - min < 0.12) return max > 0.6 ? "white" : "soft grey";
  const h = (max === r ? (g - b) / (max - min) : max === g ? 2 + (b - r) / (max - min) : 4 + (r - g) / (max - min)) * 60;
  return ["red", "warm orange", "golden yellow", "green", "cyan", "cool blue", "violet", "magenta"][Math.floor(((h + 360 + 22) % 360) / 45)];
}

// tool: paint, erase or light; words: the prompt; colors: of the painted strokes; color: the tool's colour;
// bbox: [y_min, x_min, y_max, x_max] on 0..1000. Only the chosen tool's text is built.
export function caption({ tool, words, colors, color, bbox }) {
  const text = {
    erase: () => `Remove ${words ? `the ${words}` : "the object"} inside <obj_1> completely, with its shadow and its reflection. Show the surface and the background that continue behind it, with matching detail, light, shadows and focus. Add no new object. Keep everything else unchanged.`,
    paint: () => `Replace the rough coloured drawing inside <obj_1> with ${words || "a realistic object of that shape and colour"}, in exactly the same style, lighting, perspective and grain as the rest of the image. Keep everything else unchanged.`,
    light: () => `Relight the whole scene with ${words || `${colorName(colors.find((c) => !dark(c)) ?? color)} light`} coming from <obj_1>, with physically consistent shadows and reflections.${colors.some(dark) ? " Dark strokes are hints of where shadows fall: make every shadow agree with the light." : ""} Keep the content, framing and textures unchanged.`,
  }[tool]();
  const desc = { erase: words ? `${words} to remove` : "object to remove", paint: words || "the drawn object", light: "light source" }[tool];
  return `${text} ${JSON.stringify([{ id: "obj_1", bbox, desc }])}`;
}

// ---------- What FLUX 3 Image Klein's upsampler reads, and what the page keeps of its answer ----------
// Black Forest Labs' own format (src/flux3/pup.py and bbox.py): an erase or a paint edit is a request with one locked row
// in the table Klein was trained on; a relight is a plain request. Boxes are [y_min, x_min, y_max, x_max] on 0..1000.

const pyJSON = (v) => JSON.stringify(v).replace(/("(?:[^"\\]|\\.)*")|([,:])/g, (m, s, p) => s ?? `${p} `); // json.dumps spacing
export const KEEP_TOUCHED = " Where the drawing touches an object, the new element acts on that object itself (it burns it, rests on it, " +
  "wets it or lights it); add no props, fuel or supports that were not asked for."; // a fire on a towel came with logs without it

export function upsampleRequest({ tool, words, bbox }) {
  if (tool === "light") {
    const ask = `Relight the whole photograph: ${words || "warm light coming from the painted area"}. Keep every object, its position, shape, ` +
      "size and texture, the framing and the camera exactly as they are.";
    return { mode: "plain", locked: null,
      request: `Reference images follow in order (the first image, the second image, ...).\nUser request: ${ask}\nOutput the caption.` };
  }
  const row = tool === "erase"
    ? { id: "obj_1", from: "ref_image_0", src_bbox: bbox, tgt_bbox: null, desc: words || "the object to remove" }
    : { id: "obj_1", from: "target", src_bbox: null, tgt_bbox: bbox, desc: words || "a realistic object of the drawing's shape and colour" };
  const ask = tool === "erase"
    ? `Remove the ${words || "object"} <obj_1> completely, with its shadow and its reflection, and continue the background behind it.`
    : `Replace the rough coloured drawing at <obj_1> with ${words || "a realistic object of the same shape and colour"}, photographed in the ` +
      `same light, perspective, focus and grain as the scene, casting its own light and shadows on what is around it.${KEEP_TOUCHED}`;
  const instruction = `ORIGINAL PROMPT:\n${ask}\n\nLOCKED BOUNDING-BOX ANNOTATIONS ([y_min, x_min, y_max, x_max] on a 0-1000 canvas, with ` +
    "(0, 0) at the top-left). This is an authoritative JSON list of dictionaries; preserve every supplied identity, provenance value, " +
    `null, and coordinate exactly:\n${pyJSON([row])}`;
  return { mode: "table", locked: [row],
    request: `Reference images follow in attachment order: ref_image_0, ref_image_1, ...\nUser editing instruction: ${instruction}\n` +
      "Decide the edit, imagine the target image, and output the annotation record." };
}

export function splitTable(text) { // [caption, rows]: from the last "[" where the rest parses as a JSON list
  for (let i = text.length - 1; i >= 0; i--) {
    if (text[i] !== "[") continue;
    try { const rows = JSON.parse(text.slice(i)); if (Array.isArray(rows)) return [text.slice(0, i).trimEnd(), rows]; } catch { /* not yet */ }
  }
  return [text.trim(), null];
}

const ROW_ID = /^[A-Za-z][A-Za-z0-9_]*$/;
export function validBox(b) {
  if (!Array.isArray(b) || b.length !== 4 || b.some((v) => typeof v !== "number" || !Number.isFinite(v))) return null;
  const [y1, x1, y2, x2] = b;
  return y1 < 0 || x1 < 0 || y2 <= y1 || x2 <= x1 || y2 > 1000 || x2 > 1000 || Math.max(...b) <= 1 ? null : b;
}

function addedRow(row, caption) { // a row the upsampler added: kept when it is cited as <id> and well formed
  if (!row || typeof row !== "object" || !ROW_ID.test(row.id ?? "") || !caption.includes(`<${row.id}>`) || !String(row.desc ?? "").trim()) return null;
  const desc = row.desc.trim(), box = validBox(row.bbox);
  if (box) return { id: row.id, bbox: box, desc };
  const src = row.src_bbox == null ? null : validBox(row.src_bbox), tgt = row.tgt_bbox == null ? null : validBox(row.tgt_bbox);
  if (!/^(ref_image_\d+|target)$/.test(row.from ?? "") || (row.src_bbox != null && !src) || (row.tgt_bbox != null && !tgt) ||
    (!src && !tgt) || (row.from === "target") === !!src) return null;
  return { id: row.id, from: row.from, src_bbox: src, tgt_bbox: tgt, desc };
}

// The upsampler's answer with the page's own rows put back, as Black Forest Labs' reconcile(): each locked row verbatim with
// the upsampler's description of it, then the rows it added. A cut-off table leaves the caption and the locked rows.
export function reconcile(text, locked) {
  const [caption, rows] = splitTable(text);
  const byId = new Map((rows ?? []).filter((r) => r && typeof r.id === "string").map((r) => [r.id, r]));
  const out = locked.map((lock) => ({ ...lock, desc: String(byId.get(lock.id)?.desc ?? "").trim() || lock.desc }));
  for (const r of rows ?? []) { const a = addedRow(r, caption); if (a && !out.some((o) => o.id === a.id)) out.push(a); }
  return `${caption} ${pyJSON(out)}`;
}

// ---------- The shot's prompt ----------
export const RIPPLE = "Use the reference video for motion, timing, camera movement, framing and lighting changes; " +
  "follow the edited first frame for every change of content, light and style.";

// The Ripple sentence, then one line per paint or light edit (its card: a short description of the change helps; an explosion
// then stayed and grew instead of driving off with the car). An erase is never named: named, the umbrella came back.
export function shotPrompt(edits) {
  return [RIPPLE, ...edits.filter((e) => e.tool !== "erase" && e.words).map((e) => (e.tool === "paint"
    ? `Added in the first frame: ${e.words}; it keeps moving naturally and stays in place on what it touches for the whole shot.`
    : `The first frame is relit: ${e.words}; this new light holds for the whole shot.`))].join(" ");
}

// ---------- Whole object: which of SAM's masks belong to the erase ----------
// Masks are Uint8Arrays of 0 and 1 over `area` pixels. Found by name: the instances the stroke touches. Else one mask per stroke
// point: objects only (not the sky or the road), kept when two points agree (a point that slipped onto the road found a strip of
// it). A thin pole under a wide brush covers little of the stroke, so a touch counts from either side.
const count = (m) => { let n = 0; for (let i = 0; i < m.length; i++) n += m[i]; return n; };
const shared = (a, b) => { let n = 0; for (let i = 0; i < a.length; i++) n += a[i] & b[i]; return n; };
export function pickObjects({ painted, points, named, area }) {
  const strokeArea = count(painted);
  const touched = named.filter((m) => { const c = count(m), s = shared(m, painted); return c > 0 && c <= 0.5 * area && (s > 0.02 * c || s > 0.5 * strokeArea); });
  if (touched.length) return touched;
  const objects = points.filter((m) => { const c = count(m); return c > 0 && c <= 0.15 * area; });
  if (objects.length <= 1) return objects;
  const iou = (a, b) => { const s = shared(a, b); return s / Math.max(1, count(a) + count(b) - s); };
  return objects.filter((m, i) => objects.some((o, j) => j !== i && iou(m, o) > 0.5));
}

// ---------- Edits that depend on each other ----------

export const overlap = (a, b) => !!a && !!b && a.bits.some((v, i) => v && b.bits[i]);

// An edit is made again when something it saw has changed: an edit below it came, went or changed version, and
// that edit is a light, or this one is, or their footprints overlap. `before` is the active edits below it now,
// `basis` what they were when it was made: both as [{ id, version, tool, foot }].
export function dependsOnChange(edit, before, basis) {
  const key = (e) => `${e.id}.${e.version}`;
  const now = new Set(before.map(key)), was = new Set(basis.map(key));
  const changed = [...before.filter((e) => !was.has(key(e))), ...basis.filter((e) => !now.has(key(e)))];
  if (!changed.length) return false;
  return edit.tool === "light" || changed.some((c) => c.tool === "light" || overlap(c.foot, edit.foot));
}

// ---------- The frame cache's ranking, after OpenRV's FBCache ----------

// How useful frame f is to keep: the frame on screen most, then by distance from it; a frame behind counts as
// `behind` frames ahead; distances wrap round the in and out points (playback loops); frames outside them least.
export function frameUse(f, { frame, inPt, outPt }, behind = 3) {
  if (f === frame) return Infinity;
  const span = outPt - inPt + 1;
  if (f < inPt || f > outPt) return 1 / (1 + span + Math.min(Math.abs(f - inPt), Math.abs(f - outPt)));
  const at = Math.min(Math.max(frame, inPt), outPt), ahead = (f - at + span) % span, back = (at - f + span) % span;
  return 1 / (1 + Math.min(ahead, back * behind));
}

// ---------- The viewer's colour, as in RV's Color menu: display only, the export never changes ----------
// Exposure and contrast act in linear light (contrast about 18% grey), gamma on the display values, then saturation, hue,
// one channel shown as grey, and invert. The page applies them as one SVG filter on the canvas (app.mjs, setDisplay).
export const DISPLAY = { exposure: 0, contrast: 1, gamma: 1, saturation: 1, hue: 0, channel: "rgb", invert: false };
export const PARAMS = { // the interactive edits: label, step for - and = and the wheel, change per pixel dragged, limits
  exposure: { label: "Exposure", step: 0.1, drag: 0.01, min: -10, max: 10 }, // stops: one per 100 px dragged
  contrast: { label: "Contrast", step: 0.05, drag: 0.005, min: 0, max: 4 },
  gamma: { label: "Gamma", step: 0.05, drag: 0.005, min: 0.1, max: 8 },
  saturation: { label: "Saturation", step: 0.05, drag: 0.005, min: 0, max: 4 },
  hue: { label: "Hue", step: 5, drag: 0.5, min: -180, max: 180 }, // degrees
};
export const CHANNEL_NAMES = { rgb: "All channels", r: "Red", g: "Green", b: "Blue", l: "Luminance" };
export const clampParam = (name, v) => +Math.min(PARAMS[name].max, Math.max(PARAMS[name].min, v)).toFixed(3);
export const displayActive = (d) => Object.keys(DISPLAY).some((k) => d[k] !== DISPLAY[k]);

export function formatParam(name, v) {
  if (name === "exposure") return `${v > 0 ? "+" : ""}${v.toFixed(1)} stop${Math.abs(v) === 1 ? "" : "s"}`;
  return name === "hue" ? `${Math.round(v)}°` : v.toFixed(2);
}

export function displayLabel(d) { // the transport's reminder of what the viewer changes: "E +1.0 · γ 2.20 · Red"
  const parts = [];
  if (d.exposure) parts.push(`E ${d.exposure > 0 ? "+" : ""}${d.exposure.toFixed(1)}`);
  if (d.contrast !== 1) parts.push(`C ${d.contrast.toFixed(2)}`);
  if (d.gamma !== 1) parts.push(`γ ${d.gamma.toFixed(2)}`);
  if (d.saturation !== 1) parts.push(`Sat ${d.saturation.toFixed(2)}`);
  if (d.hue) parts.push(`Hue ${Math.round(d.hue)}°`);
  if (d.channel !== "rgb") parts.push(CHANNEL_NAMES[d.channel]);
  if (d.invert) parts.push("Inverted");
  return parts.join(" · ");
}

// The two transfer functions: slope and intercept in linear light (exposure, then contrast about 18% grey), then gamma.
export const displayTransfer = ({ exposure = 0, contrast = 1, gamma = 1 }) =>
  ({ slope: contrast * 2 ** exposure, intercept: 0.18 * (1 - contrast), exponent: 1 / gamma });

const LUMA = [0.2126, 0.7152, 0.0722];
const PICK = { r: [1, 0, 0], g: [0, 1, 0], b: [0, 0, 1], l: LUMA };
const times = (A, B) => A.map((row) => B[0].map((_, j) => row.reduce((a, v, k) => a + v * B[k][j], 0)));

export function displayMatrix({ saturation = 1, hue = 0, channel = "rgb", invert = false }) { // the 20 values of a feColorMatrix
  const s = saturation, t = (hue * Math.PI) / 180, c = Math.cos(t), n = Math.sin(t);
  const sat = [0, 1, 2].map((i) => [0, 1, 2].map((j) => LUMA[j] * (1 - s) + (i === j ? s : 0)));
  const rot = [[0.213 + c * 0.787 - n * 0.213, 0.715 - c * 0.715 - n * 0.715, 0.072 - c * 0.072 + n * 0.928], // SVG's hueRotate
    [0.213 - c * 0.213 + n * 0.143, 0.715 + c * 0.285 + n * 0.14, 0.072 - c * 0.072 - n * 0.283],
    [0.213 - c * 0.213 - n * 0.787, 0.715 - c * 0.715 + n * 0.715, 0.072 + c * 0.928 + n * 0.072]];
  let m = times(sat, rot);
  if (PICK[channel]) m = Array(3).fill(times([PICK[channel]], m)[0]);
  const sign = invert ? -1 : 1;
  return [...m.flatMap((row) => [...row.map((v) => +(sign * v).toFixed(5) + 0), 0, invert ? 1 : 0]), 0, 0, 0, 1, 0].join(" ");
}

// ---------- A fluid shot on a blank plate: AInVFX's ainvfx-fluid IC-LoRA (its model card, read 28 Oct 2026) ----------
// Sides in multiples of 64 (the LoRA's reference downscale factor is 2), up to the app's 1920; 8k + 1 frames, 121 tested,
// 33 and 321 seen in training; 24, 25 and 50 fps trained. Keyframes sit on frame 0, on the last frame, and between on
// the first frame of each 8-frame group of the LTX VAE (8k + 1).
export const FLUID = { trigger: "ainvfxfluid", step: 64, minSide: 256, maxSide: 1920, minFrames: 9, maxFrames: 321, tested: 121,
  rates: [24, 25, 50], prompt: "smoke plume" };
const nearest = (list, v) => list.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));

export function blankSpec({ width, height, fps, frames }) { // the blank plate LTX and ainvfx-fluid take, nearest to what was typed
  const side = (v) => Math.min(FLUID.maxSide, Math.max(FLUID.minSide, Math.round((+v || 0) / FLUID.step) * FLUID.step));
  const n = Math.min(FLUID.maxFrames, Math.max(FLUID.minFrames, Math.round(((+frames || 0) - 1) / 8) * 8 + 1));
  return { width: side(width), height: side(height), fps: nearest(FLUID.rates, +fps || FLUID.rates[1]), frames: n };
}

export function keySlots(frames) { // where a keyframe may sit: frame 0, each 8k + 1 that starts a whole group of 8, the last frame
  const slots = [0];
  for (let f = 1; f <= frames - 8; f += 8) slots.push(f);
  if (frames - 1 > slots.at(-1)) slots.push(frames - 1);
  return slots;
}

export const snapKey = (frame, frames) => nearest(keySlots(frames), frame);

export function moveKey(keys, key, frame, frames) { // where a dragged keyframe lands: the free slot nearest the pointer, else where it was
  const taken = new Set(keys.filter((k) => k !== key).map((k) => k.frame)), free = keySlots(frames).filter((f) => !taken.has(f));
  return free.length ? nearest(free, frame) : key.frame;
}

export function nearKeys(keys, frame) { // the keyframes before and after a frame: onion skins, Alt+Left and Alt+Right
  let prev = null, next = null;
  for (const k of keys) {
    if (k.frame < frame && (!prev || k.frame > prev.frame)) prev = k;
    if (k.frame > frame && (!next || k.frame < next.frame)) next = k;
  }
  return { prev, next };
}

// One edit at a time: the strokes in progress, else the current edit (the one just started, or picked in History).
export function strokeTarget({ draft, current, tool }) { // where a new stroke goes: "draft", "current" or "new"
  if (draft) return "draft";
  return current?.tool === tool ? "current" : "new";
}

export function toolEndsEdit({ draft, current }, tool) { // picking another tool than the edit being worked on starts a new edit
  const work = draft ?? current;
  return !!work && work.tool !== tool;
}

export function fluidPrompt(words) { // the trigger first, as the model card asks; no words: its own example
  const rest = (words || "").trim().replace(/^ainvfxfluid\s*,?\s*/i, "");
  return `${FLUID.trigger}, ${rest || FLUID.prompt}`;
}
