// The limit per machine: a plate opens with no more frames than this machine's RAM holds through every step, as measured
// on an RTX PRO 6000 pod and on a 16 GB GPU under a 52 GB cap; the Open dialog, the log and the Blank plate tab say why.
import { test } from "node:test";
import assert from "node:assert/strict";
import { blankChanges, blankSpec, countText, framesFit, keepReason, LENGTH, lengthWarning, plateKeep } from "../../web/logic.mjs";

const G = 2 ** 30, pod = { ram: 175 * G, profile: "large" }, laptop = { ram: 52 * G, profile: "small" };

test("the measured cases fit, and what the pod could not hold does not", () => {
  assert.ok(framesFit(1920, 1080, pod.ram, "large") >= 497, "the pod: 497 frames at 1920 x 1080 with SDR to HDR peaked at 165.3 GB");
  assert.ok(framesFit(3840, 2160, pod.ram, "large") >= 121, "the pod: 121 frames at 3840 x 2160 ran every tool");
  assert.ok(framesFit(1920, 1080, pod.ram, "large") < 1001, "1001 frames at 1920 x 1080 need about twice the pod's RAM");
  assert.equal(framesFit(1920, 1080, laptop.ram, "small"), 121, "a 16 GB GPU under a 52 GB cap: 121 frames at 1920 x 1080 ran every tool");
  assert.deepEqual([framesFit(1280, 720, laptop.ram), framesFit(3840, 2160, laptop.ram)], [273, 25]);
});

test("the count is 8k + 1, within the nodes' ceiling; with no RAM reported, no limit", () => {
  for (const [w, h] of [[640, 360], [1920, 1080], [2048, 858], [3840, 2160], [7680, 4320]]) {
    for (const m of [pod, laptop]) {
      const n = framesFit(w, h, m.ram, m.profile);
      assert.ok((n - 1) % 8 === 0 && n >= 1 && n <= LENGTH.most, `${w} x ${h}, ${m.profile}: ${n}`);
    }
  }
  assert.equal(framesFit(1920, 1080, 0), LENGTH.most, "ComfyUI gave no RAM: the page sets no limit it cannot measure");
  assert.equal(framesFit(64, 32, pod.ram, "large"), LENGTH.most, "a tiny plate: the nodes' ceiling");
  assert.equal(framesFit(7680, 4320, 13 * G, "small"), 1, "a machine that holds no frame of it still opens one");
});

test("what sets a plate's frames, LTX's 20 s or this machine, and the sentence that says which", () => {
  assert.deepEqual(plateKeep({ width: 1920, height: 1080, fps: 25 }, pod), { frames: 497, by: "time" });
  assert.deepEqual(plateKeep({ width: 1920, height: 1080, fps: 50 }, pod), { frames: 513, by: "ram" });
  assert.deepEqual(plateKeep({ width: 1920, height: 1080, fps: 24 }), { frames: 481, by: "time" }, "before ComfyUI reports its RAM: the 20 s alone");
  const keep = plateKeep({ width: 1920, height: 1080, fps: 50 }, laptop), plate = { fps: 50, width: 1920, height: 1080, ram: laptop.ram };
  assert.equal(keepReason(keep, plate), "this machine's 52 GB of RAM holds 121 frames at 1920 x 1080 through every step");
  assert.equal(lengthWarning({ name: "long", total: 1250, keep, ...plate }),
    "Warning: plate long: 121 of its 1,250 frames opened.\n  Frames 122 to 1250 are left out: this machine's 52 GB of RAM holds 121 frames at 1920 x 1080 through every step.");
  assert.equal(countText(1001), "1,001");
});

test("the Blank plate tab's frames stop where this machine stops, and its note says so", () => {
  const typed = { width: "1920", height: "1088", fps: "25", frames: "2000" };
  assert.equal(blankSpec(typed, laptop).frames, 113);
  assert.deepEqual(blankChanges(typed, blankSpec(typed, laptop), laptop), ["Frames set to 113, the most this machine holds at 1920 x 1088."]);
  assert.equal(blankSpec(typed, pod).frames, 497, "the pod at 25 fps: the 20 s come first");
  assert.deepEqual(blankChanges({ ...typed, fps: "50" }, blankSpec({ ...typed, fps: "50" }, pod), pod), ["Frames set to 513, the most this machine holds at 1920 x 1088."]);
});
