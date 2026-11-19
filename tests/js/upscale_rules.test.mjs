// Upscale to 4K's rules: the target and source sizes, the windows by the machine's memory, the estimate, the row.
import assert from "node:assert/strict";
import { test } from "node:test";
import { FAMILY, FINISH, freesBefore, upscaleAsk, upscaleFolder, upscaleKeeps, upscaleSeconds, upscaleSource, upscaleTarget, upscaleWindow, upscaleWindows } from "../../web/logic.mjs";

const UHD = [3840, 2160], HD = [1920, 1080];

test("the target is 3840 px on the long side with the plate's aspect, and a larger plate keeps its size", () => {
  assert.deepEqual(upscaleTarget(1920, 1080), UHD);
  assert.deepEqual(upscaleTarget(1080, 1920), [2160, 3840]);
  assert.deepEqual(upscaleTarget(2048, 858), [3840, 1608]);
  assert.deepEqual(upscaleTarget(1920, 1088), [3812, 2160]); // the short side at most 2160
  assert.deepEqual(upscaleTarget(4096, 2160), [4096, 2160]);
});

test("SeedVR2 restores from half the target: a plate that large comes down to it first", () => {
  assert.deepEqual(upscaleSource(1920, 1080, UHD), [0, 0]);
  assert.deepEqual(upscaleSource(1280, 720, UHD), [0, 0]);
  assert.deepEqual(upscaleSource(3840, 2160, UHD), HD);
  assert.deepEqual(upscaleSource(2560, 1440, UHD), HD);
});

test("windows follow the machine: 21 frames on a 16 GB GPU under a 52 GB cap, one job on a 96 GB GPU with 175 GB of RAM", () => {
  assert.equal(upscaleWindow(52.0, 15.6, UHD, HD, 121), 21);
  assert.equal(upscaleWindow(175.1, 95.0, UHD, HD, 121), 121);
  assert.equal(upscaleWindow(64.0, 95.0, UHD, HD, 121), 61);
  assert.equal(upscaleWindow(24.0, 8.0, UHD, HD, 121), 21); // at least one chunk
  assert.deepEqual(upscaleWindows(121, 21), [[0, 21], [21, 21], [42, 21], [63, 21], [84, 21], [105, 16]]);
  assert.deepEqual(upscaleWindows(121, 121), [[0, 121]]);
});

test("a job that composes the 4K result holds 10 copies of a frame: the windows of Paint and Clean are sized for it", () => {
  assert.equal(upscaleWindow(131.3, 95.0, UHD, HD, 121, 10), 121); // 131.3 GB of RAM and a 95 GB GPU, where the composing job peaks at 116.8 GB: still one job
  assert.equal(upscaleWindow(52.0, 15.6, UHD, HD, 121, 10), 21);
  assert.equal(upscaleWindow(115.0, 95.0, UHD, HD, 121), 121);
  assert.equal(upscaleWindow(115.0, 95.0, UHD, HD, 121, 10), 101); // one job by 8 copies, windows by 10
});

test("the estimate: about 23 min for one pass of 121 frames at 3840 x 2160 on a 16 GB GPU, about 46 min for Paint or Clean", () => {
  assert.equal(Math.round(upscaleSeconds(UHD, 121, { profile: "small" }) / 60), 23);
  assert.equal(Math.round(upscaleSeconds(UHD, 121, { passes: 2, parts: 3, profile: "small" }) / 60), 46);
  assert.equal(Math.round(upscaleSeconds(UHD, 121, { profile: "large" })), 416); // one job of 388 s and its export
});

test("Paint and Clean keep the plate's untouched pixels; a Light edit, or no edit, restores the result alone", () => {
  assert.equal(upscaleKeeps(["paint", "erase"]), true);
  assert.equal(upscaleKeeps(["paint", "light"]), false);
  assert.equal(upscaleKeeps([]), false);
});

test("on a 16 GB GPU, SeedVR2's model leaves the memory before the 4K export and the next edit's models", () => {
  const small = { frees: true }, large = { frees: false };
  assert.deepEqual([FAMILY.upscale, FAMILY.upscale_export], ["seedvr2", "frames"]);
  assert.equal(freesBefore(small, "export", "upscale"), true);
  assert.equal(freesBefore(small, "upscale", "upscale"), false);
  assert.equal(freesBefore(small, "upscale", "upscale_export"), true);
  assert.equal(freesBefore(large, "upscale", "upscale_export", { free: 150 * 2 ** 30, need: 20 * 2 ** 30 }), false);
});

test("the row: off by default in the Finish menu, its question in figures", () => {
  const row = FINISH.find((o) => o.id === "upscale");
  assert.equal(row.name, "Upscale to 4K");
  assert.equal(typeof row.ask, "function");
  assert.equal(upscaleAsk({ target: UHD, frames: 121, alone: 1360, edit: 2748 }),
    "Export then also writes a 4k folder at 3840 x 2160. On this GPU, 121 frames take about 23 min, or about 46 min with Paint or Clean, "
    + "whose plate and layer are restored too. Every pixel of an upscaled frame is new.");
});

test("a plate's 4K windows live in one folder per setting that changes their frames, the same on every export", () => {
  const parts = ["plates/desk.mp4", "sRGB", "ocio://studio-config-latest", [3840, 2112], 21, "png16", "b1"];
  const folder = upscaleFolder("desk_1a2b", parts);
  assert.match(folder, /^paintaplate\/desk_1a2b\/upscale\/[0-9a-f]{8}$/);
  assert.equal(upscaleFolder("desk_1a2b", [...parts]), folder);
  for (let i = 0; i < parts.length; i++) assert.notEqual(upscaleFolder("desk_1a2b", parts.map((x, j) => (j === i ? `${x}!` : x))), folder, `part ${i}`);
});
