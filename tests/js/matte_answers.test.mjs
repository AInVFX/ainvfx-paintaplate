// What a change of matte strategy costs: logic.keepsAnswers and logic.freeAsk keep ComfyUI's cache between the matte and
// the frames steps, so SAM 3.1's answers survive the composite; logic.donorFor gives a render the shot of the same edits
// under another matte strategy, so the shot is never made again.
import test from "node:test";
import assert from "node:assert/strict";
import { donorFor, freeAsk, freeNeedsRoom, keepsAnswers, MEMORY } from "../../web/logic.mjs";

const GB = 2 ** 30, small = MEMORY.small, large = MEMORY.large;

test("between the matte and the frames steps a free keeps the cache, both ways", () => {
  for (const [a, b] of [["matte", "review"], ["matte", "comp"], ["review", "matte"], ["comp", "matte"], ["matte", "export"], ["export", "matte"]])
    assert.equal(keepsAnswers(a, b), true, `${a} then ${b}`);
  for (const [a, b] of [["shot", "matte"], ["matte", "shot"], ["edit", "shot"], ["review", "edit"], ["review", "hdr"], ["matte", "upscale"], ["clean", "matte"]])
    assert.equal(keepsAnswers(a, b), false, `${a} then ${b}`);
});

test("a small GPU frees between families: the matte and the frames keep the cache unless RAM is short; a larger GPU frees when RAM is short", () => {
  assert.deepEqual(freeAsk(small, "matte", "review", { free: 30 * GB, need: 14 * GB }), { why: "the matte's models unloaded.\n  This GPU holds one model family at a time.", keep: true });
  assert.equal(freeAsk(small, "matte", "review", { free: 4 * GB, need: 14 * GB }).keep, false);
  assert.equal(freeAsk(small, "review", "matte", null).keep, true);
  assert.equal(freeAsk(small, "shot", "matte", null), "the shot's models unloaded.\n  This GPU holds one model family at a time.");
  assert.equal(freeAsk(small, "matte", "matte", null), null);
  assert.equal(freeAsk(large, "matte", "review", { free: 4 * GB, need: 14 * GB }), "4 GB of RAM free, 14 GB needed for its frames.");
  assert.equal(freeAsk(large, "matte", "review", { free: 30 * GB, need: 14 * GB }), null);
  assert.equal(freeAsk(large, "matte", "review", { free: 4 * GB, need: 14 * GB }, false), null);
  assert.equal(freeNeedsRoom(small, "matte", "review"), true);
  assert.equal(freeNeedsRoom(small, "shot", "matte"), false);
  assert.equal(freeNeedsRoom(large, "shot", "matte"), true);
});

test("the same edits under another matte strategy give their shot; another Finish or other edits do not", () => {
  const e = (id, version = 1) => ({ id, version, tool: "paint" }), v1 = { key: "1.1", active: [e(1)], wanted: 1 };
  assert.equal(donorFor([e(1)], [v1], "1.1~3"), "1.1");
  assert.equal(donorFor([e(1)], [{ key: "1.1~1", active: [e(1)], wanted: 1 }], "1.1~3"), "1.1~1");
  assert.equal(donorFor([e(1)], [v1], "1.1~3|hdr"), null);
  assert.equal(donorFor([e(1)], [v1], ""), null);
  assert.equal(donorFor([e(1)], [v1], "1.1"), null);
  assert.equal(donorFor([e(1, 2)], [v1], "1.2~3"), null);
});
