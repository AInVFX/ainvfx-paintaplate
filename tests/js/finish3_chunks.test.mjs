// Core's SeedVR2TemporalChunk takes 4n+1 frames per chunk and fails the job on any other count; SeedVR2Preprocess pads a
// window to 4n+1 frames. logic.upscaleChunk's chunk is 4n+1 for every window and every pass, and holds the window's latent
// frames, its last frame's included.
import test from "node:test";
import assert from "node:assert/strict";
import { upscaleChunk, upscaleChunks, upscalePass, upscaleWindow, upscaleWindows, UPSCALE } from "../../web/logic.mjs";

test("a chunk is 4n+1 frames for every window of 1 to 121 frames and every pass of 1 to 40 latent frames", () => {
  for (let count = 1; count <= 121; count++) for (let most = 1; most <= 40; most++) {
    const chunk = upscaleChunk(count, most);
    assert.equal((chunk - 1) % 4, 0, `${count} frames, ${most} latent frames: ${chunk}`);
    assert.ok((chunk - 1) / 4 + 1 <= most, `${count} frames, ${most} latent frames: ${chunk} is more than a pass holds`);
  }
});

test("one pass over a window that is not 4n+1 frames sends the window padded to 4n+1", () => {
  assert.equal(upscaleChunk(63, 17), 65); // 63 frames hold 17 latent frames, the last frame's included
  assert.equal(upscaleChunk(19, 6), 21);
  assert.equal(upscaleChunk(21, 6), 21);
  assert.equal(upscaleChunks(63, 65), 1);
});

test("2560 x 1408 on a 16 GB GPU with 52 GB of RAM: 121 frames in 2 windows of 63 and 62 frames, each in one pass of 65", () => {
  const target = [2560, 1408], most = upscalePass(target, 15.6), size = upscaleWindow(52, 15.6, target, [1280, 704], 121, UPSCALE.copies);
  const windows = upscaleWindows(121, size);
  assert.deepEqual(windows, [[0, 63], [59, 62]]);
  assert.equal(upscaleChunk(63, most), 65);
});
