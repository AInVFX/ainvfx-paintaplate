// The edit workstream's tests of the first frame's caption (web/logic.mjs: caption, upsampleRequest).
import { test } from "node:test";
import assert from "node:assert/strict";
import { caption, upsampleRequest } from "../../web/logic.mjs";

const bbox = [362, 794, 490, 1000];

test("an erase names its object once, whether its words start with an article or not", () => {
  // the GPU case horse_erase_barn types « the barn »: the request said « Remove the the barn » (12 Nov 2026)
  for (const words of ["the barn", "The barn", "a barn", "barn", "  the barn "]) {
    const text = caption({ tool: "erase", words, colors: [], color: "#000000", bbox });
    assert.match(text, /^Remove the barn inside <obj_1> completely/, words);
    assert.match(text, /"desc":"barn to remove"/, words);
    assert.match(upsampleRequest({ tool: "erase", words, bbox }).request, /Remove the barn <obj_1> completely/, words);
  }
  assert.match(upsampleRequest({ tool: "erase", words: "an old post", bbox, boxes: [[1, 2, 30, 40], [50, 60, 70, 80]] }).request,
    /Remove the old post <obj_1> and <obj_2> completely/);
  assert.match(caption({ tool: "erase", words: "", colors: [], color: "#000000", bbox }),
    /^Remove the object inside <obj_1>.*"desc":"object to remove"/);
});

test("a paint edit keeps its words as they were typed", () => {
  assert.match(caption({ tool: "paint", words: "a cactus", colors: ["#3d7a35"], color: "#3d7a35", bbox }), /with a cactus, following/);
});
