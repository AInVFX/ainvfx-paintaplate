import { test } from "node:test";
import assert from "node:assert/strict";
import { addSampled, inspectorRows, pointsQuery } from "../../web/inspector.mjs";

test("the points sampled with Shift held: each pixel once, in the order sampled", () => {
  let pts = addSampled([], { x: 4, y: 5 });
  pts = addSampled(pts, { x: 6, y: 5 });
  assert.equal(addSampled(pts, { x: 4, y: 5 }), pts); // a pixel sampled again adds nothing
  assert.deepEqual(pts, [{ x: 4, y: 5 }, { x: 6, y: 5 }]);
  assert.equal(pointsQuery(pts), "4,5;6,5"); // as the pixel route reads them
});

test("the average row shows the route's mean of the points, from two points on", () => {
  const rows = (average) => inspectorRows({ x: 4, y: 5, frame: 1001, value: [0.5, 0.5, 0.5], average });
  assert.ok(!rows({ value: [0.5, 0.5, 0.5], n: 1 }).some((r) => r[0].startsWith("Average")));
  const got = rows({ value: [0.25, 0.5, 1.5], n: 2 });
  const at = got.findIndex((r) => r[0] === "Average source colour of 2");
  assert.deepEqual(got.slice(at + 1, at + 4), [["Red", "0.250000"], ["Green", "0.500000"], ["Blue", "1.500000"]]);
});
