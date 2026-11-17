// A cache keeps its frame size when a plan made again gives it a size within CACHE_NEAR of its own (frames.nearSize).
import { test } from "node:test";
import assert from "node:assert/strict";
import { CACHE_NEAR, nearSize } from "../../web/frames.mjs";

test("a size a few pixels away is near: the cache keeps its own", () => {
  assert.equal(CACHE_NEAR, 0.1);
  assert.ok(nearSize([1920, 1080], [1917, 1078]));
  assert.ok(nearSize([960, 540], [970, 545]));
});

test("a size more than 10% away on either side is not: the cache plans its frames again", () => {
  assert.ok(!nearSize([1344, 756], [969, 545]));
  assert.ok(!nearSize([960, 540], [1916, 1078]));
  assert.ok(!nearSize([1000, 500], [1000, 560]));
});
