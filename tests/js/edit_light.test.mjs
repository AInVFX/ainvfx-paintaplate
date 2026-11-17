// The edit workstream's tests of a relight's strokes read as intentions (web/logic.mjs: lightIntent), the prompt that
// tests/light_probe.py gives Klein with the frame alone.
import { test } from "node:test";
import assert from "node:assert/strict";
import { lightIntent } from "../../web/logic.mjs";

test("each light: its colour, strength, spread and place; then the light's behaviour, the words and what stays", () => {
  // the GPU case horse_light: three points at the top right, 64 px across on a 1920 px frame, the tool's colour
  const sun = { color: "#ffd890", size: 64 / 1920, points: [[0.92, 0.18], [0.95, 0.28], [0.92, 0.38]] };
  const said = lightIntent({ strokes: [sun], words: "warm low sun from the right" });
  assert.equal(said, "Relight the whole scene with new light, as if it were photographed under that light. " +
    "A strong, focused warm white light comes from the top right of the frame. Each light brightens the surfaces that " +
    "face it with its colour and falls off with distance; it casts soft shadows away from it, and the old highlights and " +
    "shadows that disagree with it fade. Warm low sun from the right. Keep every object, face and texture, the camera " +
    "angle, the framing and the composition exactly as they are: only the light changes.");
});

test("a broad light, a dim one, strokes of one colour as one light, and shade by place", () => {
  const moon = { color: "#8fb3ff", size: 160 / 1920, points: [[0.05, 0.05], [0.35, 0.08]] };
  const ember = { color: "#7a3008", size: 0.02, points: [[0.5, 0.5], [0.5, 0.52]] };
  const shade = { color: "#000000", size: 200 / 1920, points: [[0.75, 0.6], [0.95, 0.9]] };
  const said = lightIntent({ strokes: [moon, { ...moon, points: [[0.1, 0.2], [0.3, 0.2]] }, ember, shade] });
  assert.match(said, /A strong, broad pale blue light comes from the top left of the frame\./);
  assert.equal(said.match(/pale blue light/g).length, 1); // two strokes of one colour: one light
  assert.match(said, /A dim, focused brown light comes from the centre of the frame\./);
  assert.match(said, /The bottom right of the frame falls into deep shadow\./);
  assert.ok(!/undefined|NaN/.test(said));
});

test("shade alone: no sentence about lights", () => {
  const said = lightIntent({ strokes: [{ color: "#000000", size: 0.1, points: [[0.1, 0.5], [0.2, 0.5]] }], words: "dusk." });
  assert.ok(said.includes("The left of the frame falls into deep shadow. Dusk. Keep every object"), said);
  assert.ok(!said.includes("Each light"));
});

