// The fluid shot's two steps, as they announce themselves before they ever ran (logic.stepGuess), against their measures on
// a 96 GB GPU (an RTX PRO 6000 Blackwell, 95 GB of VRAM), read from the GPU cases' reports with the models loaded: STAGES'
// references are that GPU's own seconds, so these rows hold within 25%.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { stepGuess } from "../../web/logic.mjs";

const app = readFileSync(new URL("../../web/app.mjs", import.meta.url), "utf8");
const REF = Object.fromEntries([...app.matchAll(/\{ id: "(\w+)", label: "[^"]*", ref: (\d+)/g)].map((m) => [m[1], Number(m[2])]));
const P1088 = { work: [1920, 1088], track: [960, 544], shot: [960, 544], frames: 121 }; // fluid_1080_edit, Half size
const P704 = { work: [1280, 704], track: [928, 512], shot: [640, 352], frames: 121 }; // fluid_720
const MEASURED = [ // [case, step, seconds, plate]
  ["fluid_1080_edit", "fluid", 35.4, P1088], ["fluid_1080_edit", "fluidfull", 75.1, P1088], ["fluid_720, Preview off", "fluidfull", 35.0, P704],
];

test("on a 96 GB GPU, the fluid shot's preview and full size announce themselves within 25% of what they took", () => {
  const off = MEASURED.map(([name, id, s, plate]) => [`${name} ${id}`, s, stepGuess(id, REF[id], plate, "large")]).filter(([, s, g]) => Math.abs(g - s) > 0.25 * s);
  assert.deepEqual(off, []);
});

// Measures on an RTX 4090 Laptop GPU (16 GB of VRAM, 52 GB of RAM): a 16-bit fluid shot at 1280 x 704, 121
// frames, the preview at Half size, the models loading for the first pass
const LAPTOP = [["fluid_1280x704_25fps_121f", "fluid", 45.1, P704], ["fluid_1280x704_25fps_121f", "fluidfull", 83.7, P704]];

test("on a 16 GB GPU, the fluid shot's steps announce themselves within 25% of what they took", () => {
  const off = LAPTOP.map(([name, id, s, plate]) => [`${name} ${id}`, s, stepGuess(id, REF[id], plate, "small")]).filter(([, s, g]) => Math.abs(g - s) > 0.25 * s);
  assert.deepEqual(off, []);
});
