// Pure functions of the page: workflows as data, sizes, captions, time, edit dependencies, the frame cache's ranking.
// No DOM and no state here, so tests/js runs every one of them in Node (node --test).

// ---------- Workflows as data ----------

// Optional links: when every source slot is left empty, the link goes, with every node that fed it. The same rule as
// tools/build_workflows.py (OPTIONAL there; a test checks they match): a relight alone has
// no matte to composite with, nor to save (the export's "matte" output goes with it).
// fit_keep comes first: with no matte at all, it goes before fit_mask, with which it shares the paint matte's node.
// follow_element comes before follow_base: the plate's element track hangs on both, and goes with the first.
export const OPTIONAL = { fit_keep: ["paint_matte"], fit_mask: ["matte_a", "matte_b"], named: ["words"], relit_frame: ["relight"], follow_element: ["seed"], follow_base: ["base"], follow_named: ["name_request"], follow_removed: ["removed_request"],
  review_frames: ["frames_prefix"], review_view: ["view_prefix"], hdr_shot: ["hdr"], plate_level: ["plate_width", "plate_height"],
  matte_movie: ["video_prefix"], export_matte_movie: ["matte_video_prefix"], fluid_control: ["control_prefix"],
  export_plate: ["prefix"], export_exr: ["exr_prefix"], export_layer: ["layer_prefix"], export_layer_exr: ["layer_exr_prefix"], export_shot: ["shot_prefix"], export_clean: ["clean_prefix"],
  upscale_comp: ["comp_prefix"], upscale_matte: ["matte_prefix"] };

// The matte's requests to the prompt upsampler: the words SAM 3.1 searches for, from an edit's text prompt.
export const NAME_REQUEST = { paint: "The edit painted this into the image: \"{text}\". Name the thing it painted with a short noun phrase of at most three words, like \"red car\" or \"smoke\". Answer with that phrase only.",
  erase: "The edit removes this from the image: \"{text}\". Name the thing it removes with a short noun phrase of at most three words, like \"red car\" or \"tree\". Answer with that phrase only." };

export function nameRequest(tool, texts) { // the request for the edits' text prompts, joined; none without a text prompt
  const text = texts.map((t) => String(t ?? "").trim()).filter(Boolean).join("; ");
  return text ? NAME_REQUEST[tool].replace("{text}", () => text.replaceAll("\"", "'")) : ""; // a function: « $& » in a text prompt stays as typed
}

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
  const fed = new Set(), cut = (v) => { if (Array.isArray(v)) fed.add(String(v[0])); }; // what fed what goes
  for (const [id, input] of wf.slots[link] ?? []) if (wf.prompt[id]) { cut(wf.prompt[id].inputs[input]); delete wf.prompt[id].inputs[input]; } // a node another link took already
  const gone = new Set(sources.flatMap((k) => (wf.slots[k] ?? []).map(([id]) => id)));
  if (extra) gone.add(extra);
  for (let grew = true; grew;) {
    grew = false;
    for (const [id, node] of Object.entries(wf.prompt)) {
      if (gone.has(id) || !Object.values(node.inputs).some((v) => Array.isArray(v) && gone.has(String(v[0])))) continue;
      gone.add(id); grew = true;
    }
  }
  // what fed the cut input and the nodes that went goes too, once nothing else takes its outputs (an output always stays)
  for (const id of gone) { for (const v of Object.values(wf.prompt[id]?.inputs ?? {})) cut(v); delete wf.prompt[id]; }
  for (let grew = true; grew;) {
    grew = false;
    const used = new Set(Object.values(wf.prompt).flatMap((n) => Object.values(n.inputs).filter(Array.isArray).map((v) => String(v[0]))));
    for (const id of [...fed].sort()) {
      const node = wf.prompt[id];
      if (!node || used.has(id) || node._meta?.output) continue;
      for (const v of Object.values(node.inputs)) if (Array.isArray(v)) fed.add(String(v[0]));
      delete wf.prompt[id]; grew = true;
    }
  }
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

// Preview pass: half and a quarter of the working size, each on the grid with the plate's aspect (previewSize). `div` is
// the part of the working size's long side, `cap` that long side.
const PREVIEW_PARTS = [[2, "Half size"], [4, "Quarter size"]];
// The Preview menu: Off (no preview pass and no live preview), Latent preview (no preview pass; each pass's live preview
// shows in the player), then a preview pass at half or a quarter of the working size, with the live preview too.
export const PREVIEW_DEFAULT = "latent";
// Save scene: a name the scenes route accepts (letters, digits, '.', '-' and '_', not starting with '.'), and the first
// free name after one that is taken: horse, horse_2, horse_3; a name that ends in _2 goes on from _3.
export const sceneName = (text) => String(text).replace(/[^\w.-]/g, "_").replace(/^\.+/, "").slice(0, 100);
export function freeName(name, taken) {
  const m = /^(.*)_(\d+)$/.exec(name), stem = m ? m[1] : name;
  for (let n = m ? Number(m[2]) + 1 : 2; ; n++) if (!taken.has(`${stem}_${n}`)) return `${stem}_${n}`;
}
export function readPreview(v) { // a choice stored for the session, or the menu's value: "off", "latent", 2 or 4; null for anything else
  if (v === "off" || v === "latent") return v;
  const n = typeof v === "string" && v.trim() !== "" ? Number(v) : v;
  return PREVIEW_PARTS.some(([d]) => d === n) ? n : null;
}
export const previewDivOf = (mode) => (typeof mode === "number" ? mode : 0); // the preview pass's part of the working size; 0: none
export const liveEvery = (mode) => (mode === "off" ? 0 : 1); // the workflows' live preview: at every step, or never
// A step's name. For a set of Light edits only, the composite is Relight Transfer: the light from the shot, the detail
// from the plate. Its times stay under the step's id, so the estimates keep learning.
const LIGHT_STEPS = { comp: "Light transfer, preview", review: "Light transfer, full size" };
export const stepLabel = (st, lightOnly) => (lightOnly && LIGHT_STEPS[st.id]) || st.label;
export function previewSizes(plate, work, step = 32) {
  const out = [];
  for (const [div, label] of PREVIEW_PARTS) {
    const cap = previewCap(work, div), size = previewSize(plate, work, cap, step);
    if (!out.some((o) => o.size[0] === size[0] && o.size[1] === size[1])) out.push({ label, div, cap, size });
  }
  return out;
}
export const previewCap = (work, div) => (div ? Math.round(Math.max(...work) / div) : 0); // the shot preview's long side; 0: Off

