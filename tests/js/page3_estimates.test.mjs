// What a step announces before it ever ran (logic.stepGuess), against what it took. Small: an RTX 4090 Laptop GPU, 16 GB of
// VRAM, 52 GB of RAM. Large: an RTX PRO 6000 Blackwell Server Edition, 96 GB of VRAM, 175 GB of RAM, ComfyUI started with
// --highvram. ComfyUI 0.45.3 on both. Every row holds within 25% of its measure.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { SLOWER, startsLoaded, stepFamily, stepGuess, timeId } from "../../web/logic.mjs";

const app = readFileSync(new URL("../../web/app.mjs", import.meta.url), "utf8");
const REF = Object.fromEntries([...app.matchAll(/\{ id: "(\w+)", label: "[^"]*", ref: (\d+)/g)].map((m) => [m[1], Number(m[2])]));
// The working sizes the page gives each plate, with the preview at half size
const BLANK = { work: [960, 512], track: [960, 512], shot: [480, 256], frames: 33 }; // a blank plate of 960 x 512, a fluid shot
const HORSE = { work: [1920, 1088], track: [960, 544], shot: [960, 544], frames: 121 }; // horse.mp4, 1920 x 1080
const LONG = { ...HORSE, frames: 497 }; // horse.mp4 back and forth, 25 fps
const WIDE = { work: [960, 544], track: [960, 544], shot: [480, 272], frames: 1001 }; // 960 x 544, 50 fps
const UHD = HORSE; // a 3840 x 2160 plate: its shot and its composite are made at 1920 x 1088

const ROWS = [ // [step, seconds, plate, profile, the family of the job before it]
  ["fluid", 5.8, BLANK, "small", "ltx"], // « Fluid shot, preview », made again: LTX loaded
  ["shot", 6.1, BLANK, "small", "ltx"], // « Shot, preview » right after the fluid shot
  ["track", 33.7, BLANK, "small", "ltx"], ["track", 29.1, BLANK, "small", "ltx"], ["trackfull", 29.1, BLANK, "small", "ltx"],
  ["trackfull", 95.7, HORSE, "small", "ltx"], ["erase", 45.6, HORSE, "small", "klein"], // the matte made from SAM 3.1's answers
  ["full", 141, HORSE, "large", "frames"], ["full", 152, HORSE, "large", "frames"], ["full", 165, UHD, "large", "frames"],
  ["full", 457, WIDE, "large", "klein"], ["full", 1402, LONG, "large", "klein"],
  ["review", 51, UHD, "large", "sam"], ["review", 63, WIDE, "large", "sam"], ["review", 78, LONG, "large", "sam"],
];

test("each measure holds within 25% of what the step announces", () => {
  const off = ROWS.map(([id, took, plate, profile, before]) => [id, took, profile, stepGuess(id, REF[id], plate, profile, false, before)])
    .filter(([, took, , guess]) => Math.abs(guess - took) > 0.25 * took);
  assert.deepEqual(off, []);
});

test("on a 16 GB GPU a step pays its family's load only after a job of another family", () => {
  const after = (before) => stepGuess("shot", REF.shot, HORSE, "small", false, before);
  assert.equal(after(null), after("klein")); // nothing before it, or the edit's models: LTX loads first
  assert.ok(Math.abs(after("klein") - after("ltx") - SLOWER.small.lead.ltx) < 1e-9);
  assert.equal(stepGuess("full", REF.full, HORSE, "large", false, "klein"), stepGuess("full", REF.full, HORSE, "large", false, "ltx")); // a large GPU keeps its models
  assert.deepEqual([startsLoaded("fluidfull", "ltx"), startsLoaded("track", "ltx"), startsLoaded("shot", null)], [true, false, false]);
  assert.deepEqual([stepFamily("trackfull"), stepFamily("review"), stepFamily("upcomp")], ["sam", "frames", null]);
});

test("a step that starts with its models loaded keeps its seconds apart", () => {
  assert.deepEqual([timeId("shot", false, true), timeId("review", true, true), timeId("review", true), timeId("shot")], ["shot+loaded", "review+hdr+loaded", "review+hdr", "shot"]);
  assert.equal(timeId("fluidfull", false, false), "fluidfull+cold"); // a mean kept before loaded and cold were told apart is not read as a cold one
});