test("a small light inside the frame shows its source where it is drawn, placed by a row of Klein's layout table", () => {
  const patch = { color: "#ffeb3b", size: 50 / 1920, points: [[0.44, 0.2], [0.45, 0.2]] }; // a yellow patch above a building
  const said = lightIntent({ strokes: [patch], aspect: 16 / 9 });
  assert.match(said, /The yellow light's source <light_1> is visible in the frame: the sun, small and very bright\./);
  assert.match(said, /only the light changes, and each light's source shows where it is placed\. \[\{"id": "light_1", "from": "target", "src_bbox": null, "tgt_bbox": \[177, 427, 223, 463\], /);
  const edge = lightIntent({ strokes: [{ ...patch, points: [[0.985, 0.2], [0.99, 0.2]] }] }); // light from outside the frame
  const wash = lightIntent({ strokes: [{ ...patch, size: 0.1, points: [[0.15, 0.22], [0.85, 0.22]] }] }); // a sunset band
  for (const t of [edge, wash]) assert.ok(!t.includes("<light_") && t.endsWith("only the light changes."), t);
});

test("strokes of one colour that touch make one source; apart, two; a shade never shows a source", () => {
  const dab = (x, y) => ({ color: "#ffb060", size: 0.02, points: [[x, y], [x + 0.005, y]] });
  const one = lightIntent({ strokes: [dab(0.5, 0.5), dab(0.51, 0.505), dab(0.52, 0.51)] });
  assert.equal(one.match(/<light_\d>/g).length, 1, one);
  const two = lightIntent({ strokes: [dab(0.2, 0.5), dab(0.7, 0.5), { color: "#000000", size: 0.02, points: [[0.4, 0.4], [0.41, 0.4]] }] });
  assert.deepEqual(two.match(/"id": "light_\d"/g), ['"id": "light_1"', '"id": "light_2"'], two);
  assert.ok(two.includes("falls into deep shadow"), two);
});

test("the sources do not depend on the strokes' order: two that touch only once joined still join a third", () => {
  const at = (x0, y0, x1, y1) => ({ color: "#ffb060", size: 0.01, points: [[x0 + 0.005, y0 + 0.005 * 16 / 9], [x1 - 0.005, y1 - 0.005 * 16 / 9]] });
  const a = at(0.5, 0.5, 0.53, 0.53), b = at(0.42, 0.42, 0.45, 0.51), c = at(0.44, 0.38, 0.51, 0.43); // b and c touch; together they reach a
  for (const order of [[a, b, c], [b, c, a], [c, a, b]])
    assert.equal(lightIntent({ strokes: order, aspect: 16 / 9 }).match(/"id": "light_\d"/g).length, 1);
});

test("a dab is a source whatever the brush's size: its path decides, not its paint", () => {
  // a 174 px brush on a 1920 x 1088 frame, its path from x 405 to 467 and y 211 to 319: its paint covers about 12% by 26%
  // of the frame, its path 3% by 10%
  const W = 1920, H = 1088, at = ([x, y]) => [x / W, y / H];
  const sun = { color: "#fbc02d", size: 174 / W, points: [[425, 254], [405, 211], [467, 265], [405, 319], [467, 300]].map(at) };
  const said = lightIntent({ strokes: [sun], words: "Sunset, with sun just above the skyscraper on the left of image", aspect: W / H });
  assert.match(said, /A strong(, broad|, focused)? yellow light comes from the top left of the frame\./);
  assert.match(said, /The yellow light's source <light_1> is visible in the frame: the sun, small and very bright\./);
  assert.ok(said.includes('"tgt_bbox": [114, 166, 373, 289]'), said); // the painted area, where the dab is
  const wash = [[100, 250], [1800, 260]], edge = [[1900, 300], [1910, 380]]; // dragged across the frame; at its edge
  for (const pts of [wash, edge]) assert.ok(!lightIntent({ strokes: [{ ...sun, points: pts.map(at) }], aspect: W / H }).includes("<light_"), pts);
  for (const size of [8, 174, 400]) // a click of any brush size
    assert.match(lightIntent({ strokes: [{ ...sun, size: size / W, points: [at([960, 300])] }], aspect: W / H }), /<light_1>/, size);
});

test("a source is named by the words when they name a kind of light; with none, a warm source in the top third is the sun", () => {
  const dab = (color, y) => ({ color, size: 0.02, points: [[0.4, y], [0.41, y]] });
  const named = (t) => t.match(/is visible in the frame: ([^.]+)\./)[1];
  assert.equal(named(lightIntent({ strokes: [dab("#fbc02d", 0.15)] })), "the sun, small and very bright"); // warm, in the top third
  assert.equal(named(lightIntent({ strokes: [dab("#ffd890", 0.2)] })), "the sun, small and very bright"); // warm white too
  assert.equal(named(lightIntent({ strokes: [dab("#fbc02d", 0.6)] })), "a small, very bright yellow light"); // lower in the frame
  assert.equal(named(lightIntent({ strokes: [dab("#1976d2", 0.15)] })), "a small, very bright blue light"); // a cool colour
  assert.equal(named(lightIntent({ strokes: [dab("#fbc02d", 0.15)], words: "a street lamp at dusk" })), "the street lamp, small and very bright");
  assert.equal(named(lightIntent({ strokes: [dab("#fbc02d", 0.6)], words: "Sunset, with sun just above the skyscraper" })), "the sun, small and very bright");
  assert.equal(named(lightIntent({ strokes: [dab("#fbc02d", 0.6)], words: "sunset glow" })), "a small, very bright yellow light"); // « sunset » names no source
  const said = lightIntent({ strokes: [dab("#fbc02d", 0.15)] });
  assert.ok(said.includes('"desc": "the light\'s source: the sun, small and very bright"'), said); // the row says it as the sentence does
});