export const gb = (n) => (n > 1e9 ? `${(n / 1e9).toFixed(2)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);

// A time as a person reads it in the Render panel's rows and the render's log lines: seconds under 100 s, then minutes
export const span = (s) => (s < 100 ? `${Math.round(s)} s` : `${Math.round(s / 60)} min`);
export const doneIn = (dt, guess) => `done in ${dt < 100 ? `${dt.toFixed(1)} s` : `${(dt / 60).toFixed(1)} min`} (estimate ${span(guess)})`;
export function secs(t, tail = " left") { // "about 40 s left", "about 1 min 40 s left": rounded to 10 s past a minute; with tail "", the time alone
  if (t == null || !isFinite(t)) return "";
  if (t < 60) return `about ${Math.max(1, Math.round(t))} s${tail}`;
  const r = Math.round(t / 10) * 10, m = Math.floor(r / 60), s = r % 60;
  return m >= 10 || !s ? `about ${Math.round(t / 60)} min${tail}` : `about ${m} min ${s} s${tail}`;
}

// ---------- Captions: the page's own text and table for an edit (app.templateCaption) ----------

export const dark = (hex) => [1, 3, 5].reduce((a, i, k) => a + [0.2126, 0.7152, 0.0722][k] * parseInt(hex.slice(i, i + 2), 16), 0) < 60;

// An erase's words as its object's name after « the »: an article that was typed goes, or « the barn » would ask Klein's
// prompt writer to « Remove the the barn ».
const objectName = (words) => String(words ?? "").trim().replace(/^(?:the|a|an)\s+/i, "");

// A paint's colours by name. Klein sees the strokes on the frame, but words alone (« saddle ») leave the prompt writer free to
// give the object its usual colour. When the words name no colour, the writer's request and the page's own caption name the
// colours that the strokes show, by their share of the painted pixels, largest first; a colour under 5% of them is an edge
// where two strokes meet. Words that name a colour win, and then the page names none.
const COLOR_WORDS = /\b(?:red|orange|yellow|green|cyan|blue|violet|purple|magenta|pink|brown|black|white|gr[ae]y|silver|gold(?:en)?|beige|tan|crimson|scarlet|maroon|navy|teal|turquoise|ivory)\b/i;
const HUES = [[15, "red"], [40, "orange"], [70, "yellow"], [165, "green"], [195, "cyan"], [255, "blue"], [290, "violet"], [345, "magenta"], [361, "red"]];

// A colour by name, one namer for a paint and a light: « black », « brown », « dark blue », « pink », « warm white ». Each
// colour swatch of the page is named as its title names it, and a picked colour by the same rule. A colour is pale when
// each of its channels is above 55%; a pale orange, as the swatch « Warm light », is « warm white », which reads well in a
// light's sentence: « a strong, broad warm white light ».
export function colorName(hex) {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255);
  const max = Math.max(r, g, b), min = Math.min(r, g, b), c = max - min;
  if (c < 0.12) return max < 0.2 ? "black" : max < 0.45 ? "dark grey" : max < 0.7 ? "grey" : max < 0.9 ? "light grey" : "white";
  const h = ((max === r ? (g - b) / c : max === g ? 2 + (b - r) / c : 4 + (r - g) / c) * 60 + 360) % 360;
  const name = HUES.find(([end]) => h < end)[1];
  if ((name === "orange" || name === "yellow") && max < 0.6) return "brown";
  if (max < 0.35) return `dark ${name}`;
  if (min > 0.55) return name === "red" || name === "magenta" ? "pink" : name === "orange" ? "warm white" : `pale ${name}`;
  return name;
}

// A light edit's colour, by name: its first stroke that is not dark (a dark stroke is a shade), or the tool's colour when the
// edit has no stroke. None when every colour is dark: a shade alone names no light.
export const lightColor = (colors, color) => {
  const c = colors.length ? colors.find((x) => !dark(x)) : color;
  return c && !dark(c) ? colorName(c) : null;
};

// The pixels of each colour of `palette` (#rrggbb) in `rgba`, a canvas's bytes: a pixel counts when it is at least half
// opaque and within 24 levels of that colour on every channel. Where two strokes blend, it counts for neither.
export function colorShares(rgba, palette) {
  const cols = palette.map((hex) => [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16))), n = palette.map(() => 0);
  for (let i = 0; i < rgba.length; i += 4) {
    if (rgba[i + 3] < 128) continue;
    const k = cols.findIndex((c) => Math.abs(c[0] - rgba[i]) <= 24 && Math.abs(c[1] - rgba[i + 1]) <= 24 && Math.abs(c[2] - rgba[i + 2]) <= 24);
    if (k >= 0) n[k]++;
  }
  return Object.fromEntries(palette.map((hex, k) => [hex, n[k]]));
}

export function paintColors({ words, shares }) { // the names, largest share first; none when the words name a colour
  if (COLOR_WORDS.test(String(words ?? ""))) return [];
  const by = new Map();
  let total = 0;
  for (const [hex, n] of Object.entries(shares ?? {})) if (n > 0) { const h = colorName(hex); by.set(h, (by.get(h) ?? 0) + n); total += n; }
  return [...by].filter(([, n]) => n >= 0.05 * total).sort((a, b) => b[1] - a[1]).map(([h]) => h);
}

export const andList = (xs) => (xs.length > 1 ? `${xs.slice(0, -1).join(", ")} and ${xs.at(-1)}` : xs[0] ?? "");
export const inHues = (hues) => (hues.length ? ` in the drawing's colour${hues.length > 1 ? "s" : ""}, ${andList(hues)}` : "");
// what a paint becomes, in a request's words: the words, else `shape`; with the strokes' colours when they are named
const paintWhat = (words, hues, shape) => (words ? `${words}${inHues(hues)}` : hues.length ? `${shape}${inHues(hues)}` : `${shape} and colour`);

// tool: paint, erase or light; words: the prompt;
// bbox: [y_min, x_min, y_max, x_max] on 0..1000; strokes and aspect: a relight's, as lightIntent reads them; hues: a
// paint's colours by name (paintColors). Only the chosen tool's text is built.
export function caption({ tool, words, bbox, strokes = [], aspect, hues = [] }) {
  if (tool === "light") return lightIntent({ strokes, words, aspect }); // a relight's request is the page's own: its strokes read as intentions
  const name = objectName(words);
  const text = {
    erase: () => `Remove the ${name || "object"} inside <obj_1> completely, with its shadow and its reflection. Show the surface and the background that continue behind it, with matching detail, light, shadows and focus. Add no new object. Keep everything else unchanged.`,
    paint: () => `Replace the rough coloured drawing inside <obj_1> with ${paintWhat(words, hues, "an object of that shape")}, following the drawing's outline, pose and size, in exactly the same style, lighting, perspective and grain as the rest of the image. Keep everything else unchanged.`,
  }[tool]();
  const desc = { erase: name ? `${name} to remove` : "object to remove", paint: hues.length ? `${words || "the drawn object"}, ${andList(hues)}` : words || "the drawn object" }[tool];
  return `${text} ${JSON.stringify([{ id: "obj_1", bbox, desc }])}`;
}

// ---------- What the prompt writer reads, and what the page keeps of its answer ----------
// Black Forest Labs' own format (src/flux3/pup.py and bbox.py): an erase or a paint edit is a request with locked rows in
// the table Klein was trained on, one per painted part of an erase and one for a paint. A relight's request is the page's
// own (lightIntent), and never reaches the prompt writer. Boxes are [y_min, x_min, y_max, x_max] on 0..1000.

const pyJSON = (v) => JSON.stringify(v).replace(/("(?:[^"\\]|\\.)*")|([,:])/g, (m, s, p) => s ?? `${p} `); // json.dumps spacing
const KEEP_TOUCHED = " Where the drawing touches an object, the new element acts on that object itself (it burns it, rests on it, " +
  "wets it or lights it); add no props, fuel or supports that were not asked for."; // without it, a fire on a towel comes with logs

export function upsampleRequest({ tool, words, bbox, boxes = null, hues = [] }) { // hues: a paint's colours by name (paintColors)
  const parts = tool === "erase" && boxes?.length > 1 ? boxes : null; // several painted parts: one locked row each
  const rows = parts ? parts.map((b, i) => ({ id: `obj_${i + 1}`, from: "ref_image_0", src_bbox: b, tgt_bbox: null, desc: words || "an object to remove" }))
    : [tool === "erase" ? { id: "obj_1", from: "ref_image_0", src_bbox: boxes?.[0] ?? bbox, tgt_bbox: null, desc: words || "the object to remove" }
      : { id: "obj_1", from: "target", src_bbox: null, tgt_bbox: bbox, desc: hues.length ? `${words || "an object of the drawing's shape"}, ${andList(hues)}` : words || "an object of the drawing's shape and colour, in the image's own style" }];
  const list = andList(rows.map((r) => `<${r.id}>`));
  const ask = tool === "erase"
    ? parts ? `Remove the ${objectName(words) || "objects"} ${list} completely, with their shadows and their reflections, and continue the background behind them. Remove nothing else.`
      : `Remove the ${objectName(words) || "object"} <obj_1> completely, with its shadow and its reflection, and continue the background behind it. Remove nothing else.`
    : `Replace the rough coloured drawing at <obj_1> with ${paintWhat(words, hues, "an object of the same shape")}: follow the drawing's outline, pose, size and colours, and draw it in exactly the style of the rest of the image (a photograph, a painting or an illustration: whichever it is), in the same light, perspective, focus and grain, casting its own light and shadows on what is around it.${KEEP_TOUCHED}`;
  const instruction = `ORIGINAL PROMPT:\n${ask}\n\nLOCKED BOUNDING-BOX ANNOTATIONS ([y_min, x_min, y_max, x_max] on a 0-1000 canvas, with ` +
    "(0, 0) at the top-left). This is an authoritative JSON list of dictionaries; preserve every supplied identity, provenance value, " +
    `null, and coordinate exactly:\n${pyJSON(rows)}`;
  return { mode: "table", locked: rows,
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
function validBox(b) {
  if (!Array.isArray(b) || b.length !== 4 || b.some((v) => typeof v !== "number" || !Number.isFinite(v))) return null;
  const [y1, x1, y2, x2] = b;
  return y1 < 0 || x1 < 0 || y2 <= y1 || x2 <= x1 || y2 > 1000 || x2 > 1000 || Math.max(...b) <= 1 ? null : b;
}

function addedRow(row, caption) { // a row the prompt writer added: kept when it is cited as <id> and well formed
  if (!row || typeof row !== "object" || !ROW_ID.test(row.id ?? "") || !caption.includes(`<${row.id}>`) || !String(row.desc ?? "").trim()) return null;
  const desc = row.desc.trim(), box = validBox(row.bbox);
  if (box) return { id: row.id, bbox: box, desc };
  const src = row.src_bbox == null ? null : validBox(row.src_bbox), tgt = row.tgt_bbox == null ? null : validBox(row.tgt_bbox);
  if (!/^(ref_image_\d+|target)$/.test(row.from ?? "") || (row.src_bbox != null && !src) || (row.tgt_bbox != null && !tgt) ||
    (!src && !tgt) || (row.from === "target") === !!src) return null;
  return { id: row.id, from: row.from, src_bbox: src, tgt_bbox: tgt, desc };
}

// The prompt writer's answer with the page's own rows put back, as Black Forest Labs' reconcile(): each locked row verbatim
// with the prompt writer's description of it, then the rows it added. A cut-off table leaves the caption and the locked rows.
export function reconcile(text, locked) {
  const [caption, rows] = splitTable(text);
  const byId = new Map((rows ?? []).filter((r) => r && typeof r.id === "string").map((r) => [r.id, r]));
  const out = locked.map((lock) => ({ ...lock, desc: String(byId.get(lock.id)?.desc ?? "").trim() || lock.desc }));
  for (const r of rows ?? []) { const a = addedRow(r, caption); if (a && !out.some((o) => o.id === a.id)) out.push(a); }
  return `${caption} ${pyJSON(out)}`;
}

// ---------- An erase: one locked box per painted part ----------
// One box around several painted parts can take in an object that stands between them, and the prompt writer then
// removes that object instead. A few tight boxes cover the paint, so they hold what was painted and little else.
// paint: { bits, w, h } on a coarse grid; boxes are [y_min, x_min, y_max, x_max] on 0..1000.
export function paintBoxes({ bits, w, h }, { max = 4, fill = 0.4, gain = 0.25, margin = 8 } = {}) {
  // a box: the painted cells in it and their tight bounds. The emptiest box splits in two, along its long side, where the two
  // halves' tight boxes cover the least, while that saves a quarter of its area and fewer than `max` boxes exist
  const tight = (cells) => {
    let y1 = h, x1 = w, y2 = -1, x2 = -1;
    for (const c of cells) { const y = Math.floor(c / w), x = c % w; y1 = Math.min(y1, y); x1 = Math.min(x1, x); y2 = Math.max(y2, y); x2 = Math.max(x2, x); }
    return { cells, y1, x1, y2, x2, area: (y2 - y1 + 1) * (x2 - x1 + 1) };
  };
  const all = [];
  for (let c = 0; c < w * h; c++) if (bits[c]) all.push(c);
  if (!all.length) return [];
  const boxes = [tight(all)];
  while (boxes.length < max) {
    const b = boxes.filter((x) => x.cells.length < fill * x.area).sort((a, z) => (z.area - z.cells.length) - (a.area - a.cells.length))[0];
    if (!b) break;
    const vertical = b.x2 - b.x1 >= b.y2 - b.y1, key = (c) => (vertical ? c % w : Math.floor(c / w));
    const sorted = [...b.cells].sort((p, q) => key(p) - key(q));
    let best = null;
    for (let i = 1; i < sorted.length; i++) {
      if (key(sorted[i]) === key(sorted[i - 1])) continue;
      const a = tight(sorted.slice(0, i)), z = tight(sorted.slice(i));
      if (!best || a.area + z.area < best[0].area + best[1].area) best = [a, z];
    }
    if (!best || best[0].area + best[1].area > (1 - gain) * b.area) break;
    boxes.splice(boxes.indexOf(b), 1, ...best);
  }
  const box = (b) => [Math.max(0, Math.floor((b.y1 / h) * 1000) - margin), Math.max(0, Math.floor((b.x1 / w) * 1000) - margin),
    Math.min(1000, Math.ceil(((b.y2 + 1) / h) * 1000) + margin), Math.min(1000, Math.ceil(((b.x2 + 1) / w) * 1000) + margin)];
  return boxes.sort((a, z) => a.x1 - z.x1 || a.y1 - z.y1).map(box); // numbered left to right, as the prompt writer numbers its rows
}

// The rows of an answer that removes objects, apart from the locked ones: named in its caption, with a box in the frame and none
// in the result.
const removedRows = (caption, rows, locked) => {
  const ids = new Set(locked.map((r) => r.id));
  return (rows ?? []).filter((r) => r && !ids.has(r.id) && r.tgt_bbox == null && validBox(r.src_bbox) && caption.includes(`<${r.id}>`));
};

// Whether a caption erases what was painted: it cites a locked row (<obj_1>), or the rows it removes and cites hold most of the
// paint. `paint`: { bits, w, h }, the painted area on a coarse grid. A bad caption can remove person_1, a box with none of the
// paint in it; a good one may never cite <obj_1> but remove four rows that hold nearly all of it.
export function erasesPaint(text, locked, paint, share = 0.5) {
  const [caption, rows] = splitTable(text);
  if (locked.some((r) => caption.includes(`<${r.id}>`))) return true;
  const boxes = removedRows(caption, rows, locked).map((r) => r.src_bbox);
  let painted = 0, inside = 0;
  for (let y = 0; y < paint.h; y++) for (let x = 0; x < paint.w; x++) {
    if (!paint.bits[y * paint.w + x]) continue;
    painted++;
    const Y = ((y + 0.5) / paint.h) * 1000, X = ((x + 0.5) / paint.w) * 1000;
    if (boxes.some(([y1, x1, y2, x2]) => Y >= y1 - 10 && Y <= y2 + 10 && X >= x1 - 10 && X <= x2 + 10)) inside++;
  }
  return painted > 0 && inside / painted >= share;
}

// An erase with no words whose prompt writer took the stroke for another object (erasesPaint refused its answer) asks for
// the object's name before Klein runs: given the page's own caption instead, Klein can leave the object, and the shot
// renders. With words, the page's own caption carries them, and Klein runs.
export const asksName = (tool, words) => tool === "erase" && !String(words ?? "").trim();

// ---------- An erase with no words: the box the prompt writer gets ----------
// The object's core: the stroke, and the pixels that most of SAM's masks hold. A neighbour that a few masks take in (a horse's
// nose beside a barn) stays out of it, so the prompt writer's box holds the object under the stroke. `painted` and `masks`:
// Uint8Arrays of 0 and 1 over w x h pixels.
export function corePixels({ painted, masks, w, h }) {
  const bits = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) {
    let n = 0;
    for (const m of masks) n += m[i];
    bits[i] = painted[i] || n * 2 > masks.length ? 1 : 0;
  }
  return bits;
}

// The box around the pixels that `bits` sets, with no margin, as [y0, x0, y1, x1] from 0 to 1000. null: none is set.
export function boxOf(bits, w, h) {
  let y0 = h, x0 = w, y1 = -1, x1 = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (!bits[y * w + x]) continue;
    y0 = Math.min(y0, y); y1 = Math.max(y1, y); x0 = Math.min(x0, x); x1 = Math.max(x1, x);
  }
  return x1 < 0 ? null : [y0 / h, x0 / w, (y1 + 1) / h, (x1 + 1) / w].map((v) => Math.round(v * 1000));
}

export const coreBox = ({ painted, masks, w, h }) => boxOf(corePixels({ painted, masks, w, h }), w, h);

// The boxes the prompt writer gets: an erase with no words, painted in one part, gets its core box; otherwise one box per
// painted part (paintBoxes), with the edit's bounds (`bbox`).
export const writerBoxes = ({ tool, words, parts, core, bbox }) =>
  (tool === "erase" && !String(words ?? "").trim() && core && parts?.length === 1 ? { bbox: core, boxes: [core] } : { bbox, boxes: parts });

// What the prompt writer saw when the page asks for an object's name (app.generate, edit.editAsked): the objects that its
// last answer removes, as « barn » or « old car, sign and fence », or true when that answer names none.
export const writerSaw = (names = []) =>
  (!names?.length ? true : andList(names));

// The objects that an answer removes, apart from the locked ones, as SAM 3.1 reads a name: the row « barn_1 » is « barn ».
export function removedNames(text, locked = []) {
  const [caption, rows] = splitTable(text ?? "");
  const names = removedRows(caption, rows, locked).map((r) => String(r.id).replace(/_\d+$/, "").replace(/_/g, " ").trim());
  return [...new Set(names.filter(Boolean))];
}

// The frame that the prompt writer gets for its second look at an erase with no words (app.dimFrame): the object in full
// light and every other pixel at `keep` of its light, rounded down, so that the object under the stroke stands out from
// everything around it. rgba: the frame's pixels, 4 values each; bits: a Uint8Array of 0 and 1, one per pixel, 1 inside
// the object. A new array; the alpha stays.
export const DIM = 0.3;
export function dimOutside(rgba, bits, keep = DIM) {
  const out = new Uint8ClampedArray(rgba);
  for (let i = 0; i < bits.length; i++) if (!bits[i]) for (let c = 0; c < 3; c++) out[i * 4 + c] = Math.floor(rgba[i * 4 + c] * keep);
  return out;
}

// The erase pass's prompt: the scene as it stays, in the prompt writer's own words for what it kept (rows with a box in the
// result). People and text stay out (a pose in words fights the plate's own motion), and the erased object is never named
// (named, it comes back). Nothing kept: no prompt, as LTX's inpainting guide recommends.
const UNNAMED = /^(?:person|people|man|woman|child|boy|girl|crowd|en_text)$/i;
export function erasePrompt(captions) {
  const descs = [];
  for (const text of captions) {
    const [, rows] = splitTable(text ?? "");
    for (const r of rows ?? []) {
      if (!r || r.from !== "ref_image_0" || !validBox(r.tgt_bbox) || UNNAMED.test(String(r.id ?? "").replace(/_\d+$/, ""))) continue;
      const d = String(r.desc ?? "").trim().replace(/\s+/g, " ");
      if (d && !descs.includes(d)) descs.push(d);
    }
  }
  return descs.map((d) => (/[.!?]$/.test(d) ? d : `${d}.`)).join(" ");
}

// The full size's first stage, as in Lightricks' two-stage LTX workflows: half the working size, in multiples of 32. The second
// stage refines it at full size in 2 steps (8 steps at full size take 181 s on a 1080p plate).
export const stageOne = ([w, h], step = 32) => [Math.max(step, Math.round(w / 2 / step) * step), Math.max(step, Math.round(h / 2 / step) * step)];

// ---------- A render step and a new edit ----------
// Generate stops a running render step only where that wastes least: a full-size or an export step in its first half. A step
// past halfway costs less to finish than to run again, and a preview step is short and often reused by the new edit's render.
export const stopsForEdit = ({ cls, progress }) => cls !== "preview" && progress < 0.5;
// A step's result displayed as it is made plays at once, and a player that already plays goes on with it. It waits, paused,
// while the person paints, has an edit or the keyframes selected, looks at a pinned step, or paused the player by hand
// during this render (Space, the play button); a stop holds everything.
export const autoplays = ({ playing, painting, selected, keying, pinned, heldHere, halted }) =>
  !halted && (playing || !(painting || selected || keying || pinned || heldHere));
// Its line, written once: « Shot, preview: playing. The composite follows. », or « …: ready. Press Space to play it. … ».
// `asMade`: what follows the state, as « , as LTX made it »; `follows`: the step that comes next, or what to do.
export const resultLine = (label, plays, { asMade = "", follows = "" } = {}) =>
  `${label}: ${plays ? "playing" : "ready"}${asMade}. ${plays ? "" : "Press Space to play it. "}${follows}`.trim();
// A new preview size while a render makes a step: the step stops, at any progress, when the preview at the new size must
// come first: a preview at the old size, or a full-size step. A step that serves every size (the object tracked for
// Clean), a Finish step and the export go on. `cls`: the step's class, as stepClasses gives it.
export const stopsForPreview = (step, cls) => !!step.preview || (!!step.final && cls === "full");

// ---------- The job index ----------
// A job's key hashes its workflow and the values that change what it makes. Output folders (the prefixes) and the live
// preview's rate change nothing it makes, so they stay out, and a scene opened again on the same machine finds its jobs.
export const indexValues = (values) => Object.keys(values).sort().filter((k) => !/prefix$/.test(k) && k !== "live").map((k) => [k, values[k]]);
// The plate's identity in a job index key: its path, its files, its size and its time, as /paintaplate/stat gives them (`st`).
// null: no job index while this plate is open, because the plate could not be checked, or because the address says
// ?index=0 (`on` is false), for the tests: every job then runs, so each time and each peak of memory is a measured one.
export const plateIdentity = (path, st, on = true) => (st && on ? JSON.stringify([path, st.files, st.size, st.mtime]) : null);

// ---------- The shot's prompt ----------
export const RIPPLE = "Use the reference video for motion, timing, camera movement, framing and lighting changes; " +
  "follow the edited first frame for every change of content, light and style.";

// The Ripple sentence, then one line per paint or light edit (its card: a short description of the change helps; without
// it, an explosion added on a car can stay and grow instead of driving off with the car). An erase is never named: named,
// it comes back.
export function shotPrompt(edits) { // a light edit names its colour (`hue`), with or without words
  return [RIPPLE, ...edits.filter((e) => (e.tool === "paint" && e.words) || e.tool === "light").map((e) => (e.tool === "paint"
    ? `Added in the first frame: ${e.words}; it keeps moving naturally and stays in place on what it touches for the whole shot.`
    : `The first frame is relit${e.hue ? ` with ${e.hue} light` : ""}${e.words ? `: ${e.words}` : ""}; this new light holds for the whole shot.`))].join(" ");
}

// ---------- Whole object: which of SAM's masks belong to the erase ----------
// Masks are Uint8Arrays of 0 and 1 over `area` pixels. Found by name: the instances the stroke touches. Else one mask per stroke
// point: objects only (not the sky or the road), kept when two points agree (a point that slips onto the road finds a strip of
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

// ---------- The matte strategy: how much of the regenerated shot the composite keeps ----------
// Follow Matte's input `strategy` (mathops.MATTE_STRATEGIES), one per paint, from the menu under its row in History. A
// Clean's matte is also the hole its clean plate pass fills, so a strategy there would make that pass again: a Clean, a
// Light edit (no matte) and the fluid shot take no menu. An edit with no strategy, as in an older scene, has « Auto ».
export const MATTE_STRATEGIES = ["Auto", "Object", "Object and effects", "Whole shot"];
export const MATTE_TIPS = {
  Auto: "Object, or Object and effects when the edit spreads past the object.",
  Object: "The edit's object only, which keeps the most plate.",
  "Object and effects": "The object, what it replaces, and what the shot changed around it: smoke, light, thin haze.",
  "Whole shot": "Every pixel comes from the regenerated shot.",
};
export const matteChoices = (tool) => (tool === "paint" ? MATTE_STRATEGIES : []);
export const matteOf = (e) => (matteChoices(e?.tool).includes(e?.matte) ? e.matte : "Auto");
// A part of an edit's render key: a strategy other than « Auto » makes another render, whose shot comes from the job index
export const matteKey = (e) => (matteOf(e) === "Auto" ? "" : `~${MATTE_STRATEGIES.indexOf(matteOf(e))}`);
// The paints share one matte step: it runs the widest of their strategies, so none is cropped below its own choice
const WIDTH = ["Object", "Auto", "Object and effects", "Whole shot"];
export function sharedMatte(edits) {
  return edits.length ? edits.map(matteOf).reduce((a, b) => (WIDTH.indexOf(b) > WIDTH.indexOf(a) ? b : a)) : "Auto";
}
// The log's line when paints that share the matte chose differently; `num` gives an edit's number in History
export function sharedMatteLine(edits, num) {
  if (edits.length < 2 || new Set(edits.map(matteOf)).size < 2) return "";
  const nums = edits.map(num), runs = sharedMatte(edits), by = edits.find((e) => matteOf(e) === runs);
  return `Edits ${nums.slice(0, -1).join(", ")} and ${nums.at(-1)} share the paint matte: it runs ${runs}, edit ${num(by)}'s choice.`;
}
// What « Auto » chose, from the strategy line of Follow Matte's summary; null when the summary has none
export function autoChose(summary) {
  const m = /Strategy: Auto chose (Object and effects|Object)\b/.exec(summary ?? "");
  return m ? m[1] : null;
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
  return edit.tool === "light" || changed.some((c) => c.tool === "light" || c.tool === "fluid" || overlap(c.foot, edit.foot)); // a light or a fluid shot changes the whole frame
}

// A render of fewer edits (after a bypass or a removal) can take the frames of an earlier render of more edits: its composite
// then takes those frames only inside the mattes of the edits it keeps, and the plate everywhere else. That is exact when
// every edit left out is far from every edit kept (their first-frame footprints apart; an edit without one counts as near)
// and no light is involved, since a light changes every pixel. `want`: the new render's edits, as frozen; `renders`:
// [{ key, active, wanted }], those whose frames exist. Returns the key of the one with the fewest edits left out, then the
// most recently shown, or null.
// `self`, the key of the render that asks: a render of the same edits whose key differs only by matte strategies
// (logic.matteKey) made this very shot, so its frames serve too.
export function donorFor(want, renders, self = "") {
  const key = (e) => `${e.id}.${e.version}`, mine = new Set(want.map(key)), unmatted = (k) => k.replace(/~\d+/g, "");
  const apart = (a, b) => !!a.foot && !!b.foot && !overlap(a.foot, b.foot);
  if (!want.length || want.some((e) => e.tool === "light")) return null;
  let best = null;
  for (const r of renders) {
    const have = new Set(r.active.map(key)), same = !!self && r.key !== self && unmatted(r.key) === unmatted(self);
    if ((have.size <= mine.size && !(same && have.size === mine.size)) || [...mine].some((k) => !have.has(k)) || r.active.some((e) => e.tool === "light")) continue;
    const out = r.active.filter((e) => !mine.has(key(e)));
    if (!out.every((o) => want.every((e) => apart(o, e)))) continue;
    const wanted = r.wanted ?? 0;
    if (!best || out.length < best.out || (out.length === best.out && wanted > best.wanted)) best = { key: r.key, out: out.length, wanted };
  }
  return best?.key ?? null;
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

// ---------- The colour picker ----------
// The in-frame colour picker: the average of the pixels under the click as #rrggbb, for the brush. `data`
// holds RGBA bytes, as getImageData returns them; transparent pixels, outside the frame, do not count.
export function pickedColor(data) {
  let r = 0, g = 0, b = 0, n = 0;
  for (let i = 0; i < data.length; i += 4) if (data[i + 3] > 0) { r += data[i]; g += data[i + 1]; b += data[i + 2]; n++; }
  return n ? `#${[r, g, b].map((v) => Math.round(v / n).toString(16).padStart(2, "0")).join("")}` : null;
}

// ---------- A fluid shot on a blank plate: AInVFX's ainvfx-fluid IC-LoRA (its model card) ----------
// Sides in multiples of 64 (the LoRA's reference downscale factor is 2), up to the app's 1920; 8k + 1 frames from 9 up to
// LTX 2.5's 20 s at the frame rate (plateLength), 121 tested, 33 and 321 seen in training; 24, 25 and 50 fps trained. Keyframes sit on frame 0, on the last frame, and between on
// the first frame of each 8-frame group of the LTX VAE (8k + 1).
export const FLUID = { trigger: "ainvfxfluid", step: 64, minSide: 256, maxSide: 1920, minFrames: 9, tested: 121,
  rates: [24, 25, 50], prompt: "smoke plume" };
const nearest = (list, v) => list.reduce((a, b) => (Math.abs(b - v) < Math.abs(a - v) ? b : a));

export function blankSpec({ width, height, fps, frames }, machine = {}) { // the blank plate LTX and ainvfx-fluid take, nearest to what was typed
  const side = (v) => Math.min(FLUID.maxSide, Math.max(FLUID.minSide, Math.round((+v || 0) / FLUID.step) * FLUID.step));
  const rate = nearest(FLUID.rates, +fps || FLUID.rates[1]), [w, h] = [side(width), side(height)];
  const most = Math.max(FLUID.minFrames, plateKeep({ width: w, height: h, fps: rate }, machine).frames); // up to 20 s at that rate, as the machine holds
  const n = Math.min(most, Math.max(FLUID.minFrames, Math.round(((+frames || 0) - 1) / 8) * 8 + 1));
  return { width: w, height: h, fps: rate, frames: n };
}

// A sentence for each value of the Blank plate tab that the blank plate does not take as typed. Once the person leaves a
// field, it shows the value used (blankFit in app.mjs), and the tab's note keeps the sentence.
export function blankChanges(typed, used, machine = {}) {
  const said = [], given = (v) => String(v ?? "").trim() !== "" && Number.isFinite(+v);
  for (const [label, key] of [["Width", "width"], ["Height", "height"]]) {
    const v = +typed[key], u = used[key];
    if (!given(typed[key])) said.push(`${label} set to ${u} px.`);
    else if (v !== u) said.push(`${label} set to ${u} px, ${v > FLUID.maxSide ? "the largest" : v < FLUID.minSide ? "the smallest" : `the nearest multiple of ${FLUID.step}`}.`);
  }
  const f = +typed.frames;
  const most = plateKeep(used, machine), why = most.by === "ram" ? `the most this machine holds at ${used.width} x ${used.height}` : `the most at ${used.fps} fps (${LENGTH.seconds} s)`;
  if (!given(typed.frames)) said.push(`Frames set to ${countText(used.frames)}.`);
  else if (f !== used.frames) said.push(`Frames set to ${countText(used.frames)}, ${f > most.frames ? why : f < FLUID.minFrames ? "the fewest" : "the nearest count LTX takes"}.`);
  if (+typed.fps !== used.fps) said.push(`Frame rate set to ${used.fps} fps.`);
  return said;
}

// The Blank plate tab's limits under its hint, from FLUID and the frames this machine holds at the size and rate chosen.
export const blankLimits = (s, machine = {}) => `Width and height: ${FLUID.minSide} to ${FLUID.maxSide} px, in steps of ${FLUID.step}. ` +
  `Frames: ${FLUID.minFrames} to ${countText(Math.max(FLUID.minFrames, plateKeep(s, machine).frames))} at ${s.fps} fps, in steps of 8.`;

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
// The keyframe a click on the fluid shot's row goes to: the one nearest `frame`, the earlier one when two are as near.
export function nearestKey(frames, frame) {
  let best = null;
  for (const f of frames) {
    const d = Math.abs(f - frame), b = best === null ? Infinity : Math.abs(best - frame);
    if (d < b || (d === b && f < best)) best = f;
  }
  return best;
}
// The wipe's name for a History row's strokes: « Paint 2, strokes », « Fluid 1, keyframes ». `name`: the tool's name, `n`:
// the edit's number in History.
export const strokesLabel = (name, n, fluid) => `${name} ${n}, ${fluid ? "keyframes" : "strokes"}`;

// ---------- OCIO, as RV's menu shows it ----------

// The colour spaces as RV's OCIO menu builds its File Color Space tree (ocio_source_setup.py): each family path, such as
// "Input/ARRI", a submenu; the spaces in it; spaces without a family at the top. { name, children, spaces }
export function ocioTree(spaces) {
  const node = (name) => ({ name, children: new Map(), spaces: [] }), root = node("");
  for (const s of spaces) {
    let at = root;
    for (const part of (s.family || "").split("/").filter(Boolean)) at = at.children.get(part) ?? at.children.set(part, node(part)).get(part);
    at.spaces.push(s.name);
  }
  const plain = (n) => ({ name: n.name, children: [...n.children.values()].map(plain), spaces: n.spaces });
  return plain(root);
}

// ---------- The plate browser of the Open dialog ----------

// Folders first, then by name (numbers in order: shot2 before shot10) or newest first; `query` keeps names that contain it
export function browseItems(items, { query = "", by = "name" } = {}) {
  const q = query.trim().toLowerCase(), name = (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });
  return items.filter((i) => !q || i.name.toLowerCase().includes(q)).sort((a, b) =>
    (a.kind === "folder") !== (b.kind === "folder") ? (a.kind === "folder" ? -1 : 1) : by === "newest" ? b.mtime - a.mtime || name(a, b) : name(a, b));
}

// A path on the machine itself, outside ComfyUI's folders: absolute, or in Windows' form (folders.absolute).
const FULL = /^(\/|[A-Za-z]:[\\/])/;
export const fullPath = (path) => FULL.test(String(path ?? ""));
// A page path as breadcrumbs, the root first: "output:video/shot" gives Output, video, shot, each with the path it opens
export function crumbs(path) { // the Open dialog's trail: Input or Output and the folders below, or for a full path the machine's own folders
  const full = FULL.exec(path);
  if (full) {
    const root = full[0], sep = root.length > 1 && root.endsWith("\\") ? "\\" : "/", parts = path.slice(root.length).split(/[\\/]/).filter(Boolean);
    return [{ label: root.length > 1 ? root.slice(0, 2) : "This machine", path: root }, ...parts.map((p, i) => ({ label: p, path: root + parts.slice(0, i + 1).join(sep) }))];
  }
  const out = path.startsWith("output:"), base = out ? "output:" : "", parts = path.slice(base.length).split("/").filter(Boolean);
  return [{ label: out ? "Output" : "Input", path: base }, ...parts.map((p, i) => ({ label: p, path: base + parts.slice(0, i + 1).join("/") }))];
}

// The frame pattern of a sequence from one of its file names: core's f_00001_.exr gives f_#####_.exr
export const framePattern = (name) => name.replace(/(\d+)(\D*)$/, (_, d, rest) => "#".repeat(d.length) + rest);

// What a failed step's ComfyUI message means, in one plain sentence. The page puts it after "<step> failed:", and the
// log keeps ComfyUI's own words.
const SAVED = { matte_a: "the clean matte", matte_b: "the paint matte", clean: "the clean plate pass", shot: "the shot", plate: "the fluid shot" };
export function plainError(message) { // a failure in plain words: why, the fact for the log; todo, the action for the status line
  const m = String(message ?? ""), again = "Press Generate to try again.";
  const says = (why, todo = again) => ({ why, todo });
  if (/out of memory|allocation on device/i.test(m)) return says("the GPU ran out of memory");
  if (/ComfyUI stopped answering/i.test(m)) return says("ComfyUI stopped answering", "Its terminal says why: most often the machine ran out of memory. Start ComfyUI again, then press Generate.");
  if (/No answer from ComfyUI|is not valid JSON|Unexpected end of JSON input|Failed to fetch|NetworkError/i.test(m)) return says("ComfyUI did not answer: it may be restarting, or the connection dropped");
  const empty = m.match(/(?:No image frames found in|Image sequence not found:) (\S+?)\.?(?:\s|$)/);
  if (empty) {
    const part = empty[1].split(/[\\/]/).filter(Boolean).find((p) => SAVED[p.replace(/_(\d+x\d+|full)$/, "")]);
    return says(`${part ? SAVED[part.replace(/_(\d+x\d+|full)$/, "")] : "the step before it"} saved no frames, so there was nothing to read`);
  }
  if (/leaves the ComfyUI folders|outside the output folder|Absolute plate paths/i.test(m)) return says("the file is outside ComfyUI's input and output folders");
  if (/Unsupported plate|Plate not supported/i.test(m)) return says("Paint a plate cannot read this kind of file");
  if (/value not in list|not found in list|failed validation|Missing nodes|does not exist in/i.test(m)) return says("a model or a node it needs is missing");
  if (/No such file|FileNotFound|not found/i.test(m)) return says("a file it needs is missing");
  if (/Upload failed/i.test(m)) return says("the browser could not send a picture to ComfyUI");
  return says("ComfyUI stopped with an error");
}

// The confirmation once the export is written: its headline, which the HUD and the status line show, then the writer's
// summary as detail lines for the log, each ending with one full stop whether it brings its own or not.
export function exportDone(text) {
  const details = String(text ?? "").split("\n").map((line) => line.trim().replace(/\.+$/, "")).filter(Boolean);
  return ["Export: done, in ComfyUI's output folder.", ...details.map((line) => `  ${line}.`)].join("\n");
}
export function logLevel(text) { // a log message's colour, from its words: red when a line starts « Error: », amber when one starts « Warning: »
  const starts = (word) => String(text).split("\n").some((line) => line.trimStart().startsWith(word));
  return starts("Error: ") ? "error" : starts("Warning: ") ? "warn" : "";
}

// What the status line shows once the log writes `text`, or null to leave it as it is. An error or a
// warning shows by its first line that starts with its word, in its colour (logLevel). A line that succeeds replaces a
// fault that is over (`shown`: the status line's level), in the normal colour, unless it is bookkeeping. Every other event
// reaches the status line from the code that makes it, with what to do next.
const BOOKKEEPING = /^(Frame cache|Viewer|Played|Memory profile|Working sizes|Native frames|Job index off)\b/;
export function statusOf(text, shown = "") {
  const lines = String(text).split("\n"), level = logLevel(text), word = level === "error" ? "Error: " : "Warning: ";
  if (level) return { text: lines.map((l) => l.trim()).find((l) => l.startsWith(word)), level };
  return shown && !BOOKKEEPING.test(lines[0]) ? { text: lines[0], level: "" } : null;
}

export function workflowClasses(prompt) { // the node classes an API workflow holds, once each, sorted
  return [...new Set(Object.values(prompt).filter((n) => n?.class_type).map((n) => n.class_type))].sort();
}

// History's row when the page asks for an object's name: what the prompt writer saw, when the edit holds it.
export function askedText(asked) {
  return typeof asked === "string" && asked ? `Needs its name (the prompt writer saw ${asked})` : "Needs its name";
}

// The native frames' failure is said once per cause: a message that names its file counts once for every file.
export const nativeCause = (message, path) => String(message).split(path).join("the file").trim();

// The log's export holds no path of the person's machine. A path under ComfyUI's folder (`folder`, from
// /paintaplate/version) is written from that folder, as output/paintaplate/…; any other absolute path by its last two
// parts. A Windows path counts: a drive (C:\ or C:/, in any case) or a share (\\server\share). The status line and the
// Log panel keep the full path, which the person needs there.
const PATH_START = String.raw`(?<=^|[\s"'«(=])`;
const ABSOLUTE = new RegExp(String.raw`${PATH_START}(?:[A-Za-z]:[\\/]|\\\\|/)[^\s"'«»<>|]+`, "g");
export function plainPaths(text, folder = "") {
  const base = String(folder || "").replace(/[\\/]+$/, ""), parts = base.split(/[\\/]+/).map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  const under = base ? new RegExp(PATH_START + parts.join(String.raw`[\\/]+`) + String.raw`[\\/]+`, /^(?:[A-Za-z]:|\\\\)/.test(base) ? "gi" : "g") : null;
  return (under ? String(text).replace(under, "") : String(text)).replace(ABSOLUTE, (path) => {
    const [, body, end] = path.match(/^(.*?)([.,;:!?)\]]*)$/), sep = body.includes("\\") ? "\\" : "/";
    return body.split(/[\\/]+/).filter((part) => part && !/^[A-Za-z]:$/.test(part)).slice(-2).join(sep) + end;
  });
}

