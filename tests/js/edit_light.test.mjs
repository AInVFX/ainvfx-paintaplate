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
    "A strong, focused warm orange light comes from the top right of the frame. Each light brightens the surfaces that " +
    "face it with its colour and falls off with distance; it casts soft shadows away from it, and the old highlights and " +
    "shadows that disagree with it fade. Warm low sun from the right. Keep every object, face and texture, the camera " +
    "angle, the framing and the composition exactly as they are: only the light changes.");
});

test("a broad light, a dim one, strokes of one colour as one light, and shade by place", () => {
  const moon = { color: "#8fb3ff", size: 160 / 1920, points: [[0.05, 0.05], [0.35, 0.08]] };
  const ember = { color: "#7a3008", size: 0.02, points: [[0.5, 0.5], [0.5, 0.52]] };
  const shade = { color: "#000000", size: 200 / 1920, points: [[0.75, 0.6], [0.95, 0.9]] };
  const said = lightIntent({ strokes: [moon, { ...moon, points: [[0.1, 0.2], [0.3, 0.2]] }, ember, shade] });
  assert.match(said, /A strong, broad cool blue light comes from the top left of the frame\./);
  assert.equal(said.match(/cool blue light/g).length, 1); // two strokes of one colour: one light
  assert.match(said, /A dim, focused red light comes from the centre of the frame\./);
  assert.match(said, /The bottom right of the frame falls into deep shadow\./);
  assert.ok(!/undefined|NaN/.test(said));
});

test("shade alone: no sentence about lights", () => {
  const said = lightIntent({ strokes: [{ color: "#000000", size: 0.1, points: [[0.1, 0.5], [0.2, 0.5]] }], words: "dusk." });
  assert.ok(said.includes("The left of the frame falls into deep shadow. Dusk. Keep every object"), said);
  assert.ok(!said.includes("Each light"));
});
