// The Export dialog's rows say what each file is, in the Render panel's own step names, from one source
// (logic.exportWords). The page's file holds no row words, and the log's download line names the rows the zip holds.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { downloadLines, EXR_FRAMES, exportWords, plateFormat, zipNames } from "../../web/logic.mjs";

const read = (f) => readFileSync(new URL(`../../web/${f}`, import.meta.url), "utf8");
const STEPS = { comp: "Composite, full size", shot: "Shot, full size", hdr: "SDR to HDR", up: "Composite, upscaled" }; // as the page gives them
const MOVIE = { kind: "video", codec: "h264", ext: ".mp4" }, FRAMES = { kind: "sequence", ext: ".exr" }, PRORES = { kind: "video", codec: "prores", profile: "4444", ext: ".mov" };
const shown = (w) => Object.entries(w.rows).filter(([k, r]) => r.shown && k !== "upscaled").map(([k, r]) => [k, r.label, r.detail]);

test("a movie plate: the composite in its own format, the matte, the shot, and no second movie of the composite", () => {
  assert.deepEqual(shown(exportWords({ kind: "edits", spec: MOVIE, steps: STEPS })), [
    ["export", "Composite, full size", "H.264 movie"], ["matte", "Matte", "where the plate changed, PNG frames"],
    ["shot", "Shot, full size", "the whole frame as the model made it, H.264 MP4"], ["graph", "ComfyUI graph", "the scene as one ComfyUI workflow, with the images it loads"]]);
});

test("a plate of frames, or SDR to HDR's EXR frames: the same composite as a movie too", () => {
  for (const w of [exportWords({ kind: "edits", spec: FRAMES, steps: STEPS }), exportWords({ kind: "edits", spec: MOVIE, exr: true, steps: STEPS })]) {
    assert.deepEqual(w.rows.review, { label: "Composite, full size, as a movie", detail: "H.264 MP4", shown: true });
  }
  assert.equal(exportWords({ kind: "edits", spec: FRAMES, steps: STEPS }).rows.export.detail, "EXR frames");
  assert.equal(exportWords({ kind: "edits", spec: MOVIE, exr: true, steps: STEPS }).rows.export.detail, EXR_FRAMES);
});

test("a format reads by its name: H.264, ProRes with its profile, a sequence's file type", () => {
  assert.equal(plateFormat(MOVIE), "H.264 movie");
  assert.equal(plateFormat(PRORES), "ProRes 4444 movie");
  assert.equal(plateFormat({ kind: "video", codec: "hevc" }), "H.265 movie");
  assert.equal(plateFormat({ kind: "sequence", ext: ".png" }), "PNG frames");
  assert.equal(exportWords({ kind: "edits", spec: PRORES, steps: STEPS }).rows.review.shown, false); // a blank plate's composite is a movie
});

test("the rows and the note take the step names they are given: a Light edit's composite is « Light transfer, full size »", () => {
  const w = exportWords({ kind: "edits", spec: MOVIE, ready: false, left: "about 1 min", steps: { ...STEPS, comp: "Light transfer, full size" } });
  assert.equal(w.rows.export.label, "Light transfer, full size");
  assert.equal(w.note, "Light transfer, full size renders first: about 1 min.");
});

test("SDR to HDR on the plate alone or a relit result, Upscale on the plate alone, a fluid shot alone: one row of their own", () => {
  for (const [kind, label] of [["plate", "SDR to HDR"], ["relit", "SDR to HDR"], ["upscaled", "Composite, upscaled"], ["fluid", "Fluid shot"]]) {
    const w = exportWords({ kind, spec: MOVIE, exr: kind !== "upscaled", steps: STEPS });
    assert.equal(w.rows.export.label, label, kind);
    assert.deepEqual(["review", "matte", "shot"].filter((k) => w.rows[k].shown), [], kind);
  }
  assert.equal(exportWords({ kind: "fluid", steps: STEPS }).rows.export.detail, "ProRes 4444 movie");
});

test("the log's download line: the zip, then one line per row it holds; the layer has no row", () => {
  const { rows } = exportWords({ kind: "edits", spec: FRAMES, steps: STEPS });
  assert.equal(downloadLines("room_paintaplate_v1.zip", ["export", "layer", "matte", "review", "shot", "upscaled", "graph"], rows),
    "Download: room_paintaplate_v1.zip.\n  Composite, full size.\n  Matte.\n  Composite, full size, as a movie.\n  Shot, full size.\n  Composite, upscaled.\n  ComfyUI graph.");
  assert.equal(downloadLines("fluid_v1.zip", ["hdr", "plate", "preview"], exportWords({ kind: "fluid", hdr: true, steps: STEPS }).rows), "Download: fluid_v1.zip.\n  Fluid shot.");
});

test("one source: the page's file holds no row words, and logic.mjs never writes a step's name", () => {
  const html = read("paintaplate.html"), at = html.indexOf('<dialog id="export">'), dialog = html.slice(at, html.indexOf("</dialog>", at));
  assert.equal((dialog.match(/<label class="check"/g) ?? []).length, 6);
  assert.equal((dialog.match(/<span><\/span> <small( id="x-format")?><\/small><\/label>/g) ?? []).length, 6); // every label and detail comes from exportWords
  for (const old of ["The result", "Its matte", "The review movie", "The regenerated shot"]) assert.ok(!dialog.includes(old), old);
  const logic = read("logic.mjs");
  for (const step of ["Composite, full size", "Shot, full size"]) assert.ok(!logic.includes(step), `${step}: written once, in the Render panel's steps`);
  assert.ok(read("app.mjs").includes('steps: { comp: name("review"), shot: name("full"), hdr: name("hdr"), up: name(up) }'));
});

test("the source plate: a row of its own with its size, never on a blank plate; its files and its upscaled twin take its name", () => {
  const w = exportWords({ kind: "edits", spec: MOVIE, steps: STEPS, source: true, bytes: 3.1e9 });
  assert.deepEqual(w.rows.source, { label: "Source plate", detail: "the plate's own files, 3.10 GB", shown: true });
  assert.equal(exportWords({ kind: "edits", spec: MOVIE, steps: STEPS, source: true }).rows.source.detail, "the plate's own files"); // before its size comes
  assert.equal(exportWords({ kind: "edits", spec: MOVIE, steps: STEPS }).rows.source.shown, false); // a blank plate's page passes source: false
  assert.equal(exportWords({ kind: "fluid", steps: STEPS, source: true }).rows.source.shown, false);
  assert.deepEqual([w.zip.source, w.zip.up.plate], ["source_plate", "source_plate_upscaled"]);
  assert.deepEqual(zipNames(w.rows, "SDR to HDR").source, "source_plate");
  assert.equal(downloadLines("desk_v1.zip", ["export", "source"], w.rows), "Download: desk_v1.zip.\n  Composite, full size.\n  Source plate.");
});
