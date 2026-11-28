// Save scene's names (logic.sceneName, logic.freeName): what the scenes route accepts, and the free name the page offers.
import { test } from "node:test";
import assert from "node:assert/strict";
import { freeName, sceneName } from "../../web/logic.mjs";

test("a free name counts on from the name: horse, horse_2, horse_3", () => {
  assert.equal(freeName("horse", new Set(["horse"])), "horse_2");
  assert.equal(freeName("horse", new Set(["horse", "horse_2", "horse_3"])), "horse_4");
  assert.equal(freeName("horse_2", new Set(["horse", "horse_2"])), "horse_3");
  assert.equal(freeName("shot_v2_7", new Set(["shot_v2_7"])), "shot_v2_8");
});

test("a scene's name keeps letters, digits, '.', '-' and '_', and never starts with '.'", () => {
  assert.equal(sceneName("desk take"), "desk_take");
  assert.equal(sceneName("..hidden"), "hidden");
  assert.equal(sceneName("a/b\\c"), "a_b_c");
  assert.equal(sceneName("x".repeat(140)).length, 100);
});