// The full-precision frames' failure (app.fetchDeep): refused, unanswered or malformed, the cache stops (frames.fillDeep) and
// the viewer keeps the 8-bit movie. One line per source, an error, so the log and the status line show it in red.
export const deepStopped = (what, why) =>
  `Error: full-precision frames of ${what}: stopped (${String(why ?? "").replace(/\s+/g, " ").trim() || "no reason given"}). Viewer: 8-bit movie.`;

// The log's export: the text of <plate or scene>_log_<YYYYMMDD_HHMM>.txt, to share for troubleshooting. It holds the
// log and what ComfyUI reports of its versions and its machine (/system_stats): no command line, and its plate and log
// lines through plainPaths.
export function logReport({ version, build, stats, browser, address, memory, plate, lines, now, folder = "" }) {
  const sys = stats?.system ?? {}, two = (n) => String(n).padStart(2, "0"), devices = stats?.devices ?? [];
  const gb = (bytes) => (+bytes > 0 ? `${(bytes / 2 ** 30).toFixed(1)} GB` : "unknown");
  const when = `${now.getFullYear()}-${two(now.getMonth() + 1)}-${two(now.getDate())} ${two(now.getHours())}:${two(now.getMinutes())}`;
  return [
    `AInVFX Paint a plate ${version || "unknown"} (build ${build || "unknown"}).`, `Exported: ${when}, this machine's time.`, "",
    "Machine", `  ComfyUI: ${sys.comfyui_version || "unknown"}.`, `  Python: ${String(sys.python_version || "unknown").split(" ")[0]}.`,
    `  PyTorch: ${sys.pytorch_version || "unknown"}.`, `  Operating system: ${sys.os || "unknown"}.`,
    ...(devices.length ? devices.map((d, i) => `  GPU ${i}: ${d.name || "unknown"}, ${gb(d.vram_total)} of VRAM.`) : ["  GPU: none reported."]),
    `  RAM: ${gb(sys.ram_total)}.`, "",
    "Page", `  Browser: ${browser}.`, `  Address options: ${address || "none"}.`, `  Memory profile: ${memory || "unknown"}.`, "",
    "Plate", ...(plate.length ? plate.map((l) => `  ${plainPaths(l, folder)}`) : ["  No plate open."]), "",
    "Log", ...lines.map(([time, text]) => `${time}  ${plainPaths(text, folder).replaceAll("\n", `\n${" ".repeat(String(time).length + 2)}`)}`),
  ].join("\n") + "\n";
}

