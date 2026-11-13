// Pure functions of the page: workflows as data, sizes, captions, time, edit dependencies, the frame cache's ranking.
// No DOM and no state here, so tests/js runs every one of them in Node (node --test).

// ---------- Workflows as data ----------

// Optional links: when every source slot is left empty, the link goes, with every node that fed it. The same rule as
// tools/build_workflows.py (OPTIONAL there; a test checks they match): a relight alone has
// no matte to composite with, nor to save (the export's "matte" output goes with it).
export const OPTIONAL = { fit_mask: ["matte_a", "matte_b"], named: ["words"], relit_frame: ["relight"], follow_base: ["base"], follow_element: ["seed"],
  review_frames: ["frames_prefix"], review_view: ["view_prefix"], edit_plan: ["plan"], hdr_shot: ["hdr"], relight_shade: ["shade"],
  matte_movie: ["video_prefix"], export_matte_movie: ["matte_video_prefix"], fluid_control: ["control_prefix"],
  export_plate: ["prefix"], export_exr: ["exr_prefix"] };

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

export const gb = (n) => (n > 1e9 ? `${(n / 1e9).toFixed(2)} GB` : n >= 1e6 ? `${Math.round(n / 1e6)} MB` : `${Math.max(1, Math.round(n / 1e3))} KB`);

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

// A light edit's colour, by name: its first light stroke's (dark strokes are shadow hints), else the tool's
export const lightColor = (colors, color) => colorName(colors.find((c) => !dark(c)) ?? color);

// An erase's words as its object's name after « the »: an article that was typed goes (the GPU case's « the barn » asked
// Klein's prompt writer to « Remove the the barn », 12 Nov 2026).
const objectName = (words) => String(words ?? "").trim().replace(/^(?:the|a|an)\s+/i, "");

// tool: paint, erase or light; words: the prompt; colors: of the painted strokes; color: the tool's colour;
// bbox: [y_min, x_min, y_max, x_max] on 0..1000. Only the chosen tool's text is built.
export function caption({ tool, words, colors, color, bbox }) {
  if (tool === "light") return lightPlanCaption({ colors, color, words }); // a relight's request is the page's own
  const name = objectName(words);
  const text = {
    erase: () => `Remove the ${name || "object"} inside <obj_1> completely, with its shadow and its reflection. Show the surface and the background that continue behind it, with matching detail, light, shadows and focus. Add no new object. Keep everything else unchanged.`,
    paint: () => `Replace the rough coloured drawing inside <obj_1> with ${words || "an object of that shape and colour"}, following the drawing's outline, pose and size, in exactly the same style, lighting, perspective and grain as the rest of the image. Keep everything else unchanged.`,
  }[tool]();
  const desc = { erase: name ? `${name} to remove` : "object to remove", paint: words || "the drawn object" }[tool];
  return `${text} ${JSON.stringify([{ id: "obj_1", bbox, desc }])}`;
}

// ---------- What FLUX 3 Image Klein's upsampler reads, and what the page keeps of its answer ----------
// Black Forest Labs' own format (src/flux3/pup.py and bbox.py): an erase or a paint edit is a request with one locked row
// in the table Klein was trained on; a relight is a plain request. Boxes are [y_min, x_min, y_max, x_max] on 0..1000.

const pyJSON = (v) => JSON.stringify(v).replace(/("(?:[^"\\]|\\.)*")|([,:])/g, (m, s, p) => s ?? `${p} `); // json.dumps spacing
export const KEEP_TOUCHED = " Where the drawing touches an object, the new element acts on that object itself (it burns it, rests on it, " +
  "wets it or lights it); add no props, fuel or supports that were not asked for."; // a fire on a towel came with logs without it

export function upsampleRequest({ tool, words, bbox, boxes = null, colors = [], color = "#ffd890" }) {
  if (tool === "light") return { mode: "plain", locked: null, request: lightPlanCaption({ colors, color, words }) }; // no prompt writer: the light plan says it
  const parts = tool === "erase" && boxes?.length > 1 ? boxes : null; // several painted parts: one locked row each
  const rows = parts ? parts.map((b, i) => ({ id: `obj_${i + 1}`, from: "ref_image_0", src_bbox: b, tgt_bbox: null, desc: words || "an object to remove" }))
    : [tool === "erase" ? { id: "obj_1", from: "ref_image_0", src_bbox: boxes?.[0] ?? bbox, tgt_bbox: null, desc: words || "the object to remove" }
      : { id: "obj_1", from: "target", src_bbox: null, tgt_bbox: bbox, desc: words || "an object of the drawing's shape and colour, in the image's own style" }];
  const cites = rows.map((r) => `<${r.id}>`), list = cites.length > 1 ? `${cites.slice(0, -1).join(", ")} and ${cites.at(-1)}` : cites[0];
  const ask = tool === "erase"
    ? parts ? `Remove the ${objectName(words) || "objects"} ${list} completely, with their shadows and their reflections, and continue the background behind them. Remove nothing else.`
      : `Remove the ${objectName(words) || "object"} <obj_1> completely, with its shadow and its reflection, and continue the background behind it. Remove nothing else.`
    : `Replace the rough coloured drawing at <obj_1> with ${words || "an object of the same shape and colour"}: follow the drawing's outline, pose, size and colours, and draw it in exactly the style of the rest of the image (a photograph, a painting or an illustration: whichever it is), in the same light, perspective, focus and grain, casting its own light and shadows on what is around it.${KEEP_TOUCHED}`;
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

// ---------- An erase: one locked box per painted part ----------
// One box around a truss, a crane and a door took in an astronaut between them, and the upsampler removed him instead (28 Oct).
// A few tight boxes cover the paint, so they hold what was painted and little else.
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
  return boxes.sort((a, z) => a.x1 - z.x1 || a.y1 - z.y1).map(box); // numbered left to right, as the upsampler numbers its rows
}

