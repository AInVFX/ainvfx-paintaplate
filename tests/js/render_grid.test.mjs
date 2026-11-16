// logic.gridGrow: the clean plate pass grows its erased grid by enough 32 px blocks to reach as far as the composite pastes
// an erase (its grow and feather, 100 px on a plate 1920 wide), plus one block for the object's outline, at each size.
import { test } from "node:test";
import assert from "node:assert/strict";
import { gridGrow } from "../../web/logic.mjs";

test("the erased grid reaches the composite's edge at every size", () => {
  assert.deepEqual([1920, 960, 640].map((w) => gridGrow(w, 1920, 100)), [5, 3, 3]);
  for (const w of [1920, 1280, 960, 640]) assert.ok((gridGrow(w, 1920, 100) - 1) * 32 >= (100 * w) / 1920, `${w}`);
  assert.equal(gridGrow(3840, 3840, 200), 8); // a 4K plate: the same reach in its own pixels
});