// The log's file name, in the browser's local time.
// A name in a file's name: letters A to Z, digits, « . », « - » and « _ », every other run of characters one « _ », none at
// either end. It names the zip, every file in it (routes.zip_name, the same rule) and the log's file.
export const fileStem = (name) => String(name ?? "").replace(/[^A-Za-z0-9._-]+/g, "_").replace(/^_+|_+$/g, "");
// The zip's name, without its extension: the stem, the render's version (v3, or fluid_v2 for a fluid shot alone), then what
// it holds beyond full size, so that two zips of one render never share a name: desk_v3, desk_v3_hdr, desk_v3_hdr_upscaled.
export const zipFileName = (stem, version, held = {}) => [fileStem(stem) || "no_plate", version, held.preview && "preview", held.hdr && "hdr", held.up && "upscaled"].filter(Boolean).join("_");
export function logFileName(plate, d) {
  const two = (n) => String(n).padStart(2, "0"), name = fileStem(plate) || "no_plate";
  return `${name}_log_${d.getFullYear()}${two(d.getMonth() + 1)}${two(d.getDate())}_${two(d.getHours())}${two(d.getMinutes())}.txt`;
}

// ---------- Upscale ----------
// Finish > Upscale: after the export, SeedVR2 7B restores it at the size asked for, up to 3840 x 2160. The rules of
// tests/upscale_plate.py, which runs the same workflows from a terminal (tests/test_upscale_rules.py keeps them equal).
// long: the target's long side; factor: SeedVR2 restores from at most the target divided by it; chunk: the frames it
// samples at once, and step the frames each further chunk adds (chunks share one latent frame); modelRam: the GB the 7B
// model holds in RAM on a GPU under bigVram GB; copies: the float32 copies of one frame at the target size a job holds,
// and composeCopies those of a job that also composes the upscaled result (Paint and Clean). On a 96 GB GPU with 131 GB of RAM,
// 121 frames at 3840 x 2160 in one job peaked at 108.3 GB for the plate and 116.8 GB for the layer, which composes: 9.2
// and 10.0 copies. A window of 21 frames on a 16 GB GPU held 8.
// most: the largest target, its long and short sides; sizes: the long sides the menu lists beside the plate's own; least:
// the smallest long side Custom… takes.
export const UPSCALE = { long: 3840, most: [3840, 2160], sizes: [2560, 3840], least: 640, factor: 3, chunk: 21, step: 20, modelRam: 15.7,
  bigVram: 32, copies: 8, composeCopies: 10 };
// The size a person asks for: { side, px }, side "long", "width" or "height". The default is 3840 px on the long side, and a
// scene saved before sizes, with the switch on (true), asks for it too.
export const UPSCALE_ASK = { side: "long", px: UPSCALE.long };
const roundEven = (x) => { const r = Math.round(x); return Math.abs(x % 1) === 0.5 && r % 2 ? r - 1 : r; }; // as Python's round()
const even = (x) => 2 * roundEven(x / 2);
// The asked side at its px and the other side from the plate's aspect, both in even numbers (a movie in 4:2:0 needs even
// sides), within UPSCALE.most with the aspect kept. A plate at least as large as a long side asked for keeps its size.
// A number is a long side.
export function upscaleTarget(width, height, ask = UPSCALE_ASK) {
  const a = typeof ask === "number" ? { side: "long", px: ask } : ask, wide = width >= height;
  if (a.side === "long" && Math.max(width, height) >= a.px) return [width, height];
  const side = a.side === "long" ? (wide ? "width" : "height") : a.side, [long, short] = UPSCALE.most;
  const mostW = wide ? Math.min(long, short * width / height) : Math.min(short, long * width / height);
  const px = Math.min(a.px, side === "width" ? mostW : mostW * height / width);
  return side === "width" ? [even(px), even(px * height / width)] : [even(px * width / height), even(px)];
}
// The sizes the Finish menu lists for a plate: its own, then each long side of UPSCALE.sizes that gives a larger size.
export function upscaleSizes(width, height) {
  const out = [{ ask: { side: "long", px: Math.max(width, height) }, size: [width, height] }];
  for (const px of UPSCALE.sizes) {
    const size = upscaleTarget(width, height, { side: "long", px });
    if (size[0] > out.at(-1).size[0]) out.push({ ask: { side: "long", px }, size });
  }
  return out;
}
// Finish > Upscale > Custom…: one number, the long side in px, from UPSCALE.least to UPSCALE.most's long side: the ask for
// that side, the width or the height (the other follows the plate, within UPSCALE.most), or null.
export function upscaleCustom(text, width, height) {
  const m = String(text ?? "").trim().match(/^\d+$/), px = m ? +m[0] : 0;
  return px >= UPSCALE.least && px <= UPSCALE.most[0] ? { side: width >= height ? "width" : "height", px } : null;
}
// The ask a scene holds under deliver.upscale: true, a scene saved before sizes, asks for the default; false when off.
export function upscaleAskOf(saved) {
  if (saved === true) return UPSCALE_ASK;
  const ok = saved && typeof saved === "object" && ["long", "width", "height"].includes(saved.side) && Number.isInteger(saved.px) && saved.px > 0;
  return ok ? { side: saved.side, px: saved.px } : false;
}
export function upscaleSource(width, height, [tw, th]) { // the size SeedVR2 restores from: [0, 0], the frames as they are, when the target is UPSCALE.factor times their size or more
  if (Math.max(width, height) * UPSCALE.factor <= Math.max(tw, th)) return [0, 0];
  return [2 * roundEven(tw / UPSCALE.factor / 2), 2 * roundEven(th / UPSCALE.factor / 2)];
}
// Frames per job on this machine, from the GB of RAM and VRAM ComfyUI reports: the whole shot when 90% of the RAM holds it,
// else the most that fit as whole chunks (21, 41, 61 frames and on): a part of a chunk samples in nearly the time of a
// whole one. Held aside: 2 GB, the shot at the plate's size, and the model on a GPU under bigVram GB. 21 frames on a 16 GB
// GPU under a 52 GB cap; one job for 121 frames on a 96 GB GPU with 131 GB of RAM, even at composeCopies.
export function upscaleWindow(ramGb, vramGb, [tw, th], [pw, ph], frames, copies = UPSCALE.copies) {
  const gb = 2 ** 30, held = (vramGb < UPSCALE.bigVram ? UPSCALE.modelRam : 0) + 2 + frames * pw * ph * 12 / gb;
  const fit = Math.trunc((0.9 * ramGb - held) / (copies * tw * th * 12 / gb));
  if (fit >= frames) return frames;
  return UPSCALE.chunk + UPSCALE.step * Math.max(0, Math.floor((fit - UPSCALE.chunk) / UPSCALE.step));
}
export const upscaleWindows = (frames, size) => // [first, count] of each job: windows that follow one another and share no frame
  Array.from({ length: Math.ceil(frames / size) }, (_, i) => [i * size, Math.min(size, frames - i * size)]);
// Seconds, from 121 frames of horse.mp4 at 3840 x 2160: a SeedVR2 pass took 1,332 s on a 16 GB GPU (six windows of 21
// frames) and 388 s on a 96 GB GPU (one job); each part Save Plate writes at 4K took 28.5 s and 27.4 s. Scaled by the
// target's pixels and the frames. Paint and Clean make two passes, the plate's and the layer's, and write three parts.
const UPSCALE_SECONDS = { small: { frame: 11.0, part: 28.5 }, large: { frame: 3.21, part: 27.4 } };
export function upscaleSeconds([tw, th], frames, { passes = 1, parts = 1, profile = "large" } = {}) {
  const t = UPSCALE_SECONDS[profile] ?? UPSCALE_SECONDS.large, scale = (tw * th) / (3840 * 2160);
  return scale * frames * (passes * t.frame + parts * t.part / 121);
}
// The folder of a plate's upscaled windows: one per plate, under a key of everything that changes their frames (the plate, its
// colour space and config, the sizes, the window, the format, the build), so a changed setting never adds frames to old
// windows, and the next export of this plate finds them through the job index. FNV-1a, 32 bits, in hex.
export function upscaleFolder(plateId, parts) {
  let h = 0x811c9dc5;
  for (const c of JSON.stringify(parts)) h = Math.imul(h ^ c.codePointAt(0), 0x01000193) >>> 0;
  return `paintaplate/${plateId}/upscale/${h.toString(16).padStart(8, "0")}`;
}
// The upscaled result is composed from the upscaled plate, layer and matte when it is in the plate's own colour space, so
// that its untouched pixels are the plate's (Paint and Clean). SDR to HDR's EXR frames regenerate every pixel: their result
// is restored itself, with its matte, and keeps its values above 1.0 everywhere.
export const upscaleKeeps = (tools, exr = false) => tools.length > 0 && !tools.includes("light") && !exr; // Paint and Clean keep the plate's untouched pixels, and their export
// writes the layer and the matte in the plate's own colour space: the upscaled plate, layer and matte come too. An EXR result of SDR to HDR is upscaled alone
// What the row says when the size asked for is no larger than the plate: the plate's own size, or a smaller one.
export function upscaleWhy(width, height, ask = UPSCALE_ASK) {
  const [tw, th] = upscaleTarget(width, height, ask), part = { 2: "half", 3: "a third of" }[UPSCALE.factor] ?? `1/${UPSCALE.factor} of`;
  if (tw > width || th > height) return "";
  const restore = `the result is brought down to ${part} that size, then SeedVR2 restores its detail. Every pixel is new.`;
  return tw === width && th === height ? `At the plate's own size, ${restore}` : `This size is smaller than the plate, so the frames come out smaller: ${restore}`;
}
// Finish > Upscale's note under its size list: about how long the upscaled set takes on this GPU, for the size chosen and
// the edits displayed (upscaleFigures).
export const upscaleNote = (seconds) => `About ${Math.max(1, Math.round(seconds / 60))} min on this GPU.`;

// The Finish menu: the passes on the whole plate after the full-size composite, in the order the render runs them. Each
// option: its id (its switch is #finish-<id>), its name, the line that says what it does to the result, and the question
// it asks before it turns on, when it changes what Export writes.
export const FINISH = [
  { id: "hdr", name: "SDR to HDR",
    line: "The result is made again with values above 1.0, matched to the plate. A plate that holds values up to 1.0 only, such as a movie, gives half-float EXR frames in ACES2065-1.",
    ask: "This plate holds values up to 1.0 only. With SDR to HDR, the result becomes half-float EXR frames in ACES2065-1, in the viewer and in Export." },
  { id: "upscale", name: "Upscale",
    line: "The render's last step: SeedVR2 7B upscales the result to the size chosen, including layers and mattes. The player shows it, and Export writes it." },
];
// The Render panel's rows in the order things happen: the steps done, in the order they finished (a step reused from an
// earlier render is done at once, so it comes first), then the step running, then the steps to come in their planned
// order. steps: ids in plan order; done(id): it finished; at(id): its place in the order steps finished, if known; now: the
// id running, or null. A step done with no place known (made before this page) keeps its place among the done ones.
export function stepOrder(steps, { done, at = () => undefined, now = null }) {
  const rank = (id) => (done(id) ? [0, at(id) ?? 0] : id === now ? [1, 0] : [2, 0]);
  return steps.map((id, i) => ({ id, i, k: rank(id) })).sort((a, b) => a.k[0] - b.k[0] || a.k[1] - b.k[1] || a.i - b.i).map((x) => x.id);
}

// The Export dialog's words for every kind of result, from one source: the line above its ticks, each element's label and
// detail (What), each stage's label (Stage), the note under them, and the Help's Export entry. kind: "edits", "plate" (SDR
// to HDR on the plate, with no edit), "relit" (a Light edit in HDR), "upscaled" (the plate alone, upscaled) or "fluid".
// ready: what Export takes its files from is made; left: the time until it is, such as "about 10 min", or "". hdr: the
// fluid shot went through SDR to HDR. steps.comp: the composite at full size, as the Render panel names it (app.labelOf).
// bytes: the source plate's size, once known.
export const EXR_FRAMES = "half-float EXR frames, ACES2065-1";
export function exportWords({ kind, ready = true, left = "", hdr = false, steps = {}, bytes = 0 }) {
  const first = (step) => `${step} first${left ? `: ${left}` : ""}.`, inHdr = (what) => (ready ? `${what} in HDR.` : `${what} in HDR. ${first("SDR to HDR runs")}`);
  const note = kind === "fluid" ? (hdr ? `The fluid shot in HDR, with the SDR shot in ${XQ}.` : `The fluid shot in ${XQ}.`)
    : kind === "plate" ? inHdr("The plate") : kind === "relit" ? inHdr("The relit result") : kind === "upscaled" ? (ready ? "" : first("Upscale runs"))
    : ready ? "" : first(`${steps.comp} renders`);
  const hint = "Export writes the selected files to ComfyUI's output folder, then downloads them as one zip.";
  const elements = { plate: { label: "Plate", detail: bytes > 0 ? `the plate under the edits, ${gb(bytes)}` : "the plate under the edits" },
    shot: { label: "Shot", detail: "the frames the model made" }, layer: { label: "Layer", detail: "the shot as the composite blends it" },
    matte: { label: "Matte", detail: "where the plate changed, 16-bit PNG frames" }, composite: { label: "Composite", detail: "the result" },
    graph: { label: "ComfyUI graph", detail: "the scene as one ComfyUI workflow, with the images it loads" } };
  const stages = { preview: { label: "Preview" }, full: { label: "Full size" }, hdr: { label: "HDR" }, up: { label: "Upscaled" } };
  return { hint, note, elements, stages, help: `${hint} Frames keep their format, and a movie gives ${XQ}. With SDR to HDR, a plate that holds values up to 1.0 only, such as a movie, gives half-float EXR frames.` };
}
// The folder of a set of elements (the Finish layout): a Finish pass writes its set inside the folder of the set it reads,
// so SDR to HDR's set is <run>/hdr, Upscale's <run>/upscale/<size>/out, and Upscale's of SDR to HDR's set
// <run>/hdr/upscale/<size>/out. Finish's steps write by it, and Export reads by it (app.exportCells).
export const setFolder = (run, { hdr = false, size = "" } = {}) => [run, hdr && "hdr", size && `upscale/${size}/out`].filter(Boolean).join("/");
// Export's ticks: the elements (What) and the stages (Stage), in the dialog's order. The zip takes every element ticked at
// every stage ticked that the render has a file for: a cell (app.exportCells) is one element at one stage, with its label,
// its file, and whether it is the source plate's own files (source).
export const X_ELEMENTS = ["plate", "shot", "layer", "matte", "composite"];
// The labels of the cells the Render panel has no step for (app.exportCells): they name the files in the zip (zipName) and
// the download's lines; Finish's sets take its own labels.
export const X_LABELS = { source: "Source plate", matte: "Matte", mattePreview: "Matte, preview", layer: "Layer, full size", shotHdr: "Shot, HDR",
  plateHdr: "Plate, HDR", layerHdr: "Layer, HDR", compHdr: "Composite, HDR", plateHdrUp: "Plate, HDR, upscaled", compHdrUp: "Composite, HDR, upscaled" };
export const X_STAGES = ["preview", "full", "hdr", "up"];
// The ticks the dialog shows: an element, or a stage, that has no cell for the render has no tick.
export const xShown = (cells) => ({ elements: new Set(cells.map((c) => c.element)), stages: new Set(cells.map((c) => c.stage)) });
// The ticks set as the dialog opens: the result (`first`: the composite, or the plate when it is all there is) at the last
// stage the render has for it: Upscaled, else HDR, else Full size, else Preview.
export function xDefaults(cells, first) {
  const of = cells.filter((c) => c.element === first), stage = ["up", "hdr", "full", "preview"].find((s) => of.some((c) => c.stage === s));
  return { elements: new Set([first]), stages: new Set(stage ? [stage] : []) };
}
// The zip's rows for the ticks: each cell of a ticked element at a ticked stage, once by its name in the zip, as
// [name, label, file, source]. The matte is one picture at full size and in HDR, so it comes once.
export function xRows(cells, { elements, stages }) {
  const seen = new Set();
  return cells.filter((c) => elements.has(c.element) && stages.has(c.stage)).map((c) => [zipName(c.source ? X_LABELS.source : c.label), c.label, c.file ?? null, !!c.source])
    .filter(([name]) => !seen.has(name) && seen.add(name));
}
// A row's name in the zip: its label in lower case, its words joined by « _ », so the zip's names follow the dialog's words.
export const zipName = (label) => String(label ?? "").toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "");
// The format of the files the export writes, as the dialog, the Help, the status line and the graph's notes name it: a
// sequence keeps its own file type, and every movie is ProRes 4444 XQ (plateio.VideoWriter). spec: the plate's spec.
export const XQ = "ProRes 4444 XQ";
export const exportFormat = (spec) => (!spec ? "" : spec.kind === "video" ? XQ : `${String(spec.ext ?? "").replace(/^\./, "").toUpperCase()} frames`);
// What the log says once the zip downloads: its name, then one detail line per row the zip holds, in the dialog's words.
export function downloadLines(zip, labels) {
  return [`Download: ${zip}.`, ...[...new Set(labels)].map((label) => `  ${label}.`)].join("\n");
}
// The line when a file the ticks ask for is not on disk: Export stops before its download (app.download).
export const missingLine = (labels) => `Error: Export stopped: ${labels.length === 1 ? labels[0] : `${labels.slice(0, -1).join(", ")} and ${labels.at(-1)}`} ${labels.length === 1 ? "has" : "have"} no file on disk.`;
// The page path of a file that ComfyUI's /view serves from its output folder (comfy.viewUrl), or null.
export function outputPath(url) {
  const q = new URLSearchParams(String(url ?? "").split("?")[1] ?? "");
  return q.get("type") === "output" && q.get("filename") ? `output:${[q.get("subfolder"), q.get("filename")].filter(Boolean).join("/")}` : null;
}
export const finishLabel = (on) => (on > 0 ? `Finish · ${on}` : "Finish"); // the Finish button: how many options are on

