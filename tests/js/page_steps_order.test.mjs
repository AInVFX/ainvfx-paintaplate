// The Render panel lists the steps in the order things happen (logic.stepOrder): the steps done, in the order they
// finished, then the step running, then the steps to come in their planned order.
import assert from "node:assert/strict";
import { test } from "node:test";
import { stepOrder } from "../../web/logic.mjs";

const plan = ["erase", "clean", "shot", "comp", "cleanfull", "full", "review"];
const order = (at, now) => stepOrder(plan, { done: (id) => id in at, at: (id) => at[id], now });

test("a full-size step reused at the render's start shows first, above the steps still to come", () => {
  assert.deepEqual(order({ erase: 1, cleanfull: 2 }, "clean"), ["erase", "cleanfull", "clean", "shot", "comp", "full", "review"]);
});

test("a render that runs in its planned order keeps it", () => {
  assert.deepEqual(order({ erase: 1, clean: 2 }, "shot"), plan);
  assert.deepEqual(order({}, null), plan);
});

test("steps done with no known order keep their planned places among the done ones", () => {
  assert.deepEqual(stepOrder(plan, { done: (id) => ["erase", "clean"].includes(id), now: "shot" }), plan);
});
