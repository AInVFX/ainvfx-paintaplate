// A fluid is smoke, fire, water and more: every line a person reads about a fluid shot says so, and none lists smoke, steam
// and fire alone. The text prompt's line on a blank plate says where the fluid is described.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (f) => readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
const html = read("web/paintaplate.html"), app = read("web/app.mjs");
const models = JSON.parse(read("web/models.json")).models;
const help = html.slice(html.indexOf('<dialog id="help"'), html.indexOf("</dialog>", html.indexOf('<dialog id="help"')));
const constant = (name) => app.match(new RegExp(`const ${name} = ((?:"[^"]*"(?: \\+\\s*)?)+);`))[1].replace(/"\s*\+\s*"/g, "").slice(1, -1);
const LINES = {
  "the Help's Fluid shot entry": help.match(/<dt>Fluid shot<\/dt><dd>([^<]*)<\/dd>/)[1],
  "the Fluid shot panel's note": html.match(/<section id="fluid"[^>]*>\s*<h2>Fluid shot[\s\S]*?<p class="hint">([^<]*)<\/p>/)[1],
  "the Blank plate tab's note": html.match(/data-tab="blank"[^>]*>\s*<p class="hint">([^<]*)<\/p>/)[1],
  "the text prompt's placeholder": constant("FLUID_HINT"),
  "History's note on a blank plate": constant("FLUID_HELP"),
  "ainvfx-fluid's line in Models and licences": models.find((m) => m.id === "fluid").use,
};

test("every line about a fluid shot names water among its fluids", () => {
  assert.deepEqual(Object.entries(LINES).filter(([, l]) => !/water/.test(l)).map(([k]) => k), []);
});

test("no line lists smoke, steam and fire as all a fluid shot makes", () => {
  assert.deepEqual(Object.entries(LINES).filter(([, l]) => /steam,? or fire|smoke, steam/.test(l)).map(([k]) => k), []);
});

test("on a blank plate, the status line says the fluid is described in the text prompt", () => {
  assert.ok(app.includes('"Blank plate: paint your fluid on a keyframe, describe it in the text prompt, then press Enter."'));
});
