// The page workstream's check of the native frames' failure (logic.nativeCause): one log line per cause, so a message
// that names its file counts once for every file of a sequence.
import assert from "node:assert/strict";
import { test } from "node:test";
import { nativeCause } from "../../web/logic.mjs";

test("nativeCause takes the file's path out of the message", () => {
  const one = nativeCause("cannot read /plates/a.0001.exr: bad header", "/plates/a.0001.exr");
  assert.equal(one, "cannot read the file: bad header");
  assert.equal(nativeCause("cannot read /plates/a.0002.exr: bad header", "/plates/a.0002.exr"), one);
  assert.equal(nativeCause("out of memory", "/plates/a.0003.exr"), "out of memory");
});
