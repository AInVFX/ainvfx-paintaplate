// The line under the timeline follows the status line's classes (logic.timelineClass, stepClasses): gold, then grey once the
// preview is made, then green once the full size is made, or once Finish is made where it is the render's only class.
import { test } from "node:test";
import assert from "node:assert/strict";
import { renderStatus, timelineClass } from "../../web/logic.mjs";

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

// The Render panel's status line names a time left only while the render displayed runs (G9): each state the orchestrator
// named, with what the line and the line under the timeline show
const rows = (...r) => r.map(([cls, done, left = 60]) => ({ cls, done, left }));
const both = (steps, running) => [renderStatus(steps, { running }), timelineClass(steps, { running })];

test("a plate with no edit and a Finish switch on, before Enter: no time left; after Enter, the line counts", () => {
  const upscale = rows(["finish", false, 170]), hdr = rows(["finish", false, 90]), plateBoth = rows(["finish", false, 90], ["finish", false, 170]);
  for (const steps of [upscale, hdr, plateBoth]) assert.deepEqual(both(steps, false), ["", ""]);
  assert.match(renderStatus(upscale, { running: true }), /^finish about /);
});

test("the same plate once made, then another Upscale size: nothing made at that size, no time left", () => {
  assert.deepEqual(both(rows(["finish", false, 170]), false), ["", ""]);
  assert.deepEqual(both(rows(["finish", true]), false), ["finish ready", "ready"]);
});

test("a fluid shot with no edit on it, then a Finish switch: its full size is made", () => {
  assert.deepEqual(both(rows(["preview", true], ["full", true], ["finish", false]), false), ["full size ready", "ready"]);
});

test("a render stopped with steps still due: no time left; the line under the timeline turns grey only while it runs", () => {
  assert.deepEqual(both(rows(["preview", true], ["full", false]), false), ["", ""]);
  assert.match(renderStatus(rows(["preview", true], ["full", false]), { running: true }), /^full size about /);
  assert.equal(timelineClass(rows(["preview", true], ["full", false]), { running: true }), "final");
});

test("a render with edits after a Finish switch turned on: full size ready until its Finish steps run", () => {
  const steps = rows(["preview", true], ["full", true], ["finish", false, 120]);
  assert.deepEqual(both(steps, false), ["full size ready", "ready"]);
  assert.deepEqual(both(steps, true), ["finish about 2 min left", "ready"]);
});
