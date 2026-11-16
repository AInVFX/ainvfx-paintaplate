// Tests of a paint's colours by name (web/logic.mjs: paintHue, colorShares, paintColors, inHues, andList, and their use in
// caption and upsampleRequest): when the words name no colour, the prompt writer's request and the page's own caption name
// the colours that the strokes show, largest share first. Words that name a colour win.
import { test } from "node:test";
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
import { andList, caption, colorShares, inHues, paintColors, paintHue, upsampleRequest } from "../../web/logic.mjs";

const bbox = [400, 300, 600, 700];
const ask = (o) => upsampleRequest({ tool: "paint", bbox, ...o }).request;

test("a painted colour by name, in an object's words", () => {
  const names = { "#000000": "black", "#ffffff": "white", "#808080": "grey", "#555555": "dark grey", "#d32f2f": "red",
    "#f57c00": "orange", "#ffd400": "yellow", "#ffff00": "yellow", "#8b4513": "brown", "#2e7d32": "green", "#00bcd4": "cyan",
    "#1565c0": "blue", "#500000": "dark red", "#7b1fa2": "violet", "#ff00ff": "magenta", "#ffc0cb": "pink", "#c0d8ff": "pale blue" };
  for (const [hex, name] of Object.entries(names)) assert.equal(paintHue(hex), name, hex);
});

test("each colour swatch of the page is named in the request as its title names it", () => {
  const html = readFileSync(new URL("../../web/paintaplate.html", import.meta.url), "utf8");
  const swatches = [...html.matchAll(/data-color="(#[0-9a-f]{6})"[^>]*title="([^"(]+)/g)].filter(([, , t]) => !/light$/i.test(t.trim()));
  assert.ok(swatches.length >= 9, `${swatches.length} swatches`);
  for (const [, hex, title] of swatches) assert.equal(paintHue(hex), title.trim().toLowerCase(), hex);
});

test("a colour's pixels are half opaque or more and close to it; where two strokes blend, a pixel counts for neither", () => {
  const px = (rgba, n) => Array.from({ length: n }, () => rgba).flat();
  const rgba = Uint8ClampedArray.from([...px([211, 47, 47, 255], 60), ...px([0, 0, 0, 255], 30), ...px([105, 23, 23, 255], 5), ...px([211, 47, 47, 60], 5)]);
  assert.deepEqual(colorShares(rgba, ["#d32f2f", "#000000"]), { "#d32f2f": 60, "#000000": 30 });
});

test("the names come largest share first, merged by name; a colour under 5% of the paint is left out", () => {
  assert.deepEqual(paintColors({ words: "saddle", shares: { "#d32f2f": 600, "#000000": 350, "#f57c00": 20 } }), ["red", "black"]);
  assert.deepEqual(paintColors({ words: "", shares: { "#d32f2f": 100, "#c62828": 300, "#000000": 200 } }), ["red", "black"]);
  assert.deepEqual(paintColors({ words: "saddle", shares: {} }), []);
});

test("words that name a colour win: the page names none", () => {
  for (const words of ["a black saddle", "Red car", "a grey wolf", "gray stone", "golden crown", "a navy coat"])
    assert.deepEqual(paintColors({ words, shares: { "#d32f2f": 10 } }), [], words);
  for (const words of ["ice cream", "a goldfish", "a blackboard", "a tank"])
    assert.deepEqual(paintColors({ words, shares: { "#d32f2f": 10 } }), ["red"], words);
});

test("the writer's request and the page's own caption name the strokes' colours, and stay as they were without them", () => {
  assert.match(ask({ words: "saddle", hues: ["red", "black"] }), /with saddle in the drawing's colours, red and black: follow the drawing's outline/);
  assert.match(ask({ words: "", hues: ["yellow"] }), /with an object of the same shape in the drawing's colour, yellow: follow/);
  assert.match(ask({ words: "saddle" }), /with saddle: follow/);
  assert.match(ask({ words: "" }), /with an object of the same shape and colour: follow/);
  assert.equal(upsampleRequest({ tool: "paint", words: "saddle", bbox, hues: ["red", "black"] }).locked[0].desc, "saddle, red and black");
  const own = caption({ tool: "paint", words: "saddle", bbox, hues: ["red", "black"] });
  assert.match(own, /with saddle in the drawing's colours, red and black, following the drawing's outline/);
  assert.match(own, /"desc":"saddle, red and black"/);
  assert.match(caption({ tool: "paint", words: "", bbox }), /with an object of that shape and colour, following/);
  assert.equal(inHues([]), "");
  assert.equal(andList(["<obj_1>", "<obj_2>", "<obj_3>"]), "<obj_1>, <obj_2> and <obj_3>");
});