// Whether a caption erases what was painted: it cites a locked row (<obj_1>), or the rows it removes and cites hold most of the
// paint. `paint`: { bits, w, h }, the painted area on a coarse grid. On 28 Oct the bad caption removed person_1, a box with none
// of the paint in it; the good one never cited <obj_1> but removed four rows that held nearly all of it.
export function erasesPaint(text, locked, paint, share = 0.5) {
  const [caption, rows] = splitTable(text);
  if (locked.some((r) => caption.includes(`<${r.id}>`))) return true;
  const ids = new Set(locked.map((r) => r.id));
  const boxes = (rows ?? []).filter((r) => r && !ids.has(r.id) && r.tgt_bbox == null && validBox(r.src_bbox) && caption.includes(`<${r.id}>`))
    .map((r) => r.src_bbox);
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
// the object's name before Klein runs. On 12 November 2026 the page's own caption went to Klein instead, Klein left the barn,
// and the shot rendered. With words, the page's own caption carries them, and Klein runs.
export const asksName = (tool, words) => tool === "erase" && !String(words ?? "").trim();

// ---------- An erase with no words: the box the prompt writer gets ----------
// The stroke, and the pixels that most of SAM's masks hold, with no margin. On 12 Nov 2026 two of the five masks of a stroke
// on a barn took in the horse's nose: with a box around them all, the prompt writer removed the horse; with this one, it
// removed the barn (the probe, 13 Nov). `painted` and `masks`: Uint8Arrays of 0 and 1 over w x h pixels. null: nothing.
export function coreBox({ painted, masks, w, h }) {
  let y0 = h, x0 = w, y1 = -1, x1 = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    const i = y * w + x;
    let n = 0;
    for (const m of masks) n += m[i];
    if (!painted[i] && n * 2 <= masks.length) continue;
    y0 = Math.min(y0, y); y1 = Math.max(y1, y); x0 = Math.min(x0, x); x1 = Math.max(x1, x);
  }
  return x1 < 0 ? null : [y0 / h, x0 / w, (y1 + 1) / h, (x1 + 1) / w].map((v) => Math.round(v * 1000));
}

// The boxes the prompt writer gets: an erase with no words, painted in one part, gets its core box; otherwise one box per
// painted part (paintBoxes), with the edit's bounds (`bbox`).
export const writerBoxes = ({ tool, words, parts, core, bbox }) =>
  (tool === "erase" && !String(words ?? "").trim() && core && parts?.length === 1 ? { bbox: core, boxes: [core] } : { bbox, boxes: parts });

// The erase pass's prompt: the scene as it stays, in the upsampler's own words for what it kept (rows with a box in the
// result). People and text stay out (a pose in words fights the plate's own motion), and the erased object is never named
// (named, the umbrella came back). Nothing kept: no prompt, as LTX's inpainting guide recommends.
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
// stage refines it at full size in 2 steps (8 steps at full size took 181 s on a 1080p plate, 28 Oct).
export const stageOne = ([w, h], step = 32) => [Math.max(step, Math.round(w / 2 / step) * step), Math.max(step, Math.round(h / 2 / step) * step)];

// ---------- The render queue ----------
// Every set of edits shown since the plate opened is a render, with three classes of steps: its preview, its full-size passes
// and its export. The next step comes from the render whose next class is the lowest, so every preview runs before any full
// size, and every full size before any export; within a class, the set of edits on show first, then the most recently shown.
// An export someone is waiting for counts as a full-size step.
export const RENDER_CLASSES = ["preview", "full", "export"];
export function nextRender(items) { // items: [{ id, cls, current, wanted, urgent }]; the id of the render to run, or null
  const rank = (x) => RENDER_CLASSES.indexOf(x.cls === "export" && x.urgent ? "full" : x.cls);
  const best = items.filter((x) => RENDER_CLASSES.includes(x.cls))
    .sort((a, b) => rank(a) - rank(b) || Number(b.current) - Number(a.current) || b.wanted - a.wanted)[0];
  return best ? best.id : null;
}

// Generate stops a running render step only where that wastes least: a full-size or an export step in its first half. A step
// past halfway costs less to finish than to run again, and a preview step is short and often reused by the new edit's render.
export const stopsForEdit = ({ cls, progress }) => cls !== "preview" && progress < 0.5;

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

