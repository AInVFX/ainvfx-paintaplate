// The line under the timeline follows the status line's classes (logic.timelineClass, stepClasses): gold, then grey once the
// preview is made, then green once the full size is made, or once Finish is made where it is the render's only class.
import { test } from "node:test";
import assert from "node:assert/strict";
import { timelineClass } from "../../web/logic.mjs";

const steps = (...rows) => rows.map(([cls, done]) => ({ cls, done }));

test("a fluid shot alone turns green once its full size is made", () => {
  assert.equal(timelineClass(steps(["preview", true], ["full", false])), "final");
  assert.equal(timelineClass(steps(["preview", true], ["full", true])), "ready");
});

test("a render of edits: gold, grey, then green while Finish still runs", () => {
  assert.equal(timelineClass(steps(["preview", false], ["full", false], ["finish", false])), "");
  assert.equal(timelineClass(steps(["preview", true], ["full", false], ["finish", false])), "final");
  assert.equal(timelineClass(steps(["preview", true], ["full", true], ["finish", false], ["export", false])), "ready");
});

test("a plate alone with Finish: green once Finish is made", () => {
  assert.equal(timelineClass(steps(["finish", false])), "");
  assert.equal(timelineClass(steps(["finish", true])), "ready");
});
