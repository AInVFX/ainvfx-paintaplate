// The time a step announces before it ever ran on a machine: logic.stepGuess, the 96 GB GPU's reference from STAGES, scaled
// to the plate, then to the GPU. The rows are measures on an RTX 4090 Laptop GPU (16 GB of VRAM, 52 GB of RAM), read from the
// page's log. Every row holds within 25% of its measure, except those OUTSIDE names, each with why.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SLOWER, stepGuess, stepSizeOf, timeId } from "../../web/logic.mjs";

const app = readFileSync(new URL("../../web/app.mjs", import.meta.url), "utf8");
const REF = Object.fromEntries([...app.matchAll(/\{ id: "(\w+)", label: "[^"]*", ref: (\d+)/g)].map((m) => [m[1], Number(m[2])]));
// the working sizes in the laptop's logs: horse.mp4 at 1920 x 1080, and the fluid shot at 1280 x 704, 121 frames each
const HORSE = { work: [1920, 1088], track: [960, 544], shot: [640, 352], frames: 121 };
const FLUID = { work: [1280, 704], track: [928, 512], shot: [640, 352], frames: 121 };
const MEASURED = [ // [case, step, seconds, plate]
  ["horse_erase", "erase", 28.7], ["horse_erase", "clean", 59.1], ["horse_erase", "comp", 11.9],
  ["horse_erase", "cleanfull", 194.3], ["horse_erase", "review", 20.5], ["horse_erase", "export", 9.3],
  ["horse_erase_barn", "erase", 27.7], ["horse_erase_barn", "clean", 57.0], ["horse_erase_barn", "comp", 11.5],
  ["horse_erase_barn", "cleanfull", 186.7], ["horse_erase_barn", "review", 19.4], ["horse_erase_barn", "export", 9.3],
  ["horse_cow", "shot", 58.2], ["horse_cow", "track", 32.3], ["horse_cow", "comp", 10.4], ["horse_cow", "full", 576.5],
  ["horse_cow", "trackfull", 34.4], ["horse_cow", "review", 19.7], ["horse_cow", "export", 10.0],
  ["horse_light", "shot", 56.6], ["horse_light", "comp", 8.9], ["horse_light", "full", 574.8], ["horse_light", "review", 23.5],
  ["horse_light", "export", 6.1],
  ["horse_erase 1.11.10", "erase", 28.5], ["horse_erase 1.11.10", "clean", 57.4], ["horse_erase 1.11.10", "comp", 10.9],
  ["horse_erase 1.11.10", "cleanfull", 186.1], ["horse_erase 1.11.10", "review", 17.6], ["horse_erase 1.11.10", "export", 9.0],
  ["fluid_720", "hdr", 175.3, FLUID], // the fluid shot's SDR to HDR: the same workflow as the render's
  ["fluid_720 0.45.3", "hdr", 172.1, FLUID], ["hdr_cow", "hdr", 606.4], // SDR to HDR at 1280 x 704 and at 1920 x 1088
];
const OUTSIDE = { "horse_light export": "a relight's export writes no matte: 19 nodes against 27, 6.1 s against 9.3 to 10.0 s" };

test("before a step ever ran on the laptop, its announcement holds within 25% of what it took", () => {
  assert.equal(Object.keys(REF).length, 11, "a reference for every step of STAGES");
  const off = MEASURED.filter(([, id, took, plate = HORSE]) => Math.abs(stepGuess(id, REF[id], plate, "small") - took) > 0.25 * took);
  assert.deepEqual(off.map(([where, id]) => `${where} ${id}`), Object.keys(OUTSIDE));
});

test("other cards announce the references as they are", () => {
  assert.equal(Math.round(stepGuess("full", REF.full, HORSE, "large")), 180); // the pod measured 141 to 152 s
  assert.equal(Math.round(stepGuess("clean", REF.clean, HORSE, "medium")), 6);
});

test("on a 16 GB card a step pays its models' load, so a short plate does not make a short step", () => {
  const short = { ...HORSE, frames: 25 };
  assert.ok(stepGuess("clean", REF.clean, short, "small") > SLOWER.small.lead.ltx);
  assert.deepEqual([stepSizeOf("trackfull", HORSE), stepSizeOf("review", HORSE), stepSizeOf("shot", HORSE)], [[960, 544], [1920, 1088], [640, 352]]);
});

test("with SDR to HDR on, the full-size composite and the export announce their EXR frames' seconds", () => {
  for (const [id, took] of [["review", 37.7], ["export", 14.6]]) { // the HDR test plate, made from horse.mp4: its size and frames
    const guess = stepGuess(id, REF[id], HORSE, "small", true);
    assert.ok(Math.abs(guess - took) <= 0.25 * took, `${id}: ${guess.toFixed(1)} s announced, ${took} s measured`);
  }
  assert.equal(stepGuess("shot", REF.shot, HORSE, "small", true), stepGuess("shot", REF.shot, HORSE, "small"));
  assert.deepEqual([timeId("review", true), timeId("review", false), timeId("shot", true)], ["review+hdr", "review", "shot"]);
});
