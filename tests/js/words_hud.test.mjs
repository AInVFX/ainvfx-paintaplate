// The HUD and the status line say what the page does, in plain verbs: erase, continue, remove, close, undo. The status line
// after a stop is one sentence, written once in logic.stopHint, and the line once a plate is open says where the edit is
// described: in the text prompt.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stopHint } from "../../web/logic.mjs";

const read = (f) => readFileSync(new URL(`../../web/${f}`, import.meta.url), "utf8");
const code = (src) => src.split("\n").map((l) => l.split(/(?<![:"'`])\/\/ /)[0]).join("\n"); // each line without its comment
const app = code(read("app.mjs")), logic = code(read("logic.mjs"));

test("no idiom that a reader who is not fluent must decode", () => {
  const idioms = ["rub out", "rub strokes out", "goes on", "Esc drops", "Esc leaves", "brings it back", "as shot", "Clean takes", "out of the wipe", "keeps the line"];
  assert.deepEqual(idioms.filter((i) => app.includes(i) || logic.includes(i)), []);
});

test("after a stop, Enter continues: one sentence, which the HUD and the status line share", () => {
  assert.equal(stopHint(), "Stopped. Enter continues from there.");
  assert.match(stopHint({ edit: 2 }), /Esc removes the strokes\.$/);
  assert.match(app, /: stopHint\(\), 4000\);/);
});

test("once a plate is open, the status line says the edit is described in the text prompt", () => {
  assert.ok(app.includes('const next = "Describe the edit in the text prompt, paint on the frame, then Generate."'));
  assert.ok(app.includes("New edit: describe it in the text prompt, then paint."));
});

test("Generate's HUD line names the shot as its tooltip does, and the preview composite's line says Export can write now", () => {
  assert.ok(app.includes('"Press Enter to make the edit, then the shot. Press Esc to cancel."'));
  assert.ok(app.includes("The full-size passes follow; Export can write the result now."));
  assert.ok(!app.includes("at any time"));
});
