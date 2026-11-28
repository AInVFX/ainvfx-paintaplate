import assert from "node:assert/strict";
import test from "node:test";
import { downloadLines, exportFormat, exportWords, missingLine, outputPath, setFolder, X_ELEMENTS, X_STAGES, xDefaults, xRows, xShown } from "../../web/logic.mjs";

// Export's ticks: the zip takes every element ticked (What) at every stage ticked (Stage) that the render has a file for;
// each file is named as the page knows it from the job that made it, so a step reused from another render reaches the zip,
// and a file the ticks ask for with no file on disk stops Export with a line that names it, in the dialog's words.
const cell = (element, stage, label, file = `output:x/${label}`, source = false) => ({ element, stage, label, file, source });
const PAINT = [cell("shot", "preview", "Shot, preview"), cell("composite", "preview", "Composite, preview"), cell("plate", "full", "Source plate", "plates/desk.mp4", true),
  cell("shot", "full", "Shot, full size"), cell("layer", "full", "Layer, full size"), cell("matte", "full", "Matte"), cell("composite", "full", "Composite, full size"),
  cell("plate", "up", "Plate, upscaled"), cell("layer", "up", "Layer, upscaled"), cell("matte", "up", "Matte, upscaled"), cell("composite", "up", "Composite, upscaled")];

test("the dialog's words: five elements and the graph, four stages, each element's detail", () => {
  const w = exportWords({ kind: "edits", steps: { comp: "Composite, full size" } });
  assert.deepEqual(X_ELEMENTS.map((k) => [w.elements[k].label, w.elements[k].detail]), [["Plate", "the plate under the edits"], ["Shot", "the frames the model made"],
    ["Layer", "the shot as the composite blends it"], ["Matte", "where the plate changed, 16-bit PNG frames"], ["Composite", "the result"]]);
  assert.equal(w.elements.graph.label, "ComfyUI graph");
  assert.deepEqual(X_STAGES.map((k) => w.stages[k].label), ["Preview", "Full size", "HDR", "Upscaled"]);
  assert.equal(exportWords({ kind: "edits", bytes: 2.5e9 }).elements.plate.detail, "the plate under the edits, 2.50 GB");
});

test("a render shows only the ticks it has a file for", () => {
  const shown = xShown(PAINT);
  assert.deepEqual([...shown.elements].sort(), ["composite", "layer", "matte", "plate", "shot"]);
  assert.deepEqual([...shown.stages].sort(), ["full", "preview", "up"]);
  assert.deepEqual([...xShown([cell("plate", "full", "Fluid shot, full size"), cell("plate", "hdr", "Plate, HDR")]).stages], ["full", "hdr"]);
});

test("the ticks open on the result at its last stage: Upscaled, else HDR, else Full size", () => {
  const on = (cells, first) => { const d = xDefaults(cells, first); return [[...d.elements], [...d.stages]]; };
  assert.deepEqual(on(PAINT, "composite"), [["composite"], ["up"]]);
  assert.deepEqual(on(PAINT.filter((c) => c.stage !== "up"), "composite"), [["composite"], ["full"]]);
  assert.deepEqual(on([cell("plate", "full", "Source plate"), cell("plate", "hdr", "Plate, HDR")], "plate"), [["plate"], ["hdr"]]);
  assert.deepEqual(on([cell("composite", "preview", "Composite, preview")], "composite"), [["composite"], ["preview"]]);
});

test("the zip takes each ticked element at each ticked stage, once by its name", () => {
  const rows = (elements, stages, cells = PAINT) => xRows(cells, { elements: new Set(elements), stages: new Set(stages) });
  assert.deepEqual(rows(["composite"], ["up"]), [["composite_upscaled", "Composite, upscaled", "output:x/Composite, upscaled", false]]);
  assert.deepEqual(rows(["matte", "shot"], ["preview", "full"]).map((r) => r[0]), ["shot_preview", "shot_full_size", "matte"]);
  assert.deepEqual(rows(["plate"], ["full"]), [["source_plate", "Source plate", "plates/desk.mp4", true]]);
  assert.deepEqual(rows(["layer"], ["preview"]), []); // no cell: no row, and the dialog's Export button waits for another tick
  const both = [cell("matte", "full", "Matte", "output:x/matte"), cell("matte", "hdr", "Matte", "output:x/matte"), cell("composite", "hdr", "Composite, HDR")];
  assert.deepEqual(rows(["matte", "composite"], ["full", "hdr"], both).map((r) => r[0]), ["matte", "composite_hdr"]); // the matte is one picture
});

test("a set sits inside the folder of the set it reads", () => {
  assert.equal(setFolder("paintaplate/p/v3"), "paintaplate/p/v3");
  assert.equal(setFolder("paintaplate/p/v3", { hdr: true }), "paintaplate/p/v3/hdr");
  assert.equal(setFolder("paintaplate/p/v3", { size: "3840x2160" }), "paintaplate/p/v3/upscale/3840x2160/out");
  assert.equal(setFolder("paintaplate/p/v3", { hdr: true, size: "3840x2160" }), "paintaplate/p/v3/hdr/upscale/3840x2160/out");
});

