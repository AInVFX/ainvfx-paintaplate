// The viewer displays a step, and an edit is turned on: no line a person reads says « on show ». The sentence that leads back
// to the latest result is written once, for the Render panel's note, the HUD and each finished step's tooltip.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (f) => readFileSync(new URL(`../../web/${f}`, import.meta.url), "utf8");
const code = (src) => src.split("\n").map((l) => l.split(/(?<![:"'`])\/\/ /)[0]).join("\n"); // each line without its comment
const files = ["app.mjs", "logic.mjs", "xray.mjs", "frames.mjs"].map((f) => [f, code(read(f))]);

test("no line a person reads says « on show »", () => {
  assert.deepEqual(files.filter(([, src]) => /\bon show\b/.test(src)).map(([f]) => f), []);
  const html = read("paintaplate.html").replace(/<!--[\s\S]*?-->/g, "");
  assert.doesNotMatch(html, /\bon show\b/);
});

test("the way back to the latest result is one sentence, written once", () => {
  const all = files.map(([, src]) => src).join("\n") + read("paintaplate.html");
  assert.equal(all.split("to display the latest result").length - 1, 1);
  assert.equal(all.split("${BACK_TO_LATEST}.").length - 1, 3);
});

test("a finished step's tooltip, with the wipe's Ctrl+click, ends with one full stop", () => {
  assert.ok(read("app.mjs").includes(`li.title += " Ctrl+click to add it to the wipe.";`));
});
