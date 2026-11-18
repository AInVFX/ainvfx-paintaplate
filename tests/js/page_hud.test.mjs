// The page workstream's check of choice 1 on the HUD and the tooltips: every sentence there ends with a full stop.
// A label or a readout (a frame number, a zoom, « Plate ») keeps its form.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

const app = readFileSync(new URL("../../web/app.mjs", import.meta.url), "utf8");
const html = readFileSync(new URL("../../web/paintaplate.html", import.meta.url), "utf8");
const xray = readFileSync(new URL("../../web/xray.mjs", import.meta.url), "utf8");
const LABELS = new Set(["Plate", "Fit", "1:1"]);

test("a HUD line given as one string ends with a full stop", () => {
  const lines = [...app.matchAll(/\bhud\(\s*(["`])((?:\\.|(?!\1)[^\\])*)\1\s*[,)]/g)].map((m) => m[2]).filter((t) => !LABELS.has(t));
  assert.ok(lines.length > 20, `HUD lines found: ${lines.length}`);
  assert.deepEqual(lines.filter((t) => !/[.?!]$/.test(t)), []);
});

test("the X-ray's lines end with a full stop", () => {
  const block = xray.slice(xray.indexOf("XRAY_TEXT = {"), xray.indexOf("};", xray.indexOf("XRAY_TEXT = {")));
  const lines = [...block.matchAll(/"([^"]*)"/g)].map((m) => m[1]);
  assert.equal(lines.length, 6);
  assert.deepEqual(lines.filter((t) => !/[.?!]$/.test(t)), []);
});

test("every tooltip ends with a full stop, but a colour swatch's, which is the colour's name in the request", () => {
  const tags = [...html.matchAll(/<[^>]+>/g)].map((m) => m[0]).filter((tag) => /\btitle="/.test(tag) && !/\bclass="sw"/.test(tag));
  const titles = tags.map((tag) => tag.match(/\btitle="([^"]*)"/)[1]);
  assert.ok(titles.length > 30, `tooltips found: ${titles.length}`);
  assert.deepEqual(titles.filter((t) => !/[.?!]$/.test(t)), []);
});

test("the Help's lines end with a full stop, and none repeats a tooltip word for word", () => {
  const at = html.indexOf('<dialog id="help"'), help = html.slice(at, html.indexOf("</dialog>", at));
  const lines = [...help.matchAll(/<(dd|li|p)[^>]*>([^<]*)<\/\1>/g)].map((m) => m[2].trim()).filter(Boolean);
  assert.ok(lines.length > 40, `Help lines found: ${lines.length}`);
  assert.deepEqual(lines.filter((l) => !/[.?!]$/.test(l)), []);
  const tips = new Set([...html.matchAll(/\btitle="([^"]*)"/g)].map((m) => m[1].replace(/\.$/, "")));
  assert.deepEqual(lines.filter((l) => tips.has(l.replace(/\.$/, ""))), []);
});

test("a tooltip the page sets in code ends with a full stop", () => {
  const titles = [...app.matchAll(/\.title = (["`])((?:\\.|(?!\1)[^\\])*)\1;/g)].map((m) => m[2]);
  assert.ok(titles.length >= 4, `tooltips set in code: ${titles.length}`);
  assert.deepEqual(titles.filter((t) => !/[.?!]$/.test(t)), []);
});
