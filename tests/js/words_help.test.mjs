// The Help gives short instructions in plain words: the page's own keys only, the edit described in the text prompt, the
// viewer that displays a step and the edits that are turned on, and five tabs of prose that a person reads in a few minutes.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const html = readFileSync(new URL("../../web/paintaplate.html", import.meta.url), "utf8");
const at = html.indexOf('<dialog id="help"'), help = html.slice(at, html.indexOf("</dialog>", at));
const text = (s) => s.replace(/<[^>]+>/g, " ").replace(/&gt;/g, ">").replace(/\s+/g, " ").trim();
const tab = (name) => text(help.match(new RegExp(`<section [^>]*data-help="${name}"[^>]*>([\\s\\S]*?)</section>`))[1]);
const PROSE = ["start", "tools", "viewer", "colour", "render"];

test("the Help names the page's own keys, and no other program's", () => {
  assert.doesNotMatch(text(help), /\bRV\b/);
});

test("the edit is described in the text prompt", () => {
  assert.match(tab("start"), /describe the change in the text prompt/);
  assert.doesNotMatch(text(help), /describ\w*[^.]* at the top/);
});

test("the Viewer tab says what the viewer displays: the latest result of the edits turned on", () => {
  assert.match(tab("viewer"), /^What the viewer displays The latest result of the edits turned on\./);
});

test("a History row shows its strokes, and its pencil changes the edit", () => {
  assert.match(tab("tools"), /Click a row to see its strokes, or its pencil to change the edit\./);
});

test("the five tabs of prose hold 750 words at most", () => {
  const words = PROSE.reduce((n, t) => n + tab(t).split(" ").length, 0);
  assert.ok(words <= 750, `${words} words`);
});

test("no idiom that a reader who is not fluent must decode", () => {
  const found = ["rubs out", "rub out", "comes back", "goes on", " lays ", " holds ", "at once", "brings back", "leaves"].filter((p) => text(help).includes(p));
  assert.deepEqual(found, []);
});
