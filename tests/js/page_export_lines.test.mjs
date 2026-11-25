// The Export dialog's words for every kind of result, from one source (logic.exportWords), which the Help's Export entry
// opens with. Then two lines that two places of the page share: the key that resets OCIO, in the OCIO menu and in the Help's Keys tab, and the warning of an Export whose
// ComfyUI graph was not written, in the log and on the status line.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { exportWords, secs } from "../../web/logic.mjs";

const STEPS = { comp: "Composite, full size", shot: "Shot, full size", hdr: "SDR to HDR", up: "Composite, upscaled" }; // the Render panel's names, as the page gives them
const read = (f) => readFileSync(new URL(`../../web/${f}`, import.meta.url), "utf8");

test("the Export dialog: one line above its parts for every kind of result, and a note only for what Export waits for or brings", () => {
  const HINT = "Export writes the selected files to ComfyUI's output folder, then downloads them as one zip.";
  const said = (o) => { const w = exportWords(o); assert.equal(w.hint, HINT); return w.note; };
  assert.equal(said({ kind: "edits", ready: true, steps: STEPS }), ""); // written, or ready to write: nothing to add
  assert.equal(said({ kind: "edits", ready: false, left: secs(64, ""), steps: STEPS }), "Composite, full size renders first: about 1 min.");
  assert.equal(said({ kind: "edits", ready: false, steps: STEPS }), "Composite, full size renders first."); // no estimate yet
  assert.equal(said({ kind: "plate", ready: true, exr: true }), "The plate in HDR.");
  assert.equal(said({ kind: "plate", ready: false, left: secs(610, ""), exr: true }), "The plate in HDR. SDR to HDR runs first: about 10 min.");
  assert.equal(said({ kind: "relit", ready: true, exr: true }), "The relit result in HDR.");
  assert.equal(said({ kind: "relit", ready: false, left: secs(610, ""), exr: true }), "The relit result in HDR. SDR to HDR runs first: about 10 min.");
  assert.equal(said({ kind: "fluid" }), "The fluid shot in ProRes 4444 XQ.");
  assert.equal(said({ kind: "fluid", hdr: true }), "The fluid shot in HDR, with the SDR shot in ProRes 4444 XQ.");
});

test("the Help's Export entry opens with the Export dialog's own line, which is written once", () => {
  const html = read("paintaplate.html"), app = read("app.mjs");
  assert.match(html, /<dt>Export<\/dt><dd><span id="help-export"><\/span><\/dd>/); // the whole entry comes from exportWords' help
  assert.ok(html.includes('<p id="x-hint" class="hint"></p>')); // the dialog's line comes from the code, never from the page's file
  assert.ok(app.includes('$("#help-export").textContent = exportWords({ kind: "edits", steps: { comp: labelOf(STAGES.find((st) => st.id === "review"), null) } }).help;'));
  assert.ok(exportWords({ kind: "edits", steps: STEPS }).help.startsWith(`${exportWords({ kind: "edits" }).hint} Frames keep their format, and a movie gives ProRes 4444 XQ.`));
  for (const src of [html, app, read("logic.mjs")]) assert.equal(src.split("then downloads").length - 1, src === read("logic.mjs") ? 1 : 0);
});

test("the dialog names the result's format once: a sequence's own, ProRes 4444 XQ for a movie, EXR frames with SDR to HDR", () => {
  assert.equal(exportWords({ kind: "edits", spec: { kind: "video", codec: "h264" } }).format, "ProRes 4444 XQ");
  assert.equal(exportWords({ kind: "edits", exr: true, spec: { kind: "video", codec: "h264" } }).format, "half-float EXR frames, ACES2065-1");
  assert.equal(exportWords({ kind: "fluid" }).format, "ProRes 4444 XQ");
  assert.equal(exportWords({ kind: "fluid", hdr: true }).format, "half-float EXR frames, ACES2065-1");
});

test("a time reads « about 1 min 40 s left » in the Render panel, and « about 1 min 40 s » in a sentence that says what comes first", () => {
  assert.equal(secs(96), "about 1 min 40 s left");
  assert.equal(secs(96, ""), "about 1 min 40 s");
  assert.equal(secs(5, ""), "about 5 s");
  assert.equal(secs(700, ""), "about 12 min");
  assert.ok(read("app.mjs").includes('left: ready ? "" : secs(renderLeft(true), "")'));
});

test("the Help's Keys tab lists Shift+End beside Shift+Home, as the OCIO menu names it", () => {
  assert.match(read("paintaplate.html"), /<dt>Shift\+Home<\/dt><dd>Reset all colour\.<\/dd>\s*<dt>Shift\+End<\/dt><dd>Reset OCIO: the config's display and view\.<\/dd>/);
  assert.ok(read("app.mjs").includes('["Reset OCIO", "Shift+End", resetOcio'));
});

test("a ComfyUI graph that was not written: one warning for the log, and what to do for the status line, written once", () => {
  const app = read("app.mjs");
  assert.ok(app.includes('const GRAPH_UNWRITTEN = ["Warning: the ComfyUI graph was not written. The zip holds the other files.", "Restart ComfyUI after an update of Paint a plate, then export again."];'));
  assert.equal(app.split("the ComfyUI graph was not written").length - 1, 1);
  assert.ok(app.includes("if (written === false) told(...GRAPH_UNWRITTEN);"));
});