// What to do when a line names a missing file of models/vae_approx, which holds the live preview's decoder that
// get_models.py downloads: the status line adds it after the line, and the log keeps the fact.
export const missingFileHint = (text) => (/models\/vae_approx/.test(String(text).split("\n")[0]) ? "Run python get_models.py." : "");

// One edit at a time: the strokes in progress, else the current edit (the one just started, or picked in History).
export function strokeTarget({ draft, current, tool }) { // where a new stroke goes: "draft", "current" or "new"
  if (draft) return "draft";
  return current?.tool === tool ? "current" : "new";
}

// The status line's note while an edit with active edits above it changes: the first frame shows the edits below it only,
// so the note names the edits it hides and the way back. `n`: the edit's number; `above`: the numbers of the hidden edits.
export function hidesNote(n, above) {
  if (!above.length) return "";
  const names = above.length === 1 ? `Edit ${above[0]} hides` : `Edits ${above.slice(0, -1).join(", ")} and ${above.at(-1)} hide`;
  return `Edit ${n} changes: ${names} until Generate. Esc cancels the change.`;
}

export function toolEndsEdit({ draft, current }, tool) { // picking another tool than the edit being worked on starts a new edit
  const work = draft ?? current;
  return !!work && work.tool !== tool;
}

// The eraser's key, E. Held while a stroke is dragged, the eraser lasts as long as the key is down; a tap, shorter than
// ERASER_TAP seconds with no stroke, switches it on or off. The eraser's state once the key comes up.
export const ERASER_TAP = 0.3;
export function eraserAfterKey(was, held, dragged) { return !dragged && held < ERASER_TAP ? !was : was; }
// The OCIO menu's line for the plate: its colour space, then « from file » for the file's own, or « override ».
export function plateSpaceLine(plate) {
  return plate ? `Colour space: ${plate.cs}, ${plate.pageSpaceChosen ? "override" : "from file"}` : "Colour space: no plate";
}
// The one question before an OCIO change that regenerates: the cause and the cost, then the question, answered « Yes, continue » or « No, keep it » (app.askRemake).
// `what`: « plate's colour space » or « OCIO config ». The first frame is the page's own step: the question counts the edits.
export function remakeQuestion(what, edits) { return `Changing the ${what} affects generation: ${edits} edit${edits === 1 ? "" : "s"} will be regenerated. Continue?`; }
// The HUD's line when a fluid keyframe moves to the nearest frame it can sit on; `frame` is the plate's own number
export const keyframeSlotLine = (frame) => `Keyframes snap to the first frame, the last frame or every 8 frames between: frame ${frame}.`;

// A family of the plate's colour-space tree, named for a person. The config's « Display », the spaces encoded for a
// display, reads « Display-referred ». « ITU » is spelled out: the International Telecommunication Union publishes the
// « Rec. » standards, such as Rec.709 and Rec.2020. RV and Nuke show the config's own names. The spaces keep theirs.
const FAMILIES = { Display: "Display-referred", ITU: "ITU (International Telecommunication Union)" };
export function plateFamily(name) { return FAMILIES[name] ?? name; }
// An image that the scene's ComfyUI graph reads. It sits at the top of ComfyUI's input folder: LoadImage lists only the files
// there, and the editor marks an image input whose file is not in that list as missing. Named after the export's stem (the
// plate's or the scene's name), the edit, what it holds and its hash, so two scenes never share a name; the export's zip
// holds it under the same name, in input/ (routes.graph_images).
export function graphImageName(name, edit, kind, hash) {
  const stem = String(name || "").replace(/[^A-Za-z0-9-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "plate";
  return `${stem}_e${edit}_${kind}_${String(hash).slice(0, 8)}.png`;
}

export function fluidPrompt(words) { // the trigger first, as the model card asks; no words: its own example
  const rest = (words || "").trim().replace(/^ainvfxfluid\s*,?\s*/i, "");
  return `${FLUID.trigger}, ${rest || FLUID.prompt}`;
}

// The paint matte's seed: the pixels where the edited first frame (a) differs from the plate's (b) by more than
// `threshold` (0 to 255, on the largest channel), inside the paint zones (z, white). RGBA arrays of one size; 1 or 0 per
// pixel. The zone is wider than what was painted, and a matte started from all of it follows whatever stands nearby.
export function changedMask(a, b, z, threshold = 24) {
  const n = a.length >> 2, out = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    const j = i * 4;
    if (z[j] < 128) continue;
    if (Math.max(Math.abs(a[j] - b[j]), Math.abs(a[j + 1] - b[j + 1]), Math.abs(a[j + 2] - b[j + 2])) > threshold) out[i] = 1;
  }
  return out;
}

// An erase that left its object. Klein can answer an erase with the frame as it was: a stroke on a barn with no words,
// given the page's own caption, can leave the barn through the whole shot. So after the edit the page
// compares the first frame (`after`) with the frame under the edit (`before`) inside the object's mask (`mask`: painted
// where its red is 128 or more), all three RGBA at `w` x `h`, on cells of `cell` pixels. A cell's mean colour holds under
// Klein's softness and under the few levels its fill can sit off the frame (4 to 6, measured for Level Fill), and it
// moves when the object goes. Returns the share of the object, from 0 to 1, whose cells moved by more
// than `levels` of 255; null when the mask is empty.
export function erasedShare(after, before, mask, w, h, { cell = 4, levels = 12 } = {}) {
  let all = 0, changed = 0;
  for (let top = 0; top < h; top += cell) for (let left = 0; left < w; left += cell) {
    let n = 0, r = 0, g = 0, b = 0;
    for (let y = top; y < Math.min(h, top + cell); y++) for (let x = left; x < Math.min(w, left + cell); x++) {
      const j = (y * w + x) * 4;
      if (mask[j] < 128) continue;
      n++; r += after[j] - before[j]; g += after[j + 1] - before[j + 1]; b += after[j + 2] - before[j + 2];
    }
    if (!n) continue;
    all += n;
    if (Math.max(Math.abs(r), Math.abs(g), Math.abs(b)) / n > levels) changed += n;
  }
  return all ? changed / all : null;
}

// Whether an erase removed its object, as the page judges it (eraseCheck): the share of the object's cells moved by more
// than 24 levels, and how well its edges held. On 21 erases, what went had 53 to 78% of its cells moved and its edges at
// -0.03 to 0.75 (a fence in front of the object kept some); what stayed had 0 to 1% and 0.93 to 0.98; a tree half changed
// had 17% and 0.62. A rule of under 2% at 12 levels lets through an object that Klein only recoloured (59% of its cells
// moved). So an object is left when under 30% of it changed, or when its edges held above 0.85. A null figure: nothing to judge by it.
export const objectLeft = ({ changed, edges }) => changed !== null && (changed < 0.3 || (edges !== null && edges > 0.85));

// The correlation of the gradient's size inside the mask, before and after: 1, the same edges; near 0, none of them. Gray is the
// mean of red, green and blue; the gradient takes the next pixel across and below (none past the last). null: under 16
// pixels, or a flat image.
export function edgesHeld(after, before, mask, w, h) {
  const gray = (a, k) => (a[k] + a[k + 1] + a[k + 2]) / 3;
  const grad = (a, x, y, j) => Math.hypot(x + 1 < w ? gray(a, j + 4) - gray(a, j) : 0, y + 1 < h ? gray(a, j + 4 * w) - gray(a, j) : 0);
  let n = 0, sa = 0, sb = 0, saa = 0, sbb = 0, sab = 0;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const j = (y * w + x) * 4;
    if (mask[j] < 128) continue;
    const a = grad(after, x, y, j), b = grad(before, x, y, j);
    n++; sa += a; sb += b; saa += a * a; sbb += b * b; sab += a * b;
  }
  const va = saa - (sa * sa) / n, vb = sbb - (sb * sb) / n;
  return n < 16 || va <= 0 || vb <= 0 ? null : (sab - (sa * sb) / n) / Math.sqrt(va * vb);
}

function grownBy(m, w, h, reach) { // `m` (0 or 1 per pixel) grown by `reach` pixels each way, as a square brush
  const rows = new Uint8Array(w * h), out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (m[y * w + x]) rows.fill(1, y * w + Math.max(0, x - reach), y * w + Math.min(w - 1, x + reach) + 1);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (rows[y * w + x]) for (let k = Math.max(0, y - reach); k <= Math.min(h - 1, y + reach); k++) out[k * w + x] = 1;
  return out;
}

// The band that an erase reaches beyond its object: the object's mask grown by `reach` pixels each way, as a square (along
// the rows, then the columns, never past the frame's edge), without the mask itself. The edit's mask grows by about as much
// before Klein's pass (app.editSettings: grow, then feather). mask: RGBA at w x h, painted where its red is 128 or more.
// Returns RGBA, white in the band, as erasedShare and edgesHeld read a mask.
export function bandBeyond(mask, w, h, reach) {
  const m = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) m[i] = mask[i * 4] >= 128 ? 1 : 0;
  const grown = grownBy(m, w, h, reach), band = new Uint8ClampedArray(w * h * 4);
  for (let i = 0; i < w * h; i++) if (grown[i] && !m[i]) band.fill(255, i * 4, i * 4 + 4);
  return band;
}

// ---------- An erase's cast shadow ----------
// Clean that takes the whole object takes its cast shadow too, when the prompt writer's caption cites one (« the dark cast
// shadow <shadow_1> »). SAM 3.1 finds the shadows by that word; the object keeps those that meet the caption's box for its
// shadow and touch its mask (within 1% of the frame's width) or lie under it (their middle below the object's, within its
// width). A mask over three times the object's area is the scene's shade, not the object's shadow.
export function shadowBox(text) { // the box of the shadow row that the caption cites, [y_min, x_min, y_max, x_max] on 0..1000, or null
  const [caption, rows] = splitTable(String(text ?? ""));
  const row = (rows ?? []).find((r) => r && /shadow/i.test(`${r.id ?? ""} ${r.desc ?? ""}`) && caption.includes(`<${r.id}>`) && validBox(r.src_bbox));
  return row ? row.src_bbox : null;
}

export function shadowOf({ object, shadows, box, w, h }) { // { bits, share } of the shadow that joins the object, or null
  const n = count(object);
  if (!n || !box) return null;
  let x0 = w, x1 = -1, sy = 0;
  for (let i = 0; i < w * h; i++) if (object[i]) { const x = i % w; x0 = Math.min(x0, x); x1 = Math.max(x1, x); sy += Math.floor(i / w); }
  const near = grownBy(object, w, h, Math.max(1, Math.round(0.01 * w))), [by0, bx0, by1, bx1] = box.map((v, k) => (v / 1000) * (k % 2 ? w : h));
  const kept = shadows.filter((m) => {
    let c = 0, mx = 0, my = 0, touches = false, inBox = false;
    for (let i = 0; i < w * h; i++) {
      if (!m[i]) continue;
      const x = i % w, y = Math.floor(i / w);
      c++; mx += x; my += y;
      touches ||= near[i] === 1;
      inBox ||= x >= bx0 && x < bx1 && y >= by0 && y < by1;
    }
    return c > 0 && c <= 3 * n && inBox && (touches || (my / c > sy / n && mx / c >= x0 && mx / c <= x1));
  });
  if (!kept.length) return null;
  const bits = new Uint8Array(w * h);
  for (const m of kept) for (let i = 0; i < w * h; i++) if (m[i]) bits[i] = 1;
  let added = 0;
  for (let i = 0; i < w * h; i++) if (bits[i] && !object[i]) added++;
  return { bits, share: added / n };
}

// An erase that took more than its object: Klein can remove a neighbour with it, as a fence in front of a barn. On the probes'
// results on horse.mp4 at the edit preview's size (768 x 432, a band of 22 px), the result that removed the fence with the
// barn moved 32% of the band's cells by more than 24 levels; every other result, 6.1% at most. The mock's Klein moves 3.5
// to 16.4% there. So an erase is held back when over 20% of the band beyond its object changed.
export const BEYOND = 0.2;

// The check after an erase, one pure function for the page and for the tests on a GPU: the first frame after the edit
// (`after`), the frame under it (`before`) and the object's mask, all three RGBA at w x h. { changed, edges, left }. With
// `reach`, the band beyond the object in pixels (bandBeyond), it also gives that band's two measures and why the erase is
// held back: « object » when the object may still be there, « beyond » when over BEYOND of the band changed, else null.
export function eraseCheck(after, before, mask, w, h, reach = 0) {
  const changed = erasedShare(after, before, mask, w, h, { levels: 24 }), edges = edgesHeld(after, before, mask, w, h);
  const left = objectLeft({ changed, edges });
  if (!(reach > 0)) return { changed, edges, left };
  const band = bandBeyond(mask, w, h, reach);
  const beyond = erasedShare(after, before, band, w, h, { levels: 24 }), beyondEdges = edgesHeld(after, before, band, w, h);
  return { changed, edges, left, beyond, beyondEdges, why: left ? "object" : beyond !== null && beyond > BEYOND ? "beyond" : null };
}

// The log's detail line under an erase that passed the check: what changed around its object (eraseCheck's band).
export const beyondDetail = ({ beyond, beyondEdges }) => (beyond === null || beyond === undefined ? "" :
  `\n  Around the object: ${Math.round(beyond * 100)}% changed${beyondEdges === null ? "" : `, edges held at ${beyondEdges.toFixed(2)}`}.`);

// What to do next, for the status line: an object with no name gets one; a named object gets other words or another seed.
export const leftHint = (words) =>
  (words ? "Use another text prompt, then Generate, or Ctrl+Enter for another seed." : "Type its name in the text prompt, then Generate.");

// What the page says when the check holds an erase back. The check can be wrong on a thin or faint object, or on one behind a
// fence, so the page asks: `fact`, a warning, goes to the log once and, after « No, cancel », to the status line before leftHint;
// `question` opens the dialog, where « Yes, render anyway » keeps the first frame and renders its shot; `rendered` is the log's
// line then. A figure the check could not measure (null) is left out.
export function leftLines(n, check) {
  if (check.why === "beyond") { // the object went, and the area around it changed too much: « of that area », so no reader takes it for the object's figure
    const figures = [`${Math.round(check.beyond * 100)}% of that area changed`, check.beyondEdges === null ? "" : `edges held at ${check.beyondEdges.toFixed(2)}`];
    const around = `the erase also changed the area around the object (${figures.filter(Boolean).join(", ")})`;
    return { fact: `Warning: edit ${n}, ${around}.`, question: `Edit ${n}: ${around}. Render the shot anyway?`,
      rendered: `Edit ${n}: kept at your request. The check found the area around the object changed.` };
  }
  const { changed, edges } = check;
  const figures = [changed === null ? "" : `${Math.round(changed * 100)}% of it changed`, edges === null ? "" : `edges held at ${edges.toFixed(2)}`];
  const there = `the object may still be there${figures.some(Boolean) ? ` (${figures.filter(Boolean).join(", ")})` : ""}`;
  return { fact: `Warning: edit ${n}, ${there}.`, question: `Edit ${n}: ${there}. Render the shot anyway?`,
    rendered: `Edit ${n}: kept at your request. The check found the object still there.` };
}

// A divider's drag as a size the layout can take: never under the panel's least, and never leaving the stage under its own
// least while the window has room. `kind` "side" sizes across the window's width, "log" down its height; `around` is what
// the fixed parts take on that axis (the tools column, or the top bar and the log's status row).
export function panelSize(kind, wanted, view, { least, stage, around }) {
  const room = (kind === "side" ? view.width : view.height) - around - stage;
  return Math.round(Math.max(least, Math.min(wanted, room)));
}

// ---------- A plate's name ----------
// The name the page, scenes and exports give a plate: its file name without the extension and, for an image sequence only,
// without the frame number. Trailing digits are a frame number only in an image sequence: « train_v2.mp4 » is train_v2 and
// « room.1001.exr » is room. Read as a frame number, the digits would show train_v2.mp4 and chalet_v2.mp4 as « train_v » and
// « chalet_v », so two movies could share a name in the page, in scenes and in exports.
export function plateStem(file, sequence) {
  const base = String(file ?? "").split(/[\\/]/).pop().replace(/\.[^.]+$/, "");
  return (sequence ? base.replace(/[._]?\d+$/, "") : base) || "plate";
}

// ---------- The model warm-up ----------
// warmAll's last line. It goes to the status line only while that line still says what the page said at start: once a plate
// was opened or closed, the status line holds a newer message, and the log keeps this one. A warm-up job that an opening, an
// edit or a close cancelled (stopEverything) has not loaded its model, so the line then says so, never « every model loaded ».
// A close that cancels the warm-up's last job shows « Plate closed », never « Ready: every model loaded ».
export function warmEnd(seconds, missed, startShown) {
  const s = Math.round(seconds);
  if (missed) return { status: false, text: `Model warm-up done in ${s} s: ${missed} of its jobs did not finish, so the first edit loads their models.` };
  if (startShown) return { status: true, text: `Ready: every model loaded in ${s} s. The first edit starts immediately.`, next: "Open a plate." };
  return { status: false, text: `Model warm-up done in ${s} s: every model loaded.` };
}

