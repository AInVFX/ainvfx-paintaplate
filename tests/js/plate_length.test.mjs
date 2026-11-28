// A plate opens with up to LTX 2.5's 20 s at its frame rate, and says which frames it leaves out and why; the Blank plate
// tab shows the values its plate uses, and says why.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { blankChanges, blankLimits, blankSpec, FLUID, LENGTH, lengthWarning, plateLength } from "../../web/logic.mjs";

test("a plate opens with the longest 8k + 1 count within LTX 2.5's 20 s, at any frame rate", () => {
  const frames = (fps) => plateLength(fps).frames;
  assert.deepEqual([24, 25, 30, 48, 50, 60].map(frames), [481, 497, 601, 961, 1001, 1201]);
  assert.deepEqual([frames(23.976), frames(5), frames(1), frames(undefined)], [473, 97, 17, 481], "a plate that names no rate plays at 24 fps");
  for (const fps of [1, 5, 23.976, 24, 25, 29.97, 30, 48, 50, 59.94, 60, 120]) {
    const n = frames(fps);
    assert.equal((n - 1) % 8, 0, `${fps} fps: 8k + 1, so LTX's padding adds no frame`);
    assert.ok((n - 1) / fps <= LENGTH.seconds + 1e-9 && (n + 7) / fps > LENGTH.seconds, `${fps} fps: the longest count within 20 s`);
  }
  assert.ok(frames(30) > frames(25) && frames(50) > frames(30), "a higher frame rate opens more frames, never fewer");
  assert.deepEqual(plateLength(240), { frames: LENGTH.most, byTime: false }, "past 4,089 frames, the nodes' bound sets the count");
});

test("a plate with frames left out says which and why; a plate within 20 s opens with no warning", () => {
  const time = (fps) => ({ frames: plateLength(fps).frames, by: "time" });
  assert.equal(lengthWarning({ name: "long", total: 1250, keep: time(50), fps: 50 }),
    "Warning: plate long: 1,001 of its 1,250 frames opened.\n  Frames 1002 to 1250 are left out: LTX 2.5 makes shots of up to 20 s, 1,001 frames at 50 fps.");
  assert.equal(lengthWarning({ name: "shot", total: 600, keep: time(5), first: 1001, fps: 5 }),
    "Warning: plate shot: 97 of its 600 frames opened.\n  Frames 1098 to 1600 are left out: LTX 2.5 makes shots of up to 20 s, 97 frames at 5 fps.", "the plate's own frame numbers");
  assert.match(lengthWarning({ name: "fast", total: 5000, keep: { frames: 4089, by: "most" }, fps: 240 }), /Frames 4090 to 5000 are left out: Paint a plate's steps take up to 4,089 frames\.$/);
  assert.equal(lengthWarning({ name: "whole", total: 600, keep: time(30), fps: 30 }), null);
});

test("the Blank plate tab names each value its plate does not take as typed; its frames go up to 20 s at the rate chosen", () => {
  const changes = (typed) => blankChanges(typed, blankSpec(typed));
  assert.deepEqual(changes({ width: "5000", height: "100", fps: "25", frames: "2000" }),
    ["Width set to 1920 px, the largest.", "Height set to 256 px, the smallest.", "Frames set to 497, the most at 25 fps (20 s)."]);
  assert.equal(blankSpec({ width: "960", height: "512", fps: "50", frames: "2000" }).frames, 1001);
  assert.deepEqual(changes({ width: "1000", height: "512", fps: "24", frames: "100" }),
    ["Width set to 1024 px, the nearest multiple of 64.", "Frames set to 97, the nearest count LTX takes."]);
  assert.deepEqual(changes({ width: "", height: "512", fps: "50", frames: "4" }), ["Width set to 256 px.", "Frames set to 9, the fewest."]);
  assert.deepEqual(changes({ width: "960", height: "512", fps: "25", frames: "121" }), []);
});

test("the Blank plate tab's fields and note give the limits that FLUID and LENGTH hold", () => {
  const html = readFileSync(new URL("../../web/paintaplate.html", import.meta.url), "utf8");
  const field = (id) => Object.fromEntries([...html.match(new RegExp(`<input id="${id}"[^>]*>`))[0].matchAll(/(min|max|step)="(\d+)"/g)].map(([, k, v]) => [k, +v]));
  assert.deepEqual(field("b-width"), { min: FLUID.minSide, max: FLUID.maxSide, step: FLUID.step });
  assert.deepEqual(field("b-height"), { min: FLUID.minSide, max: FLUID.maxSide, step: FLUID.step });
  assert.deepEqual(field("b-frames"), { min: FLUID.minFrames, step: 8 }, "the page sets the most frames for the rate chosen");
  const rates = [...html.match(/<select id="b-fps">([\s\S]*?)<\/select>/)[1].matchAll(/<option[^>]*>(\d+)<\/option>/g)].map((m) => +m[1]);
  assert.deepEqual(rates, FLUID.rates);
  const hint = html.match(/data-tab="blank"[^>]*>\s*<p class="hint">([^<]*)<\/p>\s*<p class="hint" id="b-limits"><\/p>/)[1];
  assert.ok(!/\d/.test(hint), `the hint holds no limit of its own: the page writes them from FLUID: ${hint}`);
  assert.equal(blankLimits({ width: 960, height: 512, fps: 25 }), "Width and height: 256 to 1920 px, in steps of 64. Frames: 9 to 497 at 25 fps, in steps of 8.");
  assert.equal(blankLimits({ width: 1920, height: 1088, fps: 50 }, { ram: 52 * 2 ** 30, profile: "small" }), "Width and height: 256 to 1920 px, in steps of 64. Frames: 9 to 113 at 50 fps, in steps of 8.");
});
