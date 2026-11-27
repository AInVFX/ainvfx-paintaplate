// Upscale's chunks in one window (logic.upscaleChunk): every chunk full, none short at the window's end, two neighbours
// sharing three latent frames; one pass when the window holds in one chunk. The same cases as tests/upscale_plate.py's
// even_chunk, so the page and the measuring tool cut a window alike.
import { test } from "node:test";
import assert from "node:assert/strict";
import { upscaleChunk, upscaleChunks, upscalePass } from "../../web/logic.mjs";

test("a window that holds in one chunk is one pass", () => {
  assert.equal(upscaleChunk(21, 6), 21);
  assert.equal(upscaleChunk(49, 13), 49, "49 frames are 13 latent frames: one pass where a chunk holds 13");
});

test("a longer window takes chunks that core's split ends full", () => {
  assert.equal(upscaleChunk(49, 6), 17, "49 frames, at most 6 latent frames a chunk: five chunks of 5, two apart");
  assert.equal(upscaleChunk(121, 6), 17, "121 frames: chunks of 5 latent frames end full where chunks of 6 leave the last one short");
  assert.equal(upscaleChunk(49, 6, 1), 17, "one shared latent frame: chunks of 6 leave the last one 3 latent frames short, chunks of 5 end full");
});

test("one pass holds the smaller of the 32-bit bound and the VRAM, as measured on a 96 GB GPU", () => {
  assert.equal(upscalePass([3840, 2160], 95.6), 21, "3840 x 2160: 81 frames held, 85 did not");
  assert.equal(upscalePass([3840, 2048], 95.6), 22);
  assert.equal(upscalePass([2560, 1440], 95.6), 48, "the 32-bit bound, the VRAM holding more");
  assert.equal(upscalePass([1600, 880], 32), 37, "on 32 GB the VRAM bounds a pass first");
  assert.equal(upscalePass([3840, 2160], 15.6), 7, "under 32 GB the model streams: on 16 GB, 25 frames held at 3840 x 2160 and 29 did not");
  assert.equal(upscalePass([1920, 1080], 15.6), 31, "on 16 GB, a shot's 121 frames held at 1920 x 1080");
});

test("a window longer than one pass runs in even chunks, counted as core makes them", () => {
  assert.equal(upscaleChunk(121, upscalePass([3840, 2160], 95.6)), 65, "121 frames at 3840 x 2160 on 96 GB: chunks of 65 frames");
  assert.equal(upscaleChunks(121, 65), 2, "two chunks, one blended boundary");
  assert.equal(upscaleChunks(49, 49), 1, "one pass");
  assert.equal(upscaleChunks(49, 17), 5);
});