// ---------- SDR to HDR ----------
// Lightricks' LTX 2.5 SDR-to-HDR IC-LoRA makes 16-bit HDR from an SDR shot, at full size. It is on by default for a plate
// with float samples, such as EXR (plateDepth's `hdr`); on another plate, the Finish menu turns it on. On a plate that holds values above 1.0, a
// relight keeps the plate's own values under a smooth light ratio, which stay HDR, so a render with a light edit leaves it
// out; on another plate, SDR to HDR runs on the relit composite instead (hdrAfterComposite). A blank plate asks its bit depth: 8-bit, or 16-bit half float, where its
// fluid shot goes through it and becomes an EXR plate: 16-bit is the default once its files are found (?hdr=0 turns it off).
export const HDR_DEPTH = 16;
// New content at the plate's bit depth: a clean plate or a new element matches the plate. One rule per
// kind of plate, read from its pixel format: `bits` (16 for half float, 32 for float), `frames`, the Save Frames format
// a shot's frames pass through on their way to the export, and `hdr`, whether SDR to HDR is on by default. Its switch
// shows for every plate:
//   8-bit video or images: 8-bit PNG frames; SDR to HDR off by default.
//   10-bit or 12-bit video (ProRes among them), 16-bit PNG and TIFF, 10-bit DPX: 16-bit PNG frames; off by default.
//   Half and float samples (EXR, and a float TIFF or DPX: FFmpeg's decoders read 32-bit float): half-float EXR frames; on by
//   default.
export function plateDepth(spec) {
  const fmt = String(spec?.pix_fmt ?? "").toLowerCase(), exr = !!spec && spec.kind !== "video" && /^\.exr$/i.test(spec.ext ?? "");
  const float = exr || /f(16|32)(le|be)?$/.test(fmt);
  const bits = /f32/.test(fmt) ? 32 : exr || /f16/.test(fmt) ? 16 : /(rgba?|bgra?)64|(rgb|bgr)48|gray16|ya16/.test(fmt) ? 16
    : +(fmt.match(/p(\d+)(le|be)$/)?.[1] ?? 8);
  return { bits, float, frames: float ? "exr" : bits > 8 ? "png16" : "png", hdr: float };
}
// Whether a plate's own format holds the values above 1.0 that SDR to HDR makes: float samples do, and so does a plate whose
// colour space decodes code value 1.0 above 1.0 (`headroom`, from the stat route: 222.9 for ACEScct, 100 for PQ, 1.0 for
// sRGB), video or not: an HDR video in PQ or HLG, a log video, a 10-bit Cineon DPX, a camera log TIFF. Such a plate exports
// in its own format with no extra files; only the others warn first and deliver an EXR sequence.
export const holdsHdr = (spec, headroom = 1) => !!spec && (plateDepth(spec).float || headroom > 1.001);
export const wantsHdr = (spec, tools, on) => !!spec && !!on && !tools.includes("light");
// SDR to HDR on the composite, once it is made: a set with a Light edit, on a plate whose format holds nothing above 1.0, when
// SDR to HDR is on. Relight Transfer relights the plate's own pixels, and the shot's HDR frames reach the result only inside
// the mattes, so the new light would stay SDR: the relit composite goes through SDR to HDR whole, as a plate with no edit
// does (app.plateHdr), and its frames are the result. So does a set over a fluid shot, whose plate is generated: the fluid
// shot goes through SDR to HDR with the edits on it. A plate that holds values above 1.0 keeps them under the relight.
export const hdrAfterComposite = (spec, tools, on, headroom = 1) => !!spec && !!on && (tools.includes("light") || tools.includes("fluid")) && !holdsHdr(spec, headroom);
// The switch away from the plate's default makes another render, so each setting keeps its own: "|hdr" or "|sdr".
export const hdrKey = (edits, dflt, on) => (on === dflt ? edits : `${edits}|${on ? "hdr" : "sdr"}`);
export const hdrOfKey = (key, dflt) => (key?.endsWith("|hdr") ? true : key?.endsWith("|sdr") ? false : dflt);
// The render key of what is displayed: the edits' key (hdrKey). A plate with no edit has a render only when the Finish menu asks
// SDR to HDR of a plate whose format holds nothing above 1.0: the key PLATE_ALONE, whose one step is SDR to HDR on the plate.
export const PLATE_ALONE = "|hdr";
// Finish > Upscale on a plate with no edit and no SDR to HDR: the key PLATE_UP, whose one step upscales the plate itself.
export const PLATE_UP = "|up";
export const renderKey = (edits, dflt, on, up = false) => (edits ? hdrKey(edits, dflt, on) : on && !dflt ? PLATE_ALONE : up ? PLATE_UP : "");
export const plateAlone = (key) => key === PLATE_ALONE || key === PLATE_UP;
// SDR to HDR on a plate whose format cannot hold values above 1.0: asked before it turns on, then the result is
// an EXR sequence, which the player shows at full precision and the export writes.
export const exrResult = (spec, hdrRan, headroom = 1) => !!hdrRan && !holdsHdr(spec, headroom);
// SDR to HDR for a render: on its own when the plate holds values above 1.0, else when the Finish menu turns it on (deliverHdr)
export const wantsHdrFor = (spec, headroom, deliverHdr) => holdsHdr(spec, headroom) || !!deliverHdr;
// On a 32 GB GPU every step finishes at 1920 x 1088 x 121, slower than on 96 GB, but a 4K plate does not (its first erase
// still runs after 30 minutes on an RTX 5090). A plate above 2K on a GPU under 48 GB warns when it opens: a 48 GB GPU
// reports about 47.5 GiB, a 40 GB one about 39.6.
export const BIG_PLATE = { side: 2048, vram: 46 * 2 ** 30 };
export const bigPlateWarning = (spec, vram) => (spec && vram > 0 && Math.max(spec.width, spec.height) > BIG_PLATE.side && vram < BIG_PLATE.vram
  ? `Warning: this plate is ${spec.width} x ${spec.height}, above 2K, and this GPU has ${Math.round(vram / 2 ** 30)} GB of VRAM. A plate above 2K needs a 96 GB GPU: its renders may run out of memory here.`
  : null);
// ---------- How much of a plate opens: LTX 2.5's 20 seconds ----------
// LTX 2.5 places each frame at its time in seconds, its number divided by the frame rate, and its positions span 20 s in
// time and 2048 px in space (positional_embedding_max_pos, [20, 2048, 2048], in ComfyUI's comfy/ldm/lightricks/av_model.py).
// Every LTX pass runs at the working size, 1920 px at most, so only the time limits a shot: 20 s from its first frame to
// its last, at any frame rate. A plate opens with the longest 8k + 1 count within the 20 s, so the padding LTX needs adds
// no frame past them: 481 frames at 24 fps, 497 at 25, 601 at 30, 1001 at 50. `most` is the largest 8k + 1 count that
// every node of the pack takes (4,096 frames, nodes.py).
export const LENGTH = { seconds: 20, most: 4089 };

export function plateLength(fps) { // the frames a plate at `fps` opens with, and whether LTX 2.5's 20 s sets them
  const rate = +fps > 0 ? +fps : 24, timed = Math.max(1, Math.floor(LENGTH.seconds * rate + 1 + 1e-9)), most = Math.min(LENGTH.most, timed);
  return { frames: most - ((most - 1) % 8), byTime: timed <= LENGTH.most };
}

// A count as a person reads it: thousands take a comma (« 1,001 frames »). A frame number is the plate's own and takes none.
export const countText = (n) => Number(n).toLocaleString("en-CA");

// ---------- How much of a plate this machine holds ----------
// Every step holds the plate's frames in float32, several times over. On an RTX PRO 6000 pod (96 GB of VRAM, a container of
// 175 GB of RAM), the export of a 1920 x 1080 plate of 497 frames with SDR to HDR on held 14 copies of it (165.3 GB), and
// the clean plate pass of a 3840 x 2160 plate of 121 frames 14.2 (164 GB): FIT.copies at the plate's own size covers each
// step. ComfyUI also holds FIT.held GB besides the frames: 5 where every model stays in VRAM (large); 12 on a 16 GB GPU
// under a 52 GB cap, where 121 frames at 1920 x 1080 peaked at 51 GB (small; medium counts as small until it is measured).
// A plate opens with no more frames than FIT.share of the RAM that ComfyUI reports holds through every step.
export const FIT = { copies: 14, share: 0.99, held: { small: 12, medium: 12, large: 5 } };
export function framesFit(width, height, ram, profile = "small") { // the most frames, as 8k + 1; LENGTH.most when ComfyUI reports no RAM
  if (!(ram > 0 && width > 0 && height > 0)) return LENGTH.most;
  const room = FIT.share * ram - (FIT.held[profile] ?? FIT.held.small) * 2 ** 30;
  const n = Math.min(LENGTH.most, Math.floor(room / (FIT.copies * width * height * 12)));
  return n < 1 ? 1 : n - ((n - 1) % 8);
}
// The frames a plate opens with, and what sets them: "time", LTX 2.5's 20 s at its frame rate; "ram", what this machine
// holds at its size (framesFit); "most", the nodes' ceiling. `st`: width, height and fps, as the stat route gives them;
// `machine`: { ram, profile }, as ComfyUI reports its RAM and as memoryProfile names its GPU.
export function plateKeep(st, machine = {}) {
  const { frames, byTime } = plateLength(st?.fps), fit = framesFit(st?.width, st?.height, machine.ram, machine.profile);
  return fit < frames ? { frames: fit, by: "ram" } : { frames, by: byTime ? "time" : "most" };
}
// Why a plate opens with no more than `keep.frames`: one sentence for the Open dialog and the log.
export function keepReason(keep, { fps, width, height, ram }) {
  if (keep.by === "ram") return `this machine's ${Math.round(ram / 2 ** 30)} GB of RAM holds ${countText(keep.frames)} frames at ${width} x ${height} through every step`;
  if (keep.by === "most") return `Paint a plate's steps take up to ${countText(LENGTH.most)} frames`;
  return `LTX 2.5 makes shots of up to ${LENGTH.seconds} s, ${countText(keep.frames)} frames at ${Math.round(fps * 1000) / 1000} fps`;
}
// The log's warning for a plate that opens with frames left out: the status line shows its first line. Frame numbers are
// the plate's own: `first` is its first frame's. `plate`: fps, width, height and ram, for keepReason. Null when nothing is.
export function lengthWarning({ name, total, keep, first = 1, ...plate }) {
  if (!(total > keep.frames)) return null;
  const [a, b] = [first + keep.frames, first + total - 1];
  return `Warning: plate ${name}: ${countText(keep.frames)} of its ${countText(total)} frames opened.\n  Frames ${a} to ${b} are left out: ${keepReason(keep, plate)}.`;
}
export const hdrFps = (fps) => Math.min(30, +fps || 24); // the conditioning frame rate: at most 30, as in Lightricks' workflow
export const blankDepth = (v) => (+v === HDR_DEPTH ? HDR_DEPTH : 8);
// The 8-bit movies of an image sequence (its playback proxy, its review, its SDR-to-HDR pass) hold log values, ACEScct when
// the config has it, so they show what its full-precision frames show; a config without it keeps the model space.
export const viewerSpace = (names, model) => (names.includes("ACEScct") ? "ACEScct" : model);
// While a shot plays, one source shows one kind of frame: its full-precision frames once all of them are in, else its 8-bit
// movie. Mixed, the two would alternate as the frames arrive, with two different tone mappings, and the shot would flicker.
export const drawsDeep = (playing, holdsAll) => !playing || holdsAll;

// Esc, by what the page is doing. A plate that opens stops opening. The strokes in progress are dropped. The edit being
// generated stops and stays the current edit, with its strokes, words and seed ("reopen"): everything else that generates
// stops with it, and nothing starts until Enter. Then the selection goes, then a pass displayed gives way to the latest
// result, and last everything that generates stops ("stop").
export const escapeAction = ({ opening = false, editing, running = false, selected, pinned = false, generating }) =>
  (opening ? "cancelOpen" : editing ? "discard" : running ? "reopen" : selected ? "deselect" : pinned ? "latest" : generating ? "stop" : null);

// The order an edit's strokes are replayed in: as they were made, so a rub removes only what was painted before it, and a
// stroke painted later over the rubbed place stays. SAM's object comes last, cut by every rub.
export function replayOrder(strokes, sam = false) {
  const steps = strokes.map((stroke) => ({ stroke }));
  if (sam) steps.push({ sam: true, cuts: strokes.filter((s) => s.tool === "rub") });
  return steps;
}

// Edits are layers. While an edit of History is changed, the first frame shows the edits under it and its strokes: its own
// old result and every edit above it are hidden, since they are likely to be generated again. `edits`: History from the
// bottom, each { on, made } (made: it has a result); `at`: the place of the edit being changed, -1 for a new edit or none.
// Returns the places of the edits above it whose result is hidden.
export const hiddenAbove = (edits, at) => (edits[at]?.on ? edits.flatMap((e, i) => (i > at && e.on && e.made ? [i] : [])) : []);

// Edit numbers in a sentence: "edit 3", "edits 3 and 4", "edits 3, 4 and 5".
export const editList = (nums) => (nums.length === 1 ? `edit ${nums[0]}` : `edits ${nums.slice(0, -1).join(", ")} and ${nums.at(-1)}`);

// The status line after a stop: nothing starts until Enter. The edit that was being generated keeps its strokes, and the
// edits that waited for their turn stay queued. `edit`: the stopped edit's number, null when no edit was being generated.
export function stopHint({ edit = null, waits = [] } = {}) {
  const list = waits.length ? editList(waits) : "";
  const wait = list ? ` ${list[0].toUpperCase()}${list.slice(1)} ${waits.length > 1 ? "wait" : "waits"}.` : "";
  return edit === null ? `Stopped.${wait} Enter continues from there.`
    : `Stopped. Edit ${edit} keeps its strokes, text prompt and seed.${wait} Enter generates again, Ctrl+Enter tries another seed, Esc removes the strokes.`;
}

// Edits are layers, after Generate. An edit above an edit that is made again stays hidden until its own
// pass ends when it depends on that edit (dependsOnChange): it is generated again, over the new result. An edit that does
// not depend on it stays on the frame and is not generated again. `edits`: History from the bottom, each { id, version,
// tool, foot, basis, on, made, pending } (made: it has a result; pending: it waits for its turn or is being generated).
// Returns the places of the edits that wait for their own pass.
export function awaitingPass(edits) {
  const soon = [], waits = []; // the edits under each edit, as they will be once what is pending is made
  edits.forEach((e, i) => {
    if (!e.on) return;
    const again = !e.pending && e.made && dependsOnChange(e, soon, e.basis ?? []);
    if (again) waits.push(i);
    if (e.pending || again) soon.push({ ...e, version: `${e.version}+` }); // it will have another version
    else if (e.made) soon.push(e);
  });
  return waits;
}

// The light brush lays soft dabs at a fixed spacing along a stroke, whatever the pointer's speed, so the light builds up
// by stroke, never by how fast the hand moved. `points`: [x, y, radius]; `spacing(radius)`: the distance between dabs;
// `carry`: the distance walked since the last dab, kept between calls, so drawing a stroke as it arrives gives the same
// dabs as drawing it at once. The first point always gets a dab. Returns the dabs from point `from` on, and the carry.
export function dabsAlong(points, from, spacing, carry = 0) {
  const dabs = [];
  for (let i = from; i < points.length; i++) {
    const [x, y, r] = points[i];
    if (i === 0) { dabs.push([x, y, r]); carry = 0; continue; }
    const [px, py, pr] = points[i - 1], len = Math.hypot(x - px, y - py), s = Math.max(1, spacing((pr + r) / 2));
    let last = -1;
    for (let at = Math.max(0, s - carry); at <= len; at += s) {
      const f = len > 0 ? at / len : 1;
      dabs.push([px + (x - px) * f, py + (y - py) * f, pr + (r - pr) * f]);
      last = at;
    }
    carry = last < 0 ? carry + len : len - last;
  }
  return { dabs, carry };
}

