// Upscale's chunks in one window (logic.upscaleChunk): every chunk full, none short at the window's end, two neighbours
// sharing three latent frames; one pass when the window holds in one chunk. The same cases as tests/upscale_plate.py's
// even_chunk, so the page and the measuring tool cut a window alike.
import { test } from "node:test";
import assert from "node:assert/strict";
import { upscaleChunk } from "../../web/logic.mjs";

test("a window that holds in one chunk is one pass", () => {
  assert.equal(upscaleChunk(21, 6), 21);
  assert.equal(upscaleChunk(49, 13), 49, "49 frames are 13 latent frames: one pass where a chunk holds 13");
});

test("a longer window takes chunks that core's split ends full", () => {
  assert.equal(upscaleChunk(49, 6), 17, "49 frames, at most 6 latent frames a chunk: five chunks of 5, two apart");
  assert.equal(upscaleChunk(121, 6), 17, "121 frames: chunks of 5 latent frames end full where chunks of 6 leave the last one short");
  assert.equal(upscaleChunk(49, 6, 1), 17, "one shared latent frame: chunks of 6 leave the last one 3 latent frames short, chunks of 5 end full");
});
