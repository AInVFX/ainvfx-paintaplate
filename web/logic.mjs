// Pure functions of the page: workflows as data, sizes, captions, time, edit dependencies, the frame cache's ranking.
// No DOM and no state here, so tests/js runs every one of them in Node (node --test).

// ---------- Workflows as data ----------

// Optional links: when every source slot is left empty, the link goes, with every node that fed it. The same rule as
// tools/build_workflows.py (OPTIONAL there; a test checks they match): no erase, nothing to fill before LTX; a relight
// alone, no matte to composite with, nor to save (the export's "matte" output goes with it).
export const OPTIONAL = { hole_mask: ["hole"], fit_mask: ["matte_a", "matte_b"], named: ["words"], relit_frame: ["relight"] };

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

// Multiples of `step` (what the models need) that keep the plate's aspect within 1.5%, as large as `cap` allows.
export function fitSize(w, h, cap, step) {
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
