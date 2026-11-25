// The matte strategy's rules in logic.mjs: which edits take the menu, the render key, the strategy the shared paint matte
// runs, its log line, and what « Auto » chose.
import test from "node:test";
import assert from "node:assert/strict";
import { autoChose, MATTE_STRATEGIES, MATTE_TIPS, matteChoices, matteKey, matteOf, sharedMatte, sharedMatteLine } from "../../web/logic.mjs";

test("a paint takes the menu, with a line for each strategy; a Clean and a Light edit take none", () => {
  assert.deepEqual(matteChoices("paint"), ["Auto", "Object", "Object and effects", "Whole shot"]);
  assert.deepEqual(matteChoices("erase"), []);
  assert.deepEqual(matteChoices("light"), []);
  for (const s of MATTE_STRATEGIES) assert.ok(MATTE_TIPS[s].endsWith("."), s);
});

test("an edit with no strategy, or one its kind does not take, has Auto, and Auto keeps the render key", () => {
  assert.equal(matteOf({ tool: "paint" }), "Auto");
  assert.equal(matteOf({ tool: "paint", matte: "Wider" }), "Auto");
  assert.equal(matteOf({ tool: "erase", matte: "Whole shot" }), "Auto");
  assert.equal(matteOf({ tool: "paint", matte: "Whole shot" }), "Whole shot");
  assert.equal(matteKey({ tool: "paint" }), "");
  assert.equal(matteKey({ tool: "paint", matte: "Object and effects" }), "~2");
});

test("paints that share the matte run the widest strategy, and the log names whose choice it is", () => {
  const e = (id, matte) => ({ id, tool: "paint", matte });
  const num = (x) => x.id;
  assert.equal(sharedMatte([]), "Auto");
  assert.equal(sharedMatte([e(1, "Object")]), "Object");
  assert.equal(sharedMatte([e(1, "Object"), e(2)]), "Auto");
  assert.equal(sharedMatte([e(1, "Object and effects"), e(2, "Object"), e(3)]), "Object and effects");
  assert.equal(sharedMatte([e(1, "Object and effects"), e(2, "Whole shot")]), "Whole shot");
  assert.equal(sharedMatteLine([e(1, "Object"), e(2, "Object")], num), "");
  assert.equal(sharedMatteLine([e(1), e(2, "Object and effects")], num), "Edits 1 and 2 share the paint matte: it runs Object and effects, edit 2's choice.");
  assert.equal(sharedMatteLine([e(1, "Object"), e(2, "Whole shot"), e(3)], num), "Edits 1, 2 and 3 share the paint matte: it runs Whole shot, edit 2's choice.");
});

test("what Auto chose, read from the strategy line of Follow Matte's summary", () => {
  assert.equal(autoChose("tracked on 121 of 121 frames.\n  Strategy: Auto chose Object and effects: the edit spreads past the object (23% of the frame)."), "Object and effects");
  assert.equal(autoChose("tracked on 9 of 10 frames.\n  Strategy: Auto chose Object: Object and effects would change 8% of the frame around the object."), "Object");
  assert.equal(autoChose("tracked on 9 of 10 frames.\n  Strategy: Object."), null);
  assert.equal(autoChose(undefined), null);
});
