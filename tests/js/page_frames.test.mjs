// Tests of the native frames' failure (logic.nativeCause): one log line per cause, so a message
// that names its file counts once for every file of a sequence.
import assert from "node:assert/strict";
import { test } from "node:test";
import { nativeCause } from "../../web/logic.mjs";
import { CACHE_GROW, outgrows } from "../../web/frames.mjs";

test("nativeCause takes the file's path out of the message", () => {
  const one = nativeCause("cannot read /plates/a.0001.exr: bad header", "/plates/a.0001.exr");
  assert.equal(one, "cannot read the file: bad header");
  assert.equal(nativeCause("cannot read /plates/a.0002.exr: bad header", "/plates/a.0002.exr"), one);
  assert.equal(nativeCause("out of memory", "/plates/a.0003.exr"), "out of memory");
});

test("a resize keeps the frame cache unless the view needs clearly more pixels than it was planned for", () => {
  const planned = [1472, 828]; // the view the frames were planned for, in device pixels
  for (const fit of [[1408, 792], [1216, 684], [1024, 576], [1472, 828], [1792, 1008]]) assert.equal(outgrows(planned, fit), false, String(fit));
  assert.equal(outgrows(planned, [1900, 1069]), true); // 1.29 times wider than planned
  assert.equal(outgrows(planned, [1472, 1100]), true); // 1.33 times taller
  assert.equal(outgrows(null, [1024, 576]), true); // nothing planned yet
  assert.equal(CACHE_GROW, 1.25);
});
