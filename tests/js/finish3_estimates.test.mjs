// Upscale's estimate against the passes a 16 GB GPU measured under a 52 GB cap of RAM (horse.mp4 at 1920 x 1080, one pass
// per job, tests/upscale_plate.py --chunk 0): logic.upscaleSeconds on the small profile, with no Save Plate part, holds
// each within 25%.
import test from "node:test";
import assert from "node:assert/strict";
import { hdrCompSeconds, stepSizeOf, upscaleSeconds } from "../../web/logic.mjs";

const PASSES = [ // [target, frames, seconds measured]
  [[3840, 2160], 21, 231.1], [[3840, 2160], 25, 274.1],
  [[1920, 1080], 49, 120.7], [[1920, 1080], 81, 196.4], [[1920, 1080], 121, 303.6],
];

test("Upscale's estimate on a 16 GB GPU holds each pass the laptop measured within 25%", () => {
  for (const [target, frames, measured] of PASSES) {
    const est = upscaleSeconds(target, frames, { parts: 0, profile: "small" });
    assert.ok(Math.abs(est / measured - 1) <= 0.25, `${target.join(" x ")}, ${frames} frames: ${est.toFixed(1)} s for ${measured} s`);
  }
});

test("« Composite, HDR » made again from SDR to HDR's elements, a job with no model, holds the measure within 25%", () => {
  const est = hdrCompSeconds(17, [960, 512]); // 17 frames at 960 x 512 took 1.4 s on a 16 GB GPU, where SDR to HDR's reference gave 43 s
  assert.ok(Math.abs(est / 1.4 - 1) <= 0.25, `${est.toFixed(2)} s for 1.4 s`);
  assert.deepEqual(stepSizeOf("hdrcomp", { work: [960, 512], spec: { width: 960, height: 512 }, shot: [960, 512] }), stepSizeOf("hdr", { work: [960, 512], spec: { width: 960, height: 512 }, shot: [960, 512] }));
});
