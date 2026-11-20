// The tooltips, notes and placeholders say what the page does, in plain words, and a sentence that shows in two places is
// written once: the Finish button's tooltip, which the page extends with the passes turned on, and the Preview note, which
// the Help shows as its Preview entry.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (f) => readFileSync(new URL(`../../web/${f}`, import.meta.url), "utf8");
const html = read("paintaplate.html"), app = read("app.mjs"), web = html + app + read("logic.mjs");
const titles = [...html.matchAll(/\btitle="([^"]*)"/g)].map((m) => m[1]);
const notes = [...html.matchAll(/<p[^>]*class="[^"]*(?:hint|note|history-empty)[^"]*"[^>]*>([^<]+)<\/p>/g)].map((m) => m[1]);
const placeholders = [...html.matchAll(/\bplaceholder="([^"]*)"/g)].map((m) => m[1]);

test("no idiom that a reader who is not fluent must decode", () => {
  const lines = [...titles, ...notes, ...placeholders];
  assert.ok(lines.length > 50, `lines found: ${lines.length}`);
  const idioms = ["rub out", "rubs out", "comes back", "come back", "at once", "goes on", "on show", "for the latest", "can change"];
  assert.deepEqual(lines.filter((l) => idioms.some((i) => l.includes(i))), []);
});

test("Generate's tooltip says what it reuses, and Stop's what it keeps", () => {
  assert.ok(titles.includes("Generate (Enter): the edit on the first frame, then the shot. Steps already made are reused."));
  assert.ok(titles.includes("Stop (Esc): finished steps are kept. Generate continues from there."));
});

test("the Scenes tab's note is one sentence", () => {
  assert.ok(notes.includes("Scenes saved on this ComfyUI with Save scene."));
});

test("the Finish button's tooltip names its passes and is written once", () => {
  const tip = "Finish: SDR to HDR and Upscale, after the full-size composite.";
  assert.ok(titles.includes(tip));
  assert.equal(web.split("after the full-size composite.").length - 1, 1);
  assert.match(app, /btn\.title = `\$\{FINISH_TIP\}/);
});

test("the Preview note is written once, and the Help shows it", () => {
  assert.equal(web.split("each pass displays live").length - 1, 1);
  assert.match(html, /<dt>Preview<\/dt><dd id="help-preview"><\/dd>/);
  assert.match(app, /\$\("#help-preview"\)\.textContent = \$\("\.preview-note"\)\.textContent/);
});