// A soft dab: its alpha by distance over its radius, close to a Gaussian, as colour stops of a radial gradient
export const DAB_PROFILE = [[0, 1], [0.25, 0.85], [0.5, 0.5], [0.75, 0.18], [1, 0]];
export function dabAlpha(d) { // the profile between its stops
  if (d >= 1) return 0;
  const i = DAB_PROFILE.findIndex(([at]) => at > d), [a0, k0] = DAB_PROFILE[i - 1], [a1, k1] = DAB_PROFILE[i];
  return k0 + ((k1 - k0) * (d - a0)) / (a1 - a0);
}
// The eraser on a Light edit: soft dabs with the brush's profile (dabAlpha) take light and shade away. Each dab lowers a
// pixel's alpha by `amount` times the profile, never below 0, and keeps its colour, so it undoes the brush's "lighter"
// dabs of one colour exactly: paint, erase and the same paint again leave one paint, with no edge. `pixels`: the RGBA
// bytes of `box` ({ x, y, w, h }, in the layer's pixels), as getImageData gives them; `dabs`: [x, y, radius].
export function rubDabs(pixels, box, dabs, amount) {
  for (const [cx, cy, r] of dabs) {
    const x0 = Math.max(box.x, Math.floor(cx - r)), x1 = Math.min(box.x + box.w, Math.ceil(cx + r));
    const y0 = Math.max(box.y, Math.floor(cy - r)), y1 = Math.min(box.y + box.h, Math.ceil(cy + r));
    for (let y = y0; y < y1; y++) {
      for (let x = x0; x < x1; x++) {
        const k = dabAlpha(Math.hypot(x + 0.5 - cx, y + 0.5 - cy) / r), i = ((y - box.y) * box.w + x - box.x) * 4 + 3;
        if (k > 0) pixels[i] = Math.max(0, pixels[i] - 255 * amount * k);
      }
    }
  }
}
// The pixels that `dabs` reach inside a layer of `width` x `height`, as { x, y, w, h }, or null when they reach none
export function dabsBox(dabs, width, height) {
  let x0 = width, y0 = height, x1 = 0, y1 = 0;
  for (const [x, y, r] of dabs) {
    x0 = Math.min(x0, Math.floor(x - r)); y0 = Math.min(y0, Math.floor(y - r));
    x1 = Math.max(x1, Math.ceil(x + r)); y1 = Math.max(y1, Math.ceil(y + r));
  }
  [x0, y0, x1, y1] = [Math.max(0, x0), Math.max(0, y0), Math.min(width, x1), Math.min(height, y1)];
  return x1 > x0 && y1 > y0 ? { x: x0, y: y0, w: x1 - x0, h: y1 - y0 } : null;
}
// Each dab's alpha so the dabs of one straight stroke add up to `peak` on its centre line, at a spacing of
// `spacingOverRadius` of their radius
export function dabFlow(peak, spacingOverRadius) {
  let sum = 0;
  for (let k = -Math.ceil(1 / spacingOverRadius); k <= Math.ceil(1 / spacingOverRadius); k++) sum += dabAlpha(Math.abs(k * spacingOverRadius));
  return peak / sum;
}

// ---------- The passes displayed ----------
// Each finished step that made a picture shows on every frame from the Render panel, one render of the shot at a time:
// where its movie sits, in the render (`r`) or in its preview size (`pv`), as a path of keys. The tracking steps and the
// export show their matte as a grey movie, drawn through the config's data colour space (`spaces.data`): it shows its own
// values, with no view's tone mapping.
export const PASSES = { fluid: ["pv", "fluid.movie"], fluidfull: ["r", "fluid.movie"], erase: ["r", "erased.found.movie_a"], clean: ["pv", "cleanRaw"], shot: ["pv", "raw"], track: ["pv", "painted.found.movie_b"],
  comp: ["pv", "comp"], cleanfull: ["r", "cleanRaw"], full: ["r", "raw"], trackfull: ["r", "full.found.movie_b"], hdr: ["r", "hdrMovie"],
  review: ["r", "play"], export: ["r", "exported.matte"], upplate: ["up", "upplate"], uplayer: ["up", "uplayer"], upcomp: ["up", "upcomp"], uphdr: ["up", "uphdr"] };
export const MATTE_PASSES = new Set(["erase", "track", "trackfull", "export"]);
const keyPath = (o, path) => path.split(".").reduce((x, k) => x?.[k], o);
export function passMovie(id, r, pv, spaces = {}, up = null) { // { url, space, frames } of a finished step, or null; `up`: what Upscale's steps made at the size asked for
  const at = PASSES[id], store = at && (at[0] === "pv" ? pv : id === "review" ? r?.compResult ?? r : r); // the composite's own result, whichever is displayed (app.plan)
  if (at?.[0] === "up") return up?.[at[1]]?.url ? { url: up[at[1]].url, space: up[at[1]].space, frames: null } : null; // its movie at its own size (app.fitCanvas)
  const url = (at && keyPath(store, at[1])) ?? (id === "review" ? store?.review : null);
  if (!url) return null;
  if (id === "review") return { url, space: store.playSpace ?? store.reviewSpace ?? "@model", frames: store.reviewFrames ?? null };
  // SDR to HDR: its 8-bit movie in log values, and its EXR frames in their own space (ACES2065-1, `spaces.hdr`), for the viewer
  // to draw and inspect them as they are (setShot's fifth argument, framesSpace)
  if (id === "hdr") return { url, space: spaces.log ?? "@model", frames: store.hdrFrames ?? null, framesSpace: store.hdrFrames ? spaces.hdr ?? null : null };
  return { url, space: MATTE_PASSES.has(id) ? spaces.data ?? "@model" : "@model", frames: null };
}

// ---------- A relight: Klein gets the frame and the prompt that its strokes make (lightIntent) ----------
// A relight's strokes read as intentions, in words that Klein can follow with the frame alone: one sentence per light (its
// colour by name, its strength from the colour's brightness, its spread from the share of the frame it covers, its place),
// one per shaded place, the person's words, then what must stay. `strokes`: { color, size, points }, the points as [x, y]
// fractions of the frame and the size as a fraction of its width; `aspect`: the frame's width over its height. A light that
// covers 8% of the frame or more is broad; under 1%, focused. A small light inside the frame shows its source where it is
// drawn: its strokes of one colour that touch make one source, placed by a row of Klein's layout table (tgt_bbox, as a
// paint's request places its object). A source is judged by its path, its points without the brush's width: the path
// spans under a fifth of the frame each way and stays 2% inside its edges, so a dab of any brush size is a source. A
// stroke dragged across the frame is a wash, and a light at the frame's edge comes from outside: neither shows a source.
// A source is named by the words when they name a kind of light (« sun », « street lamp »). With no such word, a warm
// source in the top third of the frame is the sun: so named, Klein draws it behind what stands in front of it, where « a
// small, very bright light » washes the nearby buildings out in its glare. Any other source is a small, very bright light
// of its colour.
export const LIGHT_KINDS = /\b(sun|moon|street ?lamp|streetlight|lamp|lantern|candle|fire|torch|bulb|neon sign|spotlight)\b/i;
const WARM = new Set(["red", "orange", "yellow", "warm white"]);
export function lightIntent({ strokes, words = "", aspect = 16 / 9 }) {
  const place = (b) => { // b: [x0, y0, x1, y1] in fractions of the frame
    const cx = (b[0] + b[2]) / 2, cy = (b[1] + b[3]) / 2;
    const v = cy < 1 / 3 ? "top" : cy > 2 / 3 ? "bottom" : "", h = cx < 1 / 3 ? "left" : cx > 2 / 3 ? "right" : "";
    return v && h ? `${v} ${h}` : v || h || "centre";
  };
  const union = (a, b) => [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])];
  const groups = new Map(), lamps = [];
  for (const s of strokes) {
    const r = s.size / 2, rh = r * aspect, pts = s.points;
    let length = 0;
    for (let i = 1; i < pts.length; i++) length += Math.hypot((pts[i][0] - pts[i - 1][0]) * aspect, pts[i][1] - pts[i - 1][1]);
    const path = [Math.min(...pts.map((p) => p[0])), Math.min(...pts.map((p) => p[1])), Math.max(...pts.map((p) => p[0])), Math.max(...pts.map((p) => p[1]))];
    const box = [path[0] - r, path[1] - rh, path[2] + r, path[3] + rh].map((v) => Math.min(1, Math.max(0, v))); // its paint
    const key = dark(s.color) ? `shade ${place(box)}` : colorName(s.color);
    const g = groups.get(key) ?? { shade: dark(s.color), color: s.color, cover: 0, box };
    g.cover += Math.min(1, ((length + 2 * rh) * 2 * rh) / aspect); // a round brush along its path, as a share of the frame
    g.box = union(g.box, box);
    groups.set(key, g);
    if (!g.shade) lamps.push({ name: key, box, path });
  }
  const touch = (a, b) => a[0] <= b[2] && b[0] <= a[2] && a[1] <= b[3] && b[1] <= a[3];
  for (let joined = true; joined;) { // until no two touch: the sources do not depend on the strokes' order
    joined = false;
    for (let i = 0; i < lamps.length && !joined; i++) for (let j = i + 1; j < lamps.length && !joined; j++) {
      const a = lamps[i], b = lamps[j];
      if (a.name !== b.name || !touch(a.box, b.box)) continue;
      a.box = union(a.box, b.box);
      a.path = union(a.path, b.path);
      lamps.splice(j, 1);
      joined = true;
    }
  }
  const shown = lamps.filter(({ path: p }) => p[2] - p[0] < 0.2 && p[3] - p[1] < 0.2 && Math.min(p[0], p[1]) > 0.02 && Math.max(p[2], p[3]) < 0.98);
  const said = ["Relight the whole scene with new light, as if it were photographed under that light."];
  for (const [name, g] of groups) {
    if (g.shade) { said.push(`The ${place(g.box)} of the frame falls into deep shadow.`); continue; }
    const value = Math.max(...[1, 3, 5].map((i) => parseInt(g.color.slice(i, i + 2), 16))) / 255;
    const strength = value >= 0.85 ? "strong" : value < 0.5 ? "dim" : "soft", spread = g.cover >= 0.08 ? ", broad" : g.cover < 0.01 ? ", focused" : "";
    said.push(`A ${strength}${spread} ${name} light comes from the ${place(g.box)} of the frame.`);
  }
  if ([...groups.values()].some((g) => !g.shade)) said.push("Each light brightens the surfaces that face it with its colour and falls off with distance; " +
    "it casts soft shadows away from it, and the old highlights and shadows that disagree with it fade.");
  const w = String(words ?? "").trim();
  if (w) said.push(`${w[0].toUpperCase()}${w.slice(1)}${/[.!?]$/.test(w) ? "" : "."}`);
  const kind = w.match(LIGHT_KINDS)?.[1].toLowerCase();
  const rows = shown.map(({ name, box: b }, k) => {
    const what = kind ? `the ${kind}, small and very bright` : WARM.has(name) && place(b).startsWith("top") ? "the sun, small and very bright"
      : `a small, very bright ${name} light`;
    said.push(`The ${name} light's source <light_${k + 1}> is visible in the frame: ${what}.`);
    return { id: `light_${k + 1}`, from: "target", src_bbox: null, tgt_bbox: [b[1], b[0], b[3], b[2]].map((v) => Math.round(v * 1000)),
      desc: `the light's source: ${what}` };
  });
  said.push("Keep every object, face and texture, the camera angle, the framing and the composition exactly as they are: only the light " +
    `changes${rows.length ? ", and each light's source shows where it is placed" : ""}.`);
  return rows.length ? `${said.join(" ")} ${pyJSON(rows)}` : said.join(" ");
}

// The workflows each render step runs (a full-size erase pass runs two). The Models and licences dialog plans with them
// from the start of a job; a render also keeps the record of the steps it ran or took again (r.flows), so an export's MODELS.md
// names the models that made its result.
export const STEP_FLOWS = { fluid: ["fluid"], fluidfull: ["fluid"], erase: ["matte"], clean: ["clean"], shot: ["shot"], track: ["matte"], comp: ["comp"],
  cleanfull: ["clean", "cleanup"], full: ["shot"], trackfull: ["matte"], hdr: ["hdr"], review: ["review"], export: ["export"],
  upplate: ["export", "upscale", "upscale_export"], uplayer: ["export", "upscale", "upscale_export"], upcomp: ["export", "upscale", "upscale_export"], // an edit's upscaled steps read the export's parts
  uphdr: ["upscale", "upscale_export"] };
// The workflows behind a result: its edits' own (the prompt writer and Klein, SAM's object search for an erase), the
// render's record, and a fluid shot's (with its SDR to HDR)
export function resultFlows({ tools = [], render = [], fluid = false } = {}) {
  const w = new Set(render);
  if (tools.length) ["prompt", "edit"].forEach((n) => w.add(n));
  if (tools.includes("erase")) w.add("snap");
  if (fluid) w.add("fluid"); // a fluid shot planned before its render: its steps name the rest
  return [...w];
}
// The config's data colour space (OCIO's isdata, such as the studio config's Raw), from the spaces /paintaplate/ocio lists
export const dataSpace = (spaces = []) => spaces.find((c) => c.data)?.name ?? null;

// ---------- Pipeline: the memory profile ----------
// What the page does on the GPU it runs on, from the VRAM and RAM in ComfyUI's /system_stats. Three profiles to start from;
// the borders move with measurements (tests/gpu_matrix.py writes each case's peak VRAM and RAM).
// - small, under 24 GB of VRAM (measured on a 16 GB GPU with 52 GB of RAM): no model loads before an action needs it,
//   so the prompt writer, Klein and LTX take turns.
// - medium, from 24 GB: the edit models load at start, LTX with the first shot.
// - large, from 60 GB: every model loads at start and stays loaded.
// From 16 GB (WHOLE_FROM), every LTX decode takes the whole frame in one piece (tile WHOLE), and every LTX encode is whole:
// each IC-LoRA guide (guide_tiled false) and the first stage that the full-size clean plate pass refines (encode_tile WHOLE). In
// tiles, each tile comes out brighter near its edges, and the blend of two tiles leaves a band of 0.1 to 0.2 stops where
// they overlap; a guide encoded in tiles leaves its lines in the shot sampled from it, and a full-size clean plate pass encoded in
// 256 px tiles shows bands of 0.3 to 1.2 steps in 8 bits, up to 0.05 stops through SDR to HDR. 121 frames at 1920 x 1088
// decode whole in 13 s at a peak of 10.3 GiB in float32, against 45 to 99 s in tiles (RTX PRO 6000). Under 16 GB, LTX
// decodes and encodes in 256 px tiles, which leave those bands.
// `slots` are workflow slot values (tile, encode_tile, guide_tiled): one set of workflows serves every profile.
export const MEMORY_FROM = { medium: 24e9, large: 60e9 }; // bytes of VRAM: a 24 GB GPU reports about 25.7e9, a 16 GB one about 17.2e9
export const WHOLE = 4096; // a tile larger than any working frame: VAE Decode (Tiled) decodes the whole frame in one piece
export const WHOLE_FROM = 16e9; // bytes of VRAM from which every LTX decode is whole; a 12 GB GPU reports about 12.9e9
export const MEMORY = {
  small: { warm: [], frees: true, slots: { tile: WHOLE, encode_tile: WHOLE, guide_tiled: false }, does: "Models load one at a time, so each step takes longer than on a larger GPU" },
  medium: { warm: ["edit", "prompt"], frees: false, slots: { tile: WHOLE, encode_tile: WHOLE, guide_tiled: false }, does: "The edit models load now, LTX with the first shot" },
  large: { warm: ["edit", "prompt", "warm"], frees: false, slots: { tile: WHOLE, encode_tile: WHOLE, guide_tiled: false }, does: "Every model loads now and stays loaded" },
};
const TILED = { slots: { tile: 256, encode_tile: 256, guide_tiled: true }, does: "Models load one at a time and LTX works in 256 px tiles, so each step takes longer than on a larger GPU" }; // under WHOLE_FROM
// ComfyUI keeps the models of the jobs it has run in memory, ready for the next job. With 16 GB of VRAM under a cap of
// 52 GB of RAM, a full-size shot leaves LTX and its text encoder there, 35 GB, and a tracking job after it can take the rest:
// the system then stops ComfyUI. A profile that `frees` holds one family of models at a time: the page asks
// ComfyUI to free its memory before a job whose family is not that of the job posted before it.
export const FAMILY = { prompt: "klein", edit: "klein", shot: "ltx", clean: "ltx", cleanup: "ltx", fluid: "ltx", hdr: "ltx", warm: "ltx",
  matte: "sam", snap: "sam", ingest: "frames", comp: "frames", review: "frames", export: "frames", upscale: "seedvr2", upscale_export: "frames" }; // by workflow: the models it loads, or frames only
// Speed first where there is room. Under 24 GB of VRAM the GPU cannot hold two families of models, so a
// change of family frees ComfyUI's memory. On a larger GPU the models stay loaded, and the memory is freed only when
// RAM is short for the next job's frames: a job that reads the plate can hold RAM_COPIES float32 copies of it. The open
// itself holds 2.8 copies at its peak with a 16 GB GPU and 64 GB of RAM, 1.9 on an RTX PRO 6000 pod, so `ingest` counts
// RAM_COPIES_OPEN. A GPU that runs out of memory is retried
// once after a free, on every GPU (comfy.mjs).
export const RAM_COPIES = 8, RAM_COPIES_OPEN = 3;
export const framesNeed = (width, height, frames, name = "") => // bytes of RAM for the job `name`: the copies, and 4 GB to work in
  (name === "ingest" ? RAM_COPIES_OPEN : RAM_COPIES) * width * height * frames * 12 + 4 * 2 ** 30;
