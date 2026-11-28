// logic.editSeed: with ?seed=n in the address, a session's first new edit starts from seed n and each next edit from the
// next number, within the seeds the page draws (0 to 2^31 - 1). Without ?seed= the page draws each seed.
import { test } from "node:test";
import assert from "node:assert/strict";
import { askedSeed, editSeed } from "../../web/logic.mjs";

test("each new edit starts from the next seed after the one asked for", () => {
  assert.deepEqual([0, 1, 2].map((made) => editSeed(askedSeed("7"), made)), [7, 8, 9]);
  assert.equal(editSeed(askedSeed(String(2 ** 31 - 1)), 1), 0);
  assert.equal(editSeed(askedSeed(null), 3), null);
});
