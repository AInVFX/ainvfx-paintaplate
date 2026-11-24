// The lines that tell a person how to change something name the action: « Use the pencil to change it. », not « Its pencil
// changes it. », and say what changes, not what « comes back ».
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const app = readFileSync(new URL("../../web/app.mjs", import.meta.url), "utf8");
const html = readFileSync(new URL("../../web/paintaplate.html", import.meta.url), "utf8");

test("no line says that a tool, a menu or a pencil « changes it », or that strokes « come back »", () => {
  const said = [...`${app}\n${html}`.matchAll(/["`>]([^"`<]*?(?:\b\w+ changes it\b|\bcomes? back on the first frame\b)[^"`<]*)/g)].map((m) => m[1]);
  assert.deepEqual(said.filter((t) => !t.trimStart().startsWith("//")), []);
});

test("the lines that say how to change something say « use … to change it »", () => {
  for (const line of ["Use the pencil to change it.", "Use the pencil to change edit ${num(edit)}.", "Use the pencil to change the fluid shot.",
    "(use right-click > OCIO > Plate to change it)"]) assert.ok(app.includes(line), line);
});
