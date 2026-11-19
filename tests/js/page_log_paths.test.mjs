// The log's export holds no path of the person's machine (web/logic.mjs: plainPaths, logReport): a path under ComfyUI's
// folder is written from that folder, any other absolute path by its last two parts, a Windows path included.
import { test } from "node:test";
import assert from "node:assert/strict";
import { logReport, plainPaths } from "../../web/logic.mjs";

const SAVED = "Scene horse_2 saved: /data/ComfyUI/output/paintaplate/scenes/horse_2.paintaplate.json.";
const DONE = "Export: done, in ComfyUI's output folder: Save Plate: 1 file written to /data/ComfyUI/output/paintaplate/mwmmrpf4/v2/export.";
const ABSOLUTE = /(^|[\s"'«(=])(\/|[A-Za-z]:[\\/]|\\\\)\w/m;

test("a path under ComfyUI's folder is written from that folder, with or without a closing separator", () => {
  assert.equal(plainPaths(SAVED, "/data/ComfyUI"), "Scene horse_2 saved: output/paintaplate/scenes/horse_2.paintaplate.json.");
  assert.equal(plainPaths(DONE, "/data/ComfyUI/"), "Export: done, in ComfyUI's output folder: Save Plate: 1 file written to output/paintaplate/mwmmrpf4/v2/export.");
});

test("any other absolute path keeps its last two parts, and so does every path when ComfyUI's folder is unknown", () => {
  assert.equal(plainPaths("Plate opened: /home/ana/plates/shot_010.mov.", "/data/ComfyUI"), "Plate opened: plates/shot_010.mov.");
  assert.equal(plainPaths(SAVED, ""), "Scene horse_2 saved: scenes/horse_2.paintaplate.json.");
  assert.equal(plainPaths("written to /mnt/data/ComfyUI/output/k/v1/export.", "/data/ComfyUI"), "written to v1/export.", "ComfyUI's folder inside another path is another folder");
});

test("a Windows path counts: a drive with either separator and in any case, a share, and a folder with a space", () => {
  const folder = "C:\\Users\\Ana Lima\\ComfyUI";
  assert.equal(plainPaths("Scene horse saved: C:\\Users\\Ana Lima\\ComfyUI\\output\\paintaplate\\scenes\\horse.paintaplate.json.", folder),
    "Scene horse saved: output\\paintaplate\\scenes\\horse.paintaplate.json.");
  assert.equal(plainPaths("Save Plate: 1 file written to c:/users/ana lima/comfyui/output/paintaplate/k/v2/export.", folder),
    "Save Plate: 1 file written to output/paintaplate/k/v2/export.");
  assert.equal(plainPaths("Plate opened: D:\\plates\\shot_010\\frame.%04d.exr.", folder), "Plate opened: shot_010\\frame.%04d.exr.");
  assert.equal(plainPaths("Plate opened: \\\\nas\\plates\\shot_010.mov.", folder), "Plate opened: plates\\shot_010.mov.");
});

test("what is not an absolute path stays: a relative path, a size, a ratio, an address", () => {
  const line = "Plate input/plates/desk.mp4: 1920 x 1088, 1/2 of the size, http://127.0.0.1:8188/view?x=1, 2.5 GB/s.";
  assert.equal(plainPaths(line, "/data/ComfyUI"), line);
});

test("the exported log holds no absolute path, in its plate lines and its log lines, detail lines included", () => {
  const text = logReport({ version: "1.11.25", build: "abc", stats: null, browser: "Mozilla/5.0 (X11; Linux x86_64)", address: "", memory: "",
    now: new Date(2026, 10, 18, 16, 49), folder: "/data/ComfyUI", plate: ["horse.mp4: 1920 x 1080, 121 frames", "Plate opened: /home/ana/plates/horse.mp4."],
    lines: [["04:40:23 PM", SAVED], ["04:41:10 PM", `${DONE}\n  Save Plate: 1 file written to /data/ComfyUI/output/paintaplate/mwmmrpf4/v2/export.`]] });
  assert.ok(text.includes("04:40:23 PM  Scene horse_2 saved: output/paintaplate/scenes/horse_2.paintaplate.json.\n"));
  assert.ok(text.includes("\n               Save Plate: 1 file written to output/paintaplate/mwmmrpf4/v2/export.\n"));
  assert.ok(text.includes("  Plate opened: plates/horse.mp4.\n"));
  assert.doesNotMatch(text, ABSOLUTE);
});
