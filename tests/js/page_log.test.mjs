// Tests of the log's export (logic.logReport, logic.logFileName): the versions, the machine that
// ComfyUI reports, the page and the plate, then the log with its times; no command line and no path of this machine.
import assert from "node:assert/strict";
import { test } from "node:test";
import { logFileName, logReport } from "../../web/logic.mjs";

test("logFileName: the plate's name and the local date and time", () => {
  assert.equal(logFileName("desk", new Date(2026, 10, 14, 17, 5)), "paintaplate_log_desk_20261114_1705.txt");
  assert.equal(logFileName("", new Date(2026, 0, 2, 3, 4)), "paintaplate_log_no_plate_20260102_0304.txt");
  assert.equal(logFileName("my plate (v2)", new Date(2026, 0, 2, 3, 4)), "paintaplate_log_my_plate_v2_20260102_0304.txt");
});

test("logReport: versions, machine, page, plate, then the log with its times", () => {
  const text = logReport({ version: "1.11.17", build: "5dfb6417", browser: "Mozilla/5.0 Test", address: "blank=0", memory: "medium (16 GB of VRAM)",
    stats: { system: { os: "posix", ram_total: 64 * 2 ** 30, comfyui_version: "0.45.3", python_version: "3.12.3 (main) [GCC 13.2.0]", pytorch_version: "2.7.0+cu128", argv: ["main.py", "--listen", "/home/someone"] },
      devices: [{ name: "cuda:0 NVIDIA GeForce RTX 4090 Laptop GPU : cudaMallocAsync", vram_total: 16 * 2 ** 30 }] },
    plate: ["desk: h264, 1280 × 704", "Colour space: sRGB, from file"],
    lines: [["09:45:17", "Page ready in 25 ms."], ["09:45:18", "Plate desk: opened in 1.9 s.\n  1280 x 704, 49 frames."]], now: new Date(2026, 10, 14, 17, 5) });
  assert.match(text, /^AInVFX Paint a plate 1\.11\.17 \(build 5dfb6417\)\.\nExported: 2026-11-14 17:05, this machine's time\.\n/);
  for (const line of ["  ComfyUI: 0.45.3.", "  Python: 3.12.3.", "  PyTorch: 2.7.0+cu128.", "  Operating system: posix.", "  GPU 0: cuda:0 NVIDIA GeForce RTX 4090 Laptop GPU : cudaMallocAsync, 16.0 GB of VRAM.",
    "  RAM: 64.0 GB.", "  Browser: Mozilla/5.0 Test.", "  Address options: blank=0.", "  Memory profile: medium (16 GB of VRAM).", "  desk: h264, 1280 × 704", "09:45:17  Page ready in 25 ms.",
    "09:45:18  Plate desk: opened in 1.9 s.", "          1280 x 704, 49 frames."]) assert.ok(text.includes(line), line);
  assert.ok(!text.includes("--listen") && !text.includes("/home/someone"), "no command line");
});

test("logReport says what ComfyUI did not report", () => {
  const text = logReport({ version: "", build: "", stats: null, browser: "b", address: "", memory: "", plate: [], lines: [], now: new Date(2026, 0, 1) });
  for (const line of ["  ComfyUI: unknown.", "  GPU: none reported.", "  RAM: unknown.", "  Address options: none.", "  No plate open."]) assert.ok(text.includes(line), line);
});