// Each job's name in a line a person reads, as the Render panel names it where it can: « Memory freed before the shot: the
// edit's models unloaded. »
export const JOB_NAME = { ingest: "opening the plate", prompt: "the prompt writer", prefetch: "the prompt writer", edit: "the edit",
  snap: "the SAM mask", clean: "the clean plate pass", cleanup: "the clean plate pass", shot: "the shot", matte: "the matte",
  comp: "the composite", review: "the review movie", export: "Export", warm: "the warm-up", fluid: "the fluid shot", hdr: "SDR to HDR",
  upscale: "Upscale", upscale_export: "the upscaled export" };

// A free between the matte and the steps that only read frames (the composite, the review movie, Export) unloads the models
// but keeps ComfyUI's cache: SAM 3.1's answers and the prompt upsampler's stay in it, so a change of matte strategy runs
// Follow Matte again and not SAM. Any other free also clears the cache, as before.
const KEEPS = new Set(["sam", "frames"]);
export const keepsAnswers = (last, name) => KEEPS.has(FAMILY[last]) && KEEPS.has(FAMILY[name]);

// Why ComfyUI's memory is freed before job `name` after job `last`, or null: on a small GPU, between families of models,
// with { why, keep } between the matte and the frames steps, which keeps ComfyUI's cache unless RAM is short for the
// frames (`room`); on a larger GPU, only when RAM is short. `room`: { free, need } in bytes, or null where unknown.
export function freeAsk(profile, last, name, room = null, plate = true) {
  if (freesBefore(profile, last, name)) {
    const why = `${JOB_NAME[last] ?? last}'s models unloaded.\n  This GPU holds one model family at a time.`;
    return keepsAnswers(last, name) ? { why, keep: !room || room.free >= room.need } : why;
  }
  if (!plate || !last || FAMILY[name] === FAMILY[last] || !freesBefore(profile, last, name, room)) return null;
  return `${Math.round(room.free / 2 ** 30)} GB of RAM free, ${Math.round(room.need / 2 ** 30)} GB needed for its frames.`;
}
// Whether freeAsk needs the RAM figures for this pair: a free that may keep the cache, or a larger GPU's change of family
export const freeNeedsRoom = (profile, last, name) => !!last && FAMILY[name] !== FAMILY[last] && (!profile?.frees || keepsAnswers(last, name));

export function freesBefore(profile, last, name, room = null) { // room: { free, need } in bytes of RAM, where ComfyUI gives it
  if (!last || FAMILY[name] === FAMILY[last]) return false;
  return !!profile?.frees || (!!room && room.free < room.need);
}

// ---------- How long a render step takes ----------
// A step's time has three parts: a lead before the sampler's first step (models load, frames are read), the sampling,
// whose progress the page receives, and a tail after it (the decode, the frames, the movie). The time run so far, scaled
// by the progress, says « 4 min 10 s » 37 s into a preview shot whose first step of 8 has just ended, for a pass that ends
// 20 s later. So the sampling is timed by its own pace, between its first and its latest step, and the rest comes from
// what the step took the last time on this machine (the page keeps
// each step's total, lead and tail per size, frame count and memory profile, in paintaplate.step-times).
const STEP_FAMILY = { fluid: "ltx", fluidfull: "ltx", erase: "sam", clean: "ltx", shot: "ltx", track: "sam", comp: "frames", cleanfull: "ltx", full: "ltx", trackfull: "sam", hdr: "ltx", review: "frames", export: "frames" };
// A step's time before it ever ran on this machine (stepGuess): the 96 GB GPU's reference (STAGES' ref, in seconds at
// REF_SIZE), scaled to the plate, then to the GPU. A 16 GB GPU, the small profile, holds one family of models at a time,
// so each job loads its models again: a lead in seconds per family, then a factor per step on the reference's scaled
// seconds. Measured on a 16 GB GPU with 52 GB of RAM, horse.mp4 at
// 1920 x 1080 and 121 frames: the lead is what a job spent outside its sampler or its tracking loop in ComfyUI's trace,
// and each factor makes the rest. SDR to HDR grows faster than its pixels (`grow`, the power of its scale): 172 s at
// 1280 x 704 and 606 s at 1920 x 1088, 121 frames each, the same workflow for a fluid shot and a render. The full-size shot grows the same way: 79.8 s at
// 960 x 512, 156.6 s at 1280 x 704 and 576.4 s at 1920 x 1088. A composite also spends `fixed` seconds whatever its size:
// comp took 7.8 s at 480 x 256 and 13.7 to 15.3 s at 960 x 544, review 13.5 s at 1280 x 704 and 23.2 to 26.0 s at
// 1920 x 1088, 121 frames each. Other
// profiles announce the references as they are. With SDR to HDR on, the full-size composite (review) and the export write
// half-float EXR frames: `withHdr` multiplies their seconds (37.7 s and 14.6 s on the HDR test plate made from horse.mp4,
// 1920 x 1080 and 121 frames). tests/js/render_estimates.test.mjs holds every measured step within 25%.
export const SLOWER = {
  small: { lead: { ltx: 38, sam: 11, frames: 0 }, fluid: 1.1, fluidfull: 1.1, erase: 2.1, track: 1, trackfull: 1, clean: 3.35, shot: 1.64, cleanfull: 1.18,
    full: 1.1, hdr: 1.166, comp: 0.42, review: 0.42, export: 0.235, grow: { hdr: 1.72, full: 1.72, fluidfull: 1.72 }, withHdr: { review: 1.9, export: 1.6 },
    fixed: { comp: 6.4, review: 3 } },
};
export const slower = (profile, id) => SLOWER[profile]?.[id] ?? 1;
const BIG_STEPS = ["fluidfull", "full", "cleanfull", "cleanup", "hdr", "review", "export"]; // the steps made at the working size (cleanup: stageTwoGuess)
export const stepSizeOf = (id, plate) => (BIG_STEPS.includes(id) ? plate.work : ["erase", "track", "trackfull"].includes(id) ? plate.track : plate.shot);
const REF_SIZE = 928 * 512 * 97; // pixels times frames, where the references were measured
export function stepGuess(id, ref, plate, profile, hdr = false) { // seconds: the reference scaled to this plate (BIG_STEPS at 0.73 of it), then to this GPU; hdr: the render makes SDR to HDR
  const [w, h] = stepSizeOf(id, plate), scale = (w * h * plate.frames) / REF_SIZE * (BIG_STEPS.includes(id) ? 0.73 : 1);
  return (SLOWER[profile]?.lead?.[STEP_FAMILY[id]] ?? 0) + (SLOWER[profile]?.fixed?.[id] ?? 0) + ref * Math.max(0.25, scale) ** (SLOWER[profile]?.grow?.[id] ?? 1) * slower(profile, id)
    * (hdr ? SLOWER[profile]?.withHdr?.[id] ?? 1 : 1);
}
// Whether the full-size clean plate pass starts from the preview's own pass: the Preview pass is on (previewCap, 0 when Off)
// and makes its clean pass at the size of stage 1, half the working size.
export const startsFromPreview = (plate, previewCap) => { if (!plate?.work || !previewCap) return false; const low = stageOne(plate.work); return plate.shot?.[0] === low[0] && plate.shot?.[1] === low[1]; };
// The full-size clean plate pass when its first stage is the preview's own pass, made already: the pass less that stage
// (ref: each step's reference, by id). Its seconds are kept as « cleanup », apart from the pass that makes both stages.
export const stageTwoGuess = (ref, plate, profile) => Math.max(1, stepGuess("cleanfull", ref.cleanfull, plate, profile) - stepGuess("clean", ref.clean, plate, profile));
// The name a step's seconds are kept under: with SDR to HDR on, the steps it slows (SLOWER's withHdr) are kept apart.
export const timeId = (id, hdr) => (hdr && Object.values(SLOWER).some((p) => p.withHdr?.[id]) ? `${id}+hdr` : id);
export function stepLeft({ est, run, first = null, last = null, tail = null }) { // seconds left in the step that runs; first and last: [seconds since its start, progress]
  const after = tail ?? est * 0.15;
  if (first && last && last[1] - first[1] >= 0.2 && last[0] > first[0]) { // the sampler's own pace, over a fifth of its steps or more
    const pace = (last[0] - first[0]) / (last[1] - first[1]), since = run - last[0];
    const sampling = Math.max(0, (1 - last[1]) * pace - (last[1] < 1 ? since : 0));
    return Math.max(1, sampling + (last[1] >= 1 ? Math.max(0, after - since) : after));
  }
  return Math.max(est - run, est * 0.1, 1); // before the pace is known: what the step is expected to take, less what has run
}
export const timeKey = (id, size, frames, profile) => `${id}|${size[0]}x${size[1]}x${frames}|${profile}`;
export function remember(times, key, sample, keep = 80) { // times: { key: { total, lead, tail, at } }; the mean of what was kept and the new sample
  const old = times[key], mix = (a, b) => Math.round((a == null ? b : (a + b) / 2) * 10) / 10;
  const next = { ...times, [key]: { total: mix(old?.total, sample.total), lead: mix(old?.lead, sample.lead), tail: mix(old?.tail, sample.tail), at: sample.at } };
  return Object.fromEntries(Object.keys(next).sort((a, b) => next[b].at - next[a].at).slice(0, keep).map((k) => [k, next[k]]));
}
export function memoryProfile({ vram = 0, ram = 0, force = null } = {}) { // `force`: a profile's name, from ?memory= or the paintaplate.memory setting
  const auto = vram >= MEMORY_FROM.large ? "large" : vram >= MEMORY_FROM.medium ? "medium" : "small";
  const forced = Object.hasOwn(MEMORY, force ?? ""), name = forced ? force : auto, gib = (n) => Math.round(n / 2 ** 30);
  const card = vram > 0 ? `${gib(vram)} GB of VRAM${ram > 0 ? `, ${gib(ram)} GB of RAM` : ""}` : "ComfyUI gave no VRAM size";
  const profile = { name, why: forced ? `asked for; with ${card}, the page would choose ${auto}` : card, ...MEMORY[name] };
  if (vram >= WHOLE_FROM) return profile;
  return { ...profile, slots: { ...profile.slots, ...TILED.slots }, does: name === "small" ? TILED.does : profile.does };
}

// ---------- A seed asked for in the address ----------
// The seed that ?seed= in the address asks for, for the tests: a whole number from 0 to 2^31 - 1, as the page draws them.
// With it a session's first new edit and every new fluid shot start from that seed, and each next edit from the next number
// (editSeed), so a run makes the same pictures as the run before and no two edits start from the same noise.
// Another try (Ctrl+Enter) still draws one. null: no seed is asked for, or the text is not one, and the page draws.
export const askedSeed = (text) => (/^\d{1,10}$/.test(text ?? "") && Number(text) < 2 ** 31 ? Number(text) : null);
// The seed of a session's new edit: `made` edits came before it. null when no seed is asked for.
export const editSeed = (asked, made) => (asked === null ? null : (asked + made) % 2 ** 31);

// The blocks of LTX's 32 px grid that the clean plate pass grows its erased grid by, at a width of `sizeW`, so that it erases
// as far as the composite pastes an erase on a plate `plateW` wide: `reach`, the composite's grow and feather in the plate's
// pixels, scaled to that width, plus the block that hides the object's outline.
export const gridGrow = (sizeW, plateW, reach) => 1 + Math.ceil((reach * sizeW) / plateW / 32);

// View > Cache memory > Custom…: a size a person types, in MB or GB (a number alone is MB), as bytes, or null outside
// CACHE_LEAST to CACHE_MOST. The page counts 1 GB as 10^9 bytes, as the frame cache's other
// lines and the file sizes do (app.memoryText, gb); the lines of a GPU's VRAM and RAM count 2^30 bytes.
export const CACHE_LEAST = 128e6;
export const CACHE_MOST = 32e9;
export function memoryBytes(text) {
  const m = /^\s*(\d+(?:[.,]\d+)?)\s*(mb|m|gb|g)?\s*$/i.exec(text ?? "");
  const b = m ? parseFloat(m[1].replace(",", ".")) * (/^g/i.test(m[2] ?? "") ? 1e9 : 1e6) : NaN;
  return b >= CACHE_LEAST && b <= CACHE_MOST ? Math.round(b) : null;
}

// ---------- The cache on disk ----------
// The folders under ComfyUI's output folder that some values name: a render's (paintaplate/<plate>/v<n>), the edits'
// (paintaplate/<plate>/edits) or a plate's own files (paintaplate/<plate>). A saved scene keeps those of what it shows,
// and the page those of the plate on screen, so View > Clear unused cache (cache.py) leaves them. It walks arrays, plain
// objects, maps and sets, and reads every string, decoded as a view address.
export function foldersIn(values) {
  const found = new Set(), seen = new WeakSet();
  const walk = (v, depth) => {
    if (typeof v === "string") {
      let text = v;
      try { text = decodeURIComponent(v); } catch { /* a lone % leaves the string as it is */ }
      for (const [, id, rest] of text.matchAll(/paintaplate\/([a-z0-9]+)((?:\/[^/&"'\s?#]+)*)/g)) {
        const parts = rest.split("/").filter(Boolean);
        found.add(parts.length >= 2 || /^(v\d+|edits)$/.test(parts[0] ?? "") ? `paintaplate/${id}/${parts[0]}` : `paintaplate/${id}`);
      }
    } else if (v && typeof v === "object" && depth < 8 && !seen.has(v)
      && (Array.isArray(v) || v instanceof Map || v instanceof Set || Object.getPrototypeOf(v) === Object.prototype)) {
      seen.add(v);
      for (const x of v instanceof Map || v instanceof Set ? v.values() : Object.values(v)) walk(x, depth + 1);
    }
  };
  walk(values, 0);
  return [...found].sort();
}

// A scene of version 6 or earlier, as version 7 holds it: its fluid shot, kept apart then, is History's first row, and a
// 16-bit fluid shot turns Finish > SDR to HDR on. Version 5 named the switch « hdr ». A scene of version 7 is returned as it is.
export function sceneV7(scene) {
  if (!(scene.version < 7)) return scene;
  const { fluid, hdr, ...rest } = scene, edits = [...(scene.edits ?? [])];
  if (fluid) edits.unshift({ tool: "fluid", prompt: fluid.prompt ?? "", seed: fluid.seed, on: fluid.on !== false, made: !!fluid.made, keys: fluid.keys ?? [] });
  const on = (scene.version >= 6 ? !!scene.deliver?.hdr : scene.version === 5 && hdr === true) || +(fluid?.depth ?? 8) >= 16;
  return { ...rest, version: 7, edits, deliver: { ...(scene.deliver ?? {}), hdr: on }, fluid: undefined };
}

// ---------- The Render panel's status line ----------
// The render's steps fall in classes, in the order they run: the preview, the full size, then Finish, for the Finish menu's
// passes that run on the full-size result (SDR to HDR after the composite or on the plate alone, and Upscale's steps); the
// export is its own. A step that is neither a preview nor a full-size step (a Clean's tracking) belongs to the first class
// the render has. `steps`: the render's planned steps, as the page lists them; hdrLast: SDR to HDR runs on the full-size result.
export function stepClasses(steps, hdrLast = false) {
  const first = steps.some((st) => st.preview) ? "preview" : "full";
  return Object.fromEntries(steps.map((st) => [st.id, st.onDemand ? "export" : st.up || (st.id === "hdr" && hdrLast) ? "finish" : st.final ? "full" : st.preview ? "preview" : first]));
}
// The line names the class at work and the time until that class is done: « preview », « full size », then « finish ». At
// the end it says what is ready, so a full size that is made is never announced again while Finish runs.
// `steps`: each planned step's class, whether it is done, and its seconds left; busy: one of them runs now.
export function renderStatus(steps, { exporting = false, exported = false, busy = false } = {}) {
  const due = (...cls) => steps.filter((s) => cls.includes(s.cls) && !s.done), has = (cls) => steps.some((s) => s.cls === cls);
  const say = (name, list) => { const t = list.reduce((a, s) => a + s.left, 0); return t ? `${name} ${secs(t)}` : busy ? `${name} almost ready` : ""; };
  if (exported) return "exported";
  if (exporting) return say("export", due("preview", "full", "finish", "export"));
  for (const [cls, name] of [["preview", "preview"], ["full", "full size"], ["finish", "finish"]]) if (due(cls).length) return say(name, due(cls));
  return has("finish") ? "finish ready" : has("full") ? "full size ready" : "";
}
// The render's planned steps in the order they run: as the page lists them, with SDR to HDR after the full-size composite
// when it runs on it (hdrLast), so a step still to come sits where it will run.
export function runOrder(steps, hdrLast = false) {
  const hdr = steps.find((st) => st.id === "hdr"), comp = steps.findIndex((st) => st.id === "review");
  if (!hdrLast || !hdr || comp < steps.indexOf(hdr)) return steps;
  const rest = steps.filter((st) => st !== hdr);
  rest.splice(rest.findIndex((st) => st.id === "review") + 1, 0, hdr);
  return rest;
}
