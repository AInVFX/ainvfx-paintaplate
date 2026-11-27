// What a step announces at 960 x 512 before it ever ran (logic.stepGuess), against what it took on a 16 GB GPU with 52 to
// 61 GB of RAM, ComfyUI 0.45.3, read from the page's log; and the model families that decide when a step pays its models'
// load. Every row holds within 25% of its measure, except those OUTSIDE names, each with why.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { FAMILY, loadSeconds, STEP_FLOWS, stepFamily, stepGuess } from "../../web/logic.mjs";

const app = readFileSync(new URL("../../web/app.mjs", import.meta.url), "utf8");
const REF = Object.fromEntries([...app.matchAll(/\{ id: "(\w+)", label: "[^"]*", ref: (\d+)/g)].map((m) => [m[1], Number(m[2])]));
const B33 = { work: [960, 512], track: [960, 512], shot: [480, 256], frames: 33 }; // a blank plate of 960 x 512, the preview at half size
const B17 = { ...B33, shot: [960, 512], frames: 17 }; // the same plate with 17 frames, the preview off
const B1001 = { ...B33, frames: 1001 };
const HORSE = { work: [1920, 1088], track: [960, 544], shot: [960, 544], frames: 121 }; // horse.mp4, 1920 x 1080

const ROWS = [ // [step, seconds, plate, profile, the family of the job before it, what it is]
  ["hdrplate", 22.2, B17, "small", "frames", "« Plate, HDR », the render's first SDR to HDR job, after Export"],
  ["shot", 27.4, B33, "small", "klein", "« Shot, preview », which loads LTX after the edit"],
  ["full", 34.1, B17, "small", "klein", "« Shot, full size », which loads LTX after the edit"],
  ["fluidfull", 32.4, B17, "small", "frames", "« Fluid shot, full size », which loads LTX after the plate opens"],
  ["comp", 2.7, B33, "small", "sam", "« Composite, preview »"],
  ["fluidfull", 268, B1001, "large", "frames", "« Fluid shot, full size » on a 96 GB GPU with 175 GB of RAM, 1,001 frames"],
];
const OUTSIDE = { "fluidfull large": "one measure: it suggests that on a 96 GB GPU the fluid shot grows faster than its pixels, as « Shot, full size » does (SLOWER.large.grow.full); no factor is taken from one point" };

test("each step loads one family of models, read from its workflows", () => {
  for (const [id, flows] of Object.entries(STEP_FLOWS)) {
    const models = [...new Set(flows.map((n) => FAMILY[n]).filter((f) => f !== "frames"))];
    assert.ok(models.length <= 1, `${id} loads ${models.join(" and ")}`);
    assert.equal(stepFamily(id), models[0] ?? "frames", id);
  }
  assert.deepEqual(["hdrplate", "hdrlayer", "hdrshot", "hdr", "upplate", "upcomp", "review"].map(stepFamily), ["ltx", "ltx", "ltx", "ltx", "seedvr2", "seedvr2", "frames"]);
});

test("SDR to HDR's steps pay LTX's load when they start cold, as every other step does", () => {
  for (const id of ["hdrplate", "hdrlayer", "hdrshot", "hdr"]) {
    const cold = stepGuess(id, REF[id], B17, "small", false, "frames"), loaded = stepGuess(id, REF[id], B17, "small", false, "ltx");
    assert.ok(Math.abs(cold - loaded - loadSeconds("ltx", B17, "small")) < 1e-9, id);
  }
  assert.ok(Math.abs(loadSeconds("ltx", HORSE, "small") - 38) < 0.5, "the load at 1920 x 1080 and 121 frames is the one ComfyUI's trace measured");
});

test("each measure holds within 25% of what the step announces", () => {
  const off = ROWS.filter(([id, took, plate, profile, before]) => Math.abs(stepGuess(id, REF[id], plate, profile, false, before) - took) > 0.25 * took);
  assert.deepEqual(off.map(([id, , , profile]) => `${id} ${profile}`), Object.keys(OUTSIDE));
});
