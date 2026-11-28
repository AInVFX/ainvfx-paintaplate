// The encode of the full-size clean plate pass (slot encode_tile) follows the rule of every LTX decode (slot tile): whole from WHOLE_FROM
// bytes of VRAM, in 256 px tiles under it, on every profile, chosen or asked for.
import { test } from "node:test";
import assert from "node:assert/strict";
import { MEMORY, WHOLE, WHOLE_FROM, memoryProfile } from "../../web/logic.mjs";

test("the full-size clean plate pass encodes whole from WHOLE_FROM and in 256 px tiles under it, as every LTX decode", () => {
  for (const vram of [12.9e9, WHOLE_FROM - 1, WHOLE_FROM, 17.2e9, 25.7e9, 96 * 2 ** 30]) {
    for (const force of [null, ...Object.keys(MEMORY)]) {
      const { slots } = memoryProfile({ vram, force });
      assert.equal(slots.encode_tile, vram >= WHOLE_FROM ? WHOLE : 256, `${vram} bytes, ${force ?? "chosen"}`);
      assert.equal(slots.encode_tile, slots.tile, `${vram} bytes, ${force ?? "chosen"}`);
    }
  }
});