// The Ripple sentence, then one line per paint or light edit (its card: a short description of the change helps; an explosion
// then stayed and grew instead of driving off with the car). An erase is never named: named, the umbrella came back.
export function shotPrompt(edits) { // a light edit names its colour (`hue`), with or without words
  return [RIPPLE, ...edits.filter((e) => (e.tool === "paint" && e.words) || e.tool === "light").map((e) => (e.tool === "paint"
    ? `Added in the first frame: ${e.words}; it keeps moving naturally and stays in place on what it touches for the whole shot.`
    : `The first frame is relit${e.hue ? ` with ${e.hue} light` : ""}${e.words ? `: ${e.words}` : ""}; this new light holds for the whole shot.`))].join(" ");
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

// A render of fewer edits (after a bypass or a removal) can take the frames of an earlier render of more edits: its composite
// then takes those frames only inside the mattes of the edits it keeps, and the plate everywhere else. That is exact when
// every edit left out is far from every edit kept (their first-frame footprints apart; an edit without one counts as near)
// and no light is involved, since a light changes every pixel. `want`: the new render's edits, as frozen; `renders`:
// [{ key, active, wanted }], those whose frames exist. Returns the key of the one with the fewest edits left out, then the
// most recently shown, or null.
export function donorFor(want, renders) {
  const key = (e) => `${e.id}.${e.version}`, mine = new Set(want.map(key));
  const apart = (a, b) => !!a.foot && !!b.foot && !overlap(a.foot, b.foot);
  if (!want.length || want.some((e) => e.tool === "light")) return null;
  let best = null;
  for (const r of renders) {
    const have = new Set(r.active.map(key));
    if (have.size <= mine.size || [...mine].some((k) => !have.has(k)) || r.active.some((e) => e.tool === "light")) continue;
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
// The in-frame colour picker (Firefox, Safari): the average of the pixels under the click as #rrggbb, for the brush. `data`
// holds RGBA bytes, as getImageData returns them; transparent pixels, outside the frame, do not count.
export function pickedColor(data) {
  let r = 0, g = 0, b = 0, n = 0;
  for (let i = 0; i < data.length; i += 4) if (data[i + 3] > 0) { r += data[i]; g += data[i + 1]; b += data[i + 2]; n++; }
  return n ? `#${[r, g, b].map((v) => Math.round(v / n).toString(16).padStart(2, "0")).join("")}` : null;
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
// What a failed step's ComfyUI message means, in one plain sentence. The page puts it after "<step> failed:", and the
// log keeps ComfyUI's own words.
const SAVED = { matte_a: "the clean matte", matte_b: "the paint matte", clean: "the clean plate pass", shot: "the shot", plate: "the fluid shot" };
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

// A page path as breadcrumbs, the root first: "output:video/shot" gives Output, video, shot, each with the path it opens
export function crumbs(path) {
  const out = path.startsWith("output:"), base = out ? "output:" : "", parts = path.slice(base.length).split("/").filter(Boolean);
  return [{ label: out ? "Output" : "Input", path: base }, ...parts.map((p, i) => ({ label: p, path: base + parts.slice(0, i + 1).join("/") }))];
}

// The frame pattern of a sequence from one of its file names: core's f_00001_.exr gives f_#####_.exr
export const framePattern = (name) => name.replace(/(\d+)(\D*)$/, (_, d, rest) => "#".repeat(d.length) + rest);

export function plainError(message) {
  const m = String(message ?? "");
  if (/out of memory|allocation on device/i.test(m)) return "the GPU ran out of memory.";
  if (/ComfyUI stopped answering/i.test(m)) return "ComfyUI stopped answering. Its terminal says why: most often the machine ran out of memory. Start ComfyUI again.";
  if (/No answer from ComfyUI|is not valid JSON|Unexpected end of JSON input|Failed to fetch|NetworkError/i.test(m)) return "ComfyUI did not answer: it may be restarting, or the connection dropped.";
  const empty = m.match(/No image frames found in (\S+)/);
  if (empty) {
    const part = empty[1].split(/[\\/]/).filter(Boolean).find((p) => SAVED[p.replace(/_(\d+x\d+|full)$/, "")]);
    return `${part ? SAVED[part.replace(/_(\d+x\d+|full)$/, "")] : "the step before it"} saved no frames, so there was nothing to read.`;
  }
  if (/leaves the ComfyUI folders|outside the output folder|Absolute plate paths/i.test(m)) return "the file is outside ComfyUI's input and output folders.";
  if (/Unsupported plate/i.test(m)) return "Paint a plate cannot read this kind of file.";
  if (/value not in list|not found in list|failed validation|Missing nodes|does not exist in/i.test(m)) return "a model or a node it needs is missing.";
  if (/No such file|FileNotFound|not found/i.test(m)) return "a file it needs is missing.";
  if (/Upload failed/i.test(m)) return "the browser could not send a picture to ComfyUI.";
  return "ComfyUI stopped with an error.";
}

export function strokeTarget({ draft, current, tool }) { // where a new stroke goes: "draft", "current" or "new"
  if (draft) return "draft";
  return current?.tool === tool ? "current" : "new";
}

export function toolEndsEdit({ draft, current }, tool) { // picking another tool than the edit being worked on starts a new edit
  const work = draft ?? current;
  return !!work && work.tool !== tool;
}

// The eraser's key, X. Held while a stroke is dragged, the eraser lasts as long as the key is down; a tap, shorter than
// ERASER_TAP seconds with no stroke, switches it on or off. The eraser's state once the key comes up.
export const ERASER_TAP = 0.3;
export function eraserAfterKey(was, held, dragged) { return !dragged && held < ERASER_TAP ? !was : was; }
// The OCIO menu's line for the plate: its colour space, then « from file » for the file's own, or « override ».
export function plateSpaceLine(plate) {
  return plate ? `Colour space: ${plate.cs}, ${plate.pageSpaceChosen ? "override" : "from file"}` : "Colour space: no plate";
}
// The one question before an OCIO change that regenerates: what changes (« colour space », « config ») and the edits it counts.
export function remakeQuestion(what, edits) { return `Changing the ${what} regenerates the first frame and ${edits} edit${edits === 1 ? "" : "s"}.`; }
// An image that the scene's ComfyUI graph reads. It sits at the top of ComfyUI's input folder: LoadImage lists only the files
// there, and the editor marks an image input whose file is not in that list as missing. Named after the plate, the edit,
// what it holds and its hash, so two scenes never share a name.
export function graphImageName(plate, edit, kind, hash) {
  const stem = String(plate || "").replace(/[^A-Za-z0-9-]+/g, "_").replace(/^_+|_+$/g, "").slice(0, 40) || "plate";
  return `paintaplate_${stem}_e${edit}_${kind}_${String(hash).slice(0, 8)}.png`;
}

export function fluidPrompt(words) { // the trigger first, as the model card asks; no words: its own example
  const rest = (words || "").trim().replace(/^ainvfxfluid\s*,?\s*/i, "");
  return `${FLUID.trigger}, ${rest || FLUID.prompt}`;
}

// The paint matte's seed: the pixels where the edited first frame (a) differs from the plate's (b) by more than
// `threshold` (0 to 255, on the largest channel), inside the paint zones (z, white). RGBA arrays of one size; 1 or 0 per
// pixel. The zone is wider than what was painted, and a matte started from all of it followed whatever stood nearby.
export function changedMask(a, b, z, threshold = 24) {
  const n = a.length >> 2, out = new Uint8Array(n);
  for (let i = 0; i < n; i++) {
    const j = i * 4;
    if (z[j] < 128) continue;
    if (Math.max(Math.abs(a[j] - b[j]), Math.abs(a[j + 1] - b[j + 1]), Math.abs(a[j + 2] - b[j + 2])) > threshold) out[i] = 1;
  }
  return out;
}

// An erase that left its object. Klein can answer an erase with the frame as it was: on 12 November 2026 a stroke on a
// barn, with no words, got the page's own caption, and the barn stayed through the whole shot. So after the edit the page
// compares the first frame (`after`) with the frame under the edit (`before`) inside the object's mask (`mask`: painted
// where its red is 128 or more), all three RGBA at `w` x `h`, on cells of `cell` pixels. A cell's mean colour holds under
// Klein's softness and under the few levels its fill can sit off the frame (4 to 6, measured for Level Fill on 28
// October), and it moves when the object goes. Returns the share of the object, from 0 to 1, whose cells moved by more
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

// Whether an erase removed its object, as the page judges it (eraseCheck). The first rule (under 2% of it changed, at 12 levels)
// let through a barn that Klein had only recoloured: 59% of its cells moved (12 Nov 2026). On the probe's 21 results of 13 Nov,
// what went had 53 to 78% of its cells moved by more than 24 levels and its edges at -0.03 to 0.75 (a fence in front of the
// barn kept some); what stayed had 0 to 1% and 0.93 to 0.98; a tree half changed had 17% and 0.62. So an object is left when
// under 30% of it changed, or when its edges held above 0.85. A null figure: nothing to judge by it.
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

// The check after an erase, one pure function for the page and for the tests on a GPU: the first frame after the edit
// (`after`), the frame under it (`before`) and the object's mask, all three RGBA at w x h. { changed, edges, left }.
export function eraseCheck(after, before, mask, w, h) {
  const changed = erasedShare(after, before, mask, w, h, { levels: 24 }), edges = edgesHeld(after, before, mask, w, h);
  return { changed, edges, left: objectLeft({ changed, edges }) };
}

// What to do next, for the status line: an object with no name gets one; a named object gets other words or another seed.
export const leftHint = (words) =>
  (words ? "Describe it with other words, then Generate, or press Ctrl+Enter for another seed." : "Type its name in the prompt bar, then Generate.");

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
// « room.1001.exr » is room (3 Nov: train_v2.mp4 and chalet_v2.mp4 showed as « train_v » and « chalet_v », so two movies
// could share a name in the page, in scenes and in exports).
export function plateStem(file, sequence) {
  const base = String(file ?? "").split(/[\\/]/).pop().replace(/\.[^.]+$/, "");
  return (sequence ? base.replace(/[._]?\d+$/, "") : base) || "plate";
}

// ---------- The model warm-up ----------
// warmAll's last line. It goes to the status line only while that line still says what the page said at start: once a plate
// was opened or closed, the status line holds a newer message, and the log keeps this one. A warm-up job that an opening, an
// edit or a close cancelled (stopEverything) has not loaded its model, so the line then says so, never « every model loaded ».
// 3 Nov: a close that cancelled the warm-up's last job showed « Ready: every model loaded » in place of « Plate closed ».
export function warmEnd(seconds, missed, startShown) {
  const s = Math.round(seconds);
  if (missed) return { status: false, text: `Model warm-up done in ${s} s: ${missed} of its jobs did not finish, so the first edit loads their models.` };
  if (startShown) return { status: true, text: `Ready: every model loaded in ${s} s, so the first edit starts at once. Open a plate.` };
  return { status: false, text: `Model warm-up done in ${s} s: every model loaded.` };
}

// ---------- SDR to HDR ----------
// Lightricks' LTX 2.5 SDR-to-HDR IC-LoRA makes 16-bit HDR from an SDR shot. It runs at full size for an EXR plate, unless
// switched off; a video plate stays SDR. A relight keeps the plate's own values under a smooth light ratio, which stay HDR,
// so a render with a light edit leaves it out. A blank plate asks its bit depth: 8-bit, or 16-bit half float, where its
// fluid shot goes through it and becomes an EXR plate: 16-bit is the default once its files are found (?hdr=0 turns it off).
export const HDR_DEPTH = 16;
// New content at the plate's bit depth (Adrien, 2 Nov): a clean plate or a new element matches the plate. One rule per
// kind of plate, read from its pixel format: `bits` (16 for half float, 32 for float), `frames`, the Save Frames format
// a shot's frames pass through on their way to the export, and `hdr`, whether SDR to HDR is on by default. Its switch
// shows for every plate:
//   8-bit video or images: 8-bit PNG frames; SDR to HDR off by default.
//   10-bit or 12-bit video (ProRes among them), 16-bit PNG and TIFF, 10-bit DPX: 16-bit PNG frames; off by default.
//   Half and float samples (EXR, and a float TIFF or DPX: FFmpeg's decoders read 32-bit float): half-float EXR frames; on by
//   default (a light edit stays out while the relight is on hold).
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
// in its own format with no extra files; only the others warn first and deliver an EXR sequence (Adrien, 3 Nov).
export const holdsHdr = (spec, headroom = 1) => !!spec && (plateDepth(spec).float || headroom > 1.001);
export const hdrPlate = (spec) => plateDepth(spec).hdr; // SDR to HDR on by default for this plate
export const wantsHdr = (spec, tools, on) => !!spec && !!on && !tools.includes("light");
// The switch away from the plate's default makes another render, so each setting keeps its own: "|hdr" or "|sdr".
export const hdrKey = (edits, dflt, on) => (on === dflt ? edits : `${edits}|${on ? "hdr" : "sdr"}`);
export const hdrOfKey = (key, dflt) => (key?.endsWith("|hdr") ? true : key?.endsWith("|sdr") ? false : dflt);
// SDR to HDR on a plate whose format cannot hold values above 1.0 (Adrien, 2 Nov): asked before it turns on, then the result is
// an EXR sequence, which the player shows at full precision and the export writes.
export const exrResult = (spec, hdrRan, headroom = 1) => !!hdrRan && !holdsHdr(spec, headroom);
// SDR to HDR for a render: on its own when the plate holds values above 1.0, else when Deliver's bit-depth pass asks for it
export const wantsHdrFor = (spec, headroom, deliverHdr) => holdsHdr(spec, headroom) || !!deliverHdr;
// The 32 GB study, closed (Adrien, 3 Nov): every step finishes on a 32 GB card at 1920 x 1088 x 121, slower than on 96 GB,
// but a 4K plate does not (its first erase still ran after 30 minutes on an RTX 5090). A plate above 2K on a card under
// 48 GB warns when it opens: a 48 GB card reports about 47.5 GiB, a 40 GB one about 39.6.
export const BIG_PLATE = { side: 2048, vram: 46 * 2 ** 30 };
export const bigPlateWarning = (spec, vram) => (spec && vram > 0 && Math.max(spec.width, spec.height) > BIG_PLATE.side && vram < BIG_PLATE.vram
  ? `This plate is ${spec.width} x ${spec.height}, above 2K, and this card has ${Math.round(vram / 2 ** 30)} GB of VRAM. A plate above 2K needs a 96 GB card for now: its renders may not finish here.`
  : null);
export const hdrFps = (fps) => Math.min(30, +fps || 24); // the conditioning frame rate: at most 30, as in Lightricks' workflow
export const blankDepth = (v) => (+v === HDR_DEPTH ? HDR_DEPTH : 8);
export const defaultDepth = (hdrReady) => (hdrReady ? HDR_DEPTH : 8); // a blank plate: 16-bit whenever SDR to HDR can run
// The 8-bit movies of an image sequence (its playback proxy, its review, its SDR-to-HDR pass) hold log values, ACEScct when
// the config has it, so they show what its full-precision frames show; a config without it keeps the model space.
export const viewerSpace = (names, model) => (names.includes("ACEScct") ? "ACEScct" : model);
// While a shot plays, one source shows one kind of frame: its full-precision frames once all of them are in, else its 8-bit
// movie. Mixed, the two alternated as the frames arrived, with two different tone mappings (one cause of the flicker of 29 Oct).
export const drawsDeep = (playing, holdsAll) => !playing || holdsAll;
// A fluid shot's folder, from its HDR frames or its shot in the blank plate's format: what its export zips.
export const fluidRun = (path) => String(path ?? "").replace(/^output[:/]/, "").replace(/\/(hdr|plate)(\/[^/]*)?$/, "");

// Esc, by what the page is doing. A plate that opens stops opening. The strokes in progress are dropped. The edit being
// generated stops and stays the current edit, with its strokes, words and seed ("reopen"): everything else that generates
// stops with it, and nothing starts until Enter. Then the selection goes, then a pass on show gives way to the latest
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

// The status line while edits are hidden: "Edit 2 is being changed: edits 3 and 4 are hidden until it is generated."
export const layersHint = (n, hidden) =>
  (hidden.length ? `Edit ${n} is being changed: ${editList(hidden)} ${hidden.length > 1 ? "are" : "is"} hidden until it is generated.` : "");

// The status line after a stop: nothing starts until Enter. The edit that was being generated keeps its strokes, and the
// edits that waited for their turn stay queued. `edit`: the stopped edit's number, null when no edit was being generated.
export function stopHint({ edit = null, waits = [] } = {}) {
  const list = waits.length ? editList(waits) : "";
  const wait = list ? ` ${list[0].toUpperCase()}${list.slice(1)} ${waits.length > 1 ? "wait" : "waits"}.` : "";
  return edit === null ? `Stopped.${wait} Enter goes on from where it stopped.`
    : `Stopped. Edit ${edit} keeps its strokes, words and seed.${wait} Enter generates again, Ctrl+Enter tries another seed, Esc drops the strokes.`;
}

// Edits are layers, after Generate (Adrien, 11 Nov). An edit above an edit that is made again stays hidden until its own
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
// Each dab's alpha so the dabs of one straight stroke add up to `peak` on its centre line, at a spacing of
// `spacingOverRadius` of their radius
export function dabFlow(peak, spacingOverRadius) {
  let sum = 0;
  for (let k = -Math.ceil(1 / spacingOverRadius); k <= Math.ceil(1 / spacingOverRadius); k++) sum += dabAlpha(Math.abs(k * spacingOverRadius));
  return peak / sum;
}

// ---------- Passes on show ----------
// Each finished step that made a picture shows on every frame from the Render panel, one render of the shot at a time:
// where its movie sits, in the render (`r`) or in its preview size (`pv`), as a path of keys. The tracking steps and the
// export show their matte as a grey movie, drawn through the config's data colour space (`spaces.data`): it shows its own
// values, with no view's tone mapping.
export const PASSES = { erase: ["r", "erased.found.movie_a"], clean: ["pv", "cleanRaw"], shot: ["pv", "raw"], track: ["pv", "painted.found.movie_b"],
  comp: ["pv", "comp"], cleanfull: ["r", "cleanRaw"], full: ["r", "raw"], trackfull: ["r", "full.found.movie_b"], hdr: ["r", "hdrMovie"],
  review: ["r", "play"], export: ["r", "exported.matte"] };
export const MATTE_PASSES = new Set(["erase", "track", "trackfull", "export"]);
const keyPath = (o, path) => path.split(".").reduce((x, k) => x?.[k], o);
export function passMovie(id, r, pv, spaces = {}) { // { url, space, frames } of a finished step, or null
  const at = PASSES[id], store = at && (at[0] === "pv" ? pv : r);
  const url = (at && keyPath(store, at[1])) ?? (id === "review" ? store?.review : null);
  if (!url) return null;
  if (id === "review") return { url, space: store.playSpace ?? store.reviewSpace ?? "@model", frames: store.reviewFrames ?? null };
  // SDR to HDR: its 8-bit movie in log values, and its EXR frames in their own space (ACES2065-1, `spaces.hdr`), for the viewer
  // to draw and inspect them as they are (setShot's fifth argument, framesSpace)
  if (id === "hdr") return { url, space: spaces.log ?? "@model", frames: store.hdrFrames ?? null, framesSpace: store.hdrFrames ? spaces.hdr ?? null : null };
  return { url, space: MATTE_PASSES.has(id) ? spaces.data ?? "@model" : id === "hdr" ? spaces.log ?? "@model" : "@model", frames: null };
}

// ---------- A relight's light plan (2 Nov test on an RTX PRO 6000, approved by Adrien) ----------
// Klein gets two references: the frame, and the light plan, the light's strokes alone on grey (shade strokes in black). Shown
// the frame with the light painted on it, Klein treated the strokes as paint; with the plan, it places the light where it is
// painted, keeps its colours, and relights the rest of the frame to agree with it.
export const PLAN_GREY = "#3a3a3a";
export const lightColors = (colors, color) => {
  const names = [...new Set(colors.filter((c) => !dark(c)).map(colorName))];
  return names.length ? names.join(" and ") : colorName(color);
};
export function lightPlanCaption({ colors = [], color = "#ffd890", words = "" }) {
  const shade = colors.some(dark) ? " The black strokes mark areas that must fall into deep shadow." : "";
  const w = words.trim() ? ` ${words.trim()[0].toUpperCase()}${words.trim().slice(1)}${/[.!?]$/.test(words.trim()) ? "" : "."}` : "";
  return "Relight the first image with the light planned in the second image. The second image is a light plan of the same frame: each coloured " +
    `stroke marks a light source at that exact place, with that colour (${lightColors(colors, color)}).${shade}${w} Make the light source itself ` +
    "visible where it is painted, as a real lamp, window, fire or glow that fits the scene. Light every surface that faces it with its colour and a " +
    "natural falloff, cast new shadows away from it, and remove or soften the old highlights and shadows that disagree with it. Keep every object, " +
    "face and texture, the framing and the camera exactly as in the first image: only the light changes. Do not draw any stroke.";
}

// A fluid shot's own passes, shown from the Render panel with its keyframes open or closed: the control video LTX was
// guided by, the shot as LTX made it, and for a 16-bit plate its SDR-to-HDR frames as a movie in log values.
// The wipe on a fluid row: the step's input on the left, its output on the right, so each step reads against what it was
// given: the blank plate (black) before the keyframes, the keyframes before the shot, the SDR shot before SDR to HDR (Adrien,
// 3 Nov: the left side showed the fluid shot, the plate under the edits, whatever the row).
export const fluidWipeLeft = (id) => ({ fluid_keys: "black", fluid_shot: "fluid_keys", fluid_hdr: "fluid_shot" })[id] ?? null;
export const fluidPasses = (result, spaces = {}) => (result ? [
  result.control && { id: "fluid_keys", label: "Fluid: keyframes", url: result.control, space: "@model" },
  result.preview && { id: "fluid_shot", label: "Fluid: shot", url: result.preview, space: "@model" },
  result.hdr && result.movie && { id: "fluid_hdr", label: "Fluid: SDR to HDR", url: result.movie, space: spaces.log ?? "@model",
    frames: result.hdrFrames ?? null, framesSpace: result.hdrFrames ? spaces.hdr ?? null : null },
].filter(Boolean) : []);
// The workflows each render step runs (a full-size erase pass runs two). A render keeps the record of the steps it ran or
// took again (r.flows), so Models and licences, and an export's MODELS.md, name the models that made the result on show,
// rather than guess them from its tools (viewer report 3, request 2).
export const STEP_FLOWS = { erase: ["matte"], clean: ["clean"], shot: ["shot"], track: ["matte"], comp: ["comp"],
  cleanfull: ["clean", "cleanup"], full: ["shot"], trackfull: ["matte"], hdr: ["hdr"], review: ["review"], export: ["export"] };
// The workflows behind a result: its edits' own (the prompt writer and Klein, SAM's object search for an erase), the
// render's record, and a fluid shot's (with its SDR to HDR)
export function resultFlows({ tools = [], render = [], fluid = false, fluidHdr = false } = {}) {
  const w = new Set(render);
  if (tools.length) ["prompt", "edit"].forEach((n) => w.add(n));
  if (tools.includes("erase")) w.add("snap");
  if (fluid) { w.add("fluid"); if (fluidHdr) w.add("hdr"); }
  return [...w];
}
// The config's data colour space (OCIO's isdata, such as the studio config's Raw), from the spaces /paintaplate/ocio lists
export const dataSpace = (spaces = []) => spaces.find((c) => c.data)?.name ?? null;

// ---------- Pipeline: the paint matte's report ----------
// Follow Matte's summary has a warning line when its largest matte is more than 3 times the tracked object on that frame:
// "Warning: matte up to 31.1x the object at frame 67. Check the composite there." The page's log then shows the summary
// as a warning: the composite takes regenerated pixels there that the edit did not ask for.
export const MATTE_WARN = 3;
export function matteLargest(summary) {
  const m = /Warning: matte up to ([\d.]+)x the object at frame (\d+)\./.exec(summary ?? "");
  return m ? { ratio: +m[1], frame: +m[2], warn: +m[1] > MATTE_WARN } : null;
}

// ---------- Pipeline: the memory profile ----------
// What the page does on the card it runs on, from the VRAM and RAM in ComfyUI's /system_stats. Three profiles to start from;
// the borders move with measurements (tests/gpu_matrix.py writes each case's peak VRAM and RAM).
// - small, under 24 GB of VRAM (the reference is an RTX 4090 Laptop with 16 GB): no model loads before an action needs it,
//   so the prompt writer, Klein and LTX take turns; every LTX pass encodes its guide in tiles and decodes in 256 px tiles
//   (in the SDR-to-HDR decode, 512 px tiles ran out of memory on 16 GB).
// - medium, from 24 GB: the edit models load at start, LTX with the first shot; 512 px tiles.
// - large, from 60 GB: every model loads at start and stays loaded.
// `slots` are workflow slot values (tile, guide_tiled): one set of workflows serves every profile.
export const MEMORY_FROM = { medium: 24e9, large: 60e9 }; // bytes of VRAM: a 24 GB card reports about 25.7e9, a 16 GB one about 17.2e9
export const MEMORY = {
  small: { warm: [], frees: true, slots: { tile: 256, guide_tiled: true }, does: "Models load one at a time and LTX works in 256 px tiles, so each step takes longer than on a larger card" },
  medium: { warm: ["edit", "prompt"], frees: false, slots: { tile: 512, guide_tiled: false }, does: "The edit models load now, LTX with the first shot" },
  large: { warm: ["edit", "prompt", "warm"], frees: false, slots: { tile: 512, guide_tiled: false }, does: "Every model loads now and stays loaded" },
};
// ComfyUI keeps the models of the jobs it has run in memory, ready for the next job. With 16 GB of VRAM under a cap of
// 52 GB of RAM, a full-size shot left LTX and its text encoder there, 35 GB, and the tracking job after it took the rest:
// the system stopped ComfyUI (11 Nov). A profile that `frees` holds one family of models at a time: the page asks
// ComfyUI to free its memory before a job whose family is not that of the job posted before it.
export const FAMILY = { prompt: "klein", edit: "klein", shot: "ltx", clean: "ltx", cleanup: "ltx", fluid: "ltx", hdr: "ltx", warm: "ltx",
  matte: "sam", snap: "sam", ingest: "frames", comp: "frames", review: "frames", export: "frames" }; // by workflow: the models it loads, or frames only
// Speed first where there is room (Adrien, 11 Nov). Under 24 GB of VRAM the card cannot hold two families of models, so a
// change of family frees ComfyUI's memory. On a larger card the models stay loaded, and the memory is freed only when
// RAM is short for the next job's frames: a job that reads the plate can hold RAM_COPIES float32 copies of it (the
// open of 1.11.8 held 8, measured on 11 Nov). The open itself holds the plate once since 1.11.9: 2.8 copies at its peak
// on the laptop and 1.9 on a pod (12 Nov), so `ingest` counts RAM_COPIES_OPEN. A GPU that runs out of memory is retried
// once after a free, on every card (comfy.mjs).
export const RAM_COPIES = 8, RAM_COPIES_OPEN = 3;
export const framesNeed = (width, height, frames, name = "") => // bytes of RAM for the job `name`: the copies, and 4 GB to work in
  (name === "ingest" ? RAM_COPIES_OPEN : RAM_COPIES) * width * height * frames * 12 + 4 * 2 ** 30;
export function freesBefore(profile, last, name, room = null) { // room: { free, need } in bytes of RAM, where ComfyUI gives it
  if (!last || FAMILY[name] === FAMILY[last]) return false;
  return !!profile?.frees || (!!room && room.free < room.need);
}

// ---------- How long a render step takes ----------
// A step's time has three parts: a lead before the sampler's first step (models load, frames are read), the sampling,
// whose progress the page receives, and a tail after it (the decode, the frames, the movie). Until 11 Nov the time left
// was the time run so far, scaled by the progress: 37 s into a preview shot whose first step of 8 had just ended, the
// page said « 4 min 10 s » for a pass that ended 20 s later. Now the sampling is timed by its own pace, between its
// first and its latest step, and the rest comes from what the step took the last time on this machine (the page keeps
// each step's total, lead and tail per size, frame count and memory profile, in paintaplate.times).
export const STEP_FAMILY = { erase: "sam", clean: "ltx", shot: "ltx", track: "sam", comp: "frames", cleanfull: "ltx", full: "ltx", trackfull: "sam", hdr: "ltx", review: "frames", export: "frames" };
// A step's time before it ever ran on this machine (stepGuess): the 96 GB card's reference (STAGES' ref, in seconds at
// REF_SIZE), scaled to the plate, then to the card. A 16 GB card, the small profile, holds one family of models at a time,
// so each job loads its models again: a lead in seconds per family, then a factor per step on the reference's scaled
// seconds. Measured on the laptop (RTX 4090 Laptop GPU, 16 GB of VRAM, 52 GB of RAM) at 1.11.12 on 12 Nov, horse.mp4 at
// 1920 x 1080 and 121 frames: the lead is what a job spent outside its sampler or its tracking loop in ComfyUI's trace,
// and each factor makes the rest. hdr's factor comes from fluid_720's SDR to HDR, the same workflow at 1280 x 704. Other
// profiles announce the references as they are. tests/js/render_estimates.test.mjs holds every measured step within 25%.
export const SLOWER = {
  small: { lead: { ltx: 38, sam: 11, frames: 0 }, erase: 2.1, track: 1, trackfull: 1, clean: 3.35, shot: 1.64, cleanfull: 1.18,
    full: 2.98, hdr: 1.77, comp: 1.3, review: 0.42, export: 0.235 },
};
export const slower = (profile, id) => SLOWER[profile]?.[id] ?? 1;
export const BIG_STEPS = ["full", "cleanfull", "hdr", "review", "export"]; // the steps made at the working size
export const stepSizeOf = (id, plate) => (BIG_STEPS.includes(id) ? plate.work : ["erase", "track", "trackfull"].includes(id) ? plate.track : plate.shot);
const REF_SIZE = 928 * 512 * 97; // pixels times frames, where the references were measured
export function stepGuess(id, ref, plate, profile) { // seconds: the reference scaled to this plate (BIG_STEPS at 0.73 of it), then to this card
  const [w, h] = stepSizeOf(id, plate), scale = (w * h * plate.frames) / REF_SIZE * (BIG_STEPS.includes(id) ? 0.73 : 1);
  return (SLOWER[profile]?.lead?.[STEP_FAMILY[id]] ?? 0) + ref * Math.max(0.25, scale) * slower(profile, id);
}
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
  return { name, why: forced ? `asked for; with ${card}, the page would choose ${auto}` : card, ...MEMORY[name] };
}

// ---------- A seed asked for in the address ----------
// The seed that ?seed= in the address asks for, for the tests: a whole number from 0 to 2^31 - 1, as the page draws them.
// With it every new edit and every new fluid shot starts from that seed, so a run makes the same pictures as the run before.
// Another try (Ctrl+Enter) still draws one. null: no seed is asked for, or the text is not one, and the page draws.
export const askedSeed = (text) => (/^\d{1,10}$/.test(text ?? "") && Number(text) < 2 ** 31 ? Number(text) : null);
