// logic.keepsAnswers: which frees keep ComfyUI's cache, so that SAM 3.1's answers survive the composite and a change of
// matte strategy runs Follow Matte alone.
import test from "node:test";
import assert from "node:assert/strict";
import { keepsAnswers } from "../../web/logic.mjs";

test("between the matte and the frames steps a free keeps the cache, both ways", () => {
  for (const [a, b] of [["matte", "review"], ["matte", "comp"], ["review", "matte"], ["comp", "matte"], ["matte", "export"], ["export", "matte"]])
    assert.equal(keepsAnswers(a, b), true, `${a} then ${b}`);
});

test("any other free clears the cache, as before", () => {
  for (const [a, b] of [["shot", "matte"], ["matte", "shot"], ["edit", "shot"], ["review", "edit"], ["review", "hdr"], ["matte", "upscale"], ["clean", "matte"]])
    assert.equal(keepsAnswers(a, b), false, `${a} then ${b}`);
});