test("the download's lines name each row the zip holds, once", () => {
  assert.equal(downloadLines("desk_v3.zip", ["Composite, upscaled", "Matte", "Matte"]), "Download: desk_v3.zip.\n  Composite, upscaled.\n  Matte.");
});

test("the export's format: a sequence keeps its file type, and every movie is ProRes 4444 XQ, whatever its codec", () => {
  assert.equal(exportFormat({ kind: "video", codec: "h264" }), "ProRes 4444 XQ");
  assert.equal(exportFormat({ kind: "video", codec: "hevc" }), "ProRes 4444 XQ");
  assert.equal(exportFormat({ kind: "sequence", ext: ".png" }), "PNG frames");
  assert.equal(exportFormat(null), "");
});

test("a view address names its file in ComfyUI's output folder", () => {
  assert.equal(outputPath("/view?filename=raw_00001_.mp4&subfolder=paintaplate%2Fp%2Fv2%2Ffull&type=output"), "output:paintaplate/p/v2/full/raw_00001_.mp4");
  assert.equal(outputPath("/view?filename=a.png&subfolder=&type=output"), "output:a.png");
  assert.equal(outputPath("/view?filename=a.png&subfolder=x&type=temp"), null);
  assert.equal(outputPath(undefined), null);
});

test("the line names every file the ticks ask for that is not on disk", () => {
  assert.equal(missingLine(["Shot, full size"]), "Error: Export stopped: Shot, full size has no file on disk.");
  assert.equal(missingLine(["Shot, full size", "Matte", "Composite, upscaled"]), "Error: Export stopped: Shot, full size, Matte and Composite, upscaled have no file on disk.");
});

test("one rule names the zip, its files and the log: ASCII letters, digits, « . », « - » and « _ »", async () => {
  const { fileStem, zipFileName, logFileName } = await import("../../web/logic.mjs");
  assert.equal(fileStem("Désk shot.01"), "D_sk_shot.01");
  assert.equal(fileStem("  über / plate  "), "ber_plate");
  assert.equal(zipFileName("Désk shot.01", "v3", {}), "D_sk_shot.01_v3");
  assert.equal(zipFileName("desk", "v3", { hdr: true }), "desk_v3_hdr");
  assert.equal(zipFileName("desk", "v3", { hdr: true, up: true }), "desk_v3_hdr_upscaled");
  assert.equal(zipFileName("smoke", "fluid_v1", { preview: true }), "smoke_fluid_v1_preview");
  assert.equal(zipFileName("", "v1", {}), "no_plate_v1");
  assert.ok(logFileName("Désk shot.01", new Date(2026, 10, 25, 9, 5)).startsWith("D_sk_shot.01_log_20261125_0905"));
});

test("the export writes the shot, and a Clean's pass under a paint, by Save Plate in the plate's colour space, only when the page asks", async () => {
  const { readFileSync } = await import("node:fs");
  const { fillWorkflow, parseWorkflow } = await import("../../web/logic.mjs");
  const wf = parseWorkflow(JSON.parse(readFileSync(new URL("../../web/workflows/export.json", import.meta.url), "utf8")));
  const outputs = (prompt) => Object.values(prompt).map((n) => n._meta?.output).filter(Boolean);
  const none = fillWorkflow(wf, { prefix: "x/export" }).prompt;
  assert.ok(!outputs(none).includes("shot") && !outputs(none).includes("clean") && !Object.values(none).some((n) => n._meta?.title === "Clean plate pass"));
  const both = fillWorkflow(wf, { prefix: "x/export", shot_prefix: "x/shot", clean_pass: "output:x/full/clean", clean_prefix: "x/clean" }).prompt;
  const save = (out) => Object.values(both).find((n) => n._meta?.output === out);
  const from = (node) => both[node.inputs.images[0]]._meta.title;
  assert.deepEqual([save("shot").class_type, from(save("shot")), save("shot").inputs.keep_untouched], ["PaintAPlate_SavePlate", "Shot in the plate's colour space", false]);
  assert.deepEqual([save("clean").class_type, from(save("clean")), save("clean").inputs.keep_untouched], ["PaintAPlate_SavePlate", "Clean plate pass in the plate's colour space", false]);
});

test("a movie deeper than 10 bits exports as 16-bit PNG frames, and Export says so when it starts", async () => {
  const { deepLine, deepMovie, exportFormat } = await import("../../web/logic.mjs");
  const movie = (bits) => ({ kind: "video", ext: ".mov", bits });
  assert.deepEqual([exportFormat(movie(12)), exportFormat(movie(10)), exportFormat(movie(8)), exportFormat({ kind: "sequence", ext: ".dpx", bits: 12 })],
    ["16-bit PNG frames", "ProRes 4444 XQ", "ProRes 4444 XQ", "DPX frames"]);
  assert.deepEqual([deepMovie(movie(12)), deepMovie(movie(10)), deepMovie({ kind: "video" })], [true, false, false]);
  assert.equal(deepLine(movie(12)), "Export: the plate is a 12-bit movie, so Export writes 16-bit PNG frames, which keep all 12 bits.");
  assert.equal(deepLine(movie(10)), "");
});
