// A paint's matte that SAM 3.1 follows on fewer than half of the shot's frames (logic.matteShort): the page warns in the status
// line, with the count, and says to choose « Whole shot » in Matte strategy.
import assert from "node:assert/strict";
import { test } from "node:test";
import { matteShort } from "../../web/logic.mjs";

test("a matte that follows its object on fewer than half of the frames warns, with the count", () => {
  assert.equal(matteShort("tracked on 22 of 121 frames. Object hidden from frame 26 to 121."), "the paint's matte follows the object on 22 of 121 frames");
  assert.equal(matteShort("tracked on 60 of 121 frames."), "the paint's matte follows the object on 60 of 121 frames");
});

test("a matte on half of the frames or more, or a note with no count, warns of nothing", () => {
  assert.equal(matteShort("tracked on 61 of 121 frames."), null);
  assert.equal(matteShort("tracked on 121 of 121 frames."), null);
  assert.equal(matteShort(""), null);
  assert.equal(matteShort(undefined), null);
});
