// The memory profile's decode and guide: from 16 GB of VRAM every LTX decode takes the whole frame in one piece and every
// IC-LoRA guide is encoded whole; under it, 256 px tiles and a tiled guide. The full-size passes' encode follows the decode.
import { test } from "node:test";
import assert from "node:assert/strict";
import { memoryProfile, MEMORY_FROM, WHOLE, WHOLE_FROM } from "../../web/logic.mjs";

const gib = 2 ** 30;

test("from 16 GB of VRAM every LTX decode is whole, and under it, or with no VRAM size, it is in 256 px tiles", () => {
  assert.equal(WHOLE, 4096);
  assert.ok(12.9e9 < WHOLE_FROM && WHOLE_FROM < 16 * gib && WHOLE_FROM < MEMORY_FROM.medium);
  for (const vram of [16 * gib, 25.7e9, 96 * gib]) assert.equal(memoryProfile({ vram }).slots.tile, WHOLE, `${vram}`);
  for (const vram of [0, 12.9e9, WHOLE_FROM - 1]) assert.equal(memoryProfile({ vram }).slots.tile, 256, `${vram}`);
});

test("the small profile's line names the tiles only where LTX decodes in tiles", () => {
  assert.equal(memoryProfile({ vram: 16 * gib }).does, "Models load one at a time, so each step takes longer than on a larger GPU");
  assert.equal(memoryProfile({ vram: 12.9e9 }).does,
    "Models load one at a time and LTX works in 256 px tiles, so each step takes longer than on a larger GPU");
});

test("the guide is whole from 16 GB and tiled under it, the encode keeps each profile's tiles, and an asked-for profile follows the VRAM", () => {
  assert.deepEqual(memoryProfile({ vram: 16 * gib }).slots, { tile: WHOLE, encode_tile: WHOLE, guide_tiled: false });
  assert.deepEqual(memoryProfile({ vram: 12.9e9 }).slots, { tile: 256, encode_tile: 256, guide_tiled: true });
  assert.deepEqual(memoryProfile({ vram: 96 * gib }).slots, { tile: WHOLE, encode_tile: WHOLE, guide_tiled: false });
  assert.deepEqual(memoryProfile({ vram: 96 * gib, force: "small" }).slots, { tile: WHOLE, encode_tile: WHOLE, guide_tiled: false });
  const large = memoryProfile({ vram: 12.9e9, force: "large" });
  assert.deepEqual(large.slots, { tile: 256, encode_tile: 256, guide_tiled: true });
  assert.equal(large.does, "Every model loads now and stays loaded");
});
