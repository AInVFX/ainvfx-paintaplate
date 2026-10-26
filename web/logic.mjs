// Pure functions of the page: workflows as data, sizes, captions, time, edit dependencies, the frame cache's ranking.
// No DOM and no state here, so tests/js runs every one of them in Node (node --test).

// ---------- Workflows as data ----------

// Optional links: when every source slot is left empty, the link goes, with every node that fed it. The same rule as
// tools/build_workflows.py (OPTIONAL there; a test checks they match): no erase, nothing to fill before LTX; a relight
// alone, no matte to composite with, nor to save (the export's "matte" output goes with it).
export const OPTIONAL = { hole_mask: ["hole"], fit_mask: ["matte_a", "matte_b"] };

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
