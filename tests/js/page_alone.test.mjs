// The page workstream's check of the render key (logic.renderKey): a plate with no edit has a render only when the Finish
// menu asks SDR to HDR of a plate whose format holds nothing above 1.0, and then its key is PLATE_ALONE (logic.plateAlone).
import assert from "node:assert/strict";
import { test } from "node:test";
import { hdrKey, hdrOfKey, PLATE_ALONE, plateAlone, renderKey } from "../../web/logic.mjs";

test("a plate with no edit renders only for SDR to HDR asked of a plate that holds nothing above 1.0", () => {
  assert.equal(renderKey("", false, true), PLATE_ALONE);
  assert.equal(renderKey("", false, false), "");
  assert.equal(renderKey("", true, true), ""); // a plate that holds values above 1.0: with no new content, nothing to convert
  assert.ok(plateAlone(renderKey("", false, true)));
  assert.equal(hdrOfKey(PLATE_ALONE, false), true); // the render's plan reads the switch from the key
});

test("with edits, the key is the edits' key, and it never reads as the plate alone", () => {
  for (const [dflt, on] of [[false, false], [false, true], [true, true], [true, false]]) {
    assert.equal(renderKey("1.1,2.1", dflt, on), hdrKey("1.1,2.1", dflt, on));
    assert.ok(!plateAlone(renderKey("1.1,2.1", dflt, on)));
  }
});
