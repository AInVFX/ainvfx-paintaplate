import { test } from "node:test";
import assert from "node:assert/strict";
import { addSample, formatValue, inspectorRows, sourcePath, sourcePixel } from "../../web/inspector.mjs";

test("a point of the view gives the plate's own pixel, from the top left", () => {
  assert.deepEqual(sourcePixel(0, 0, 3840, 2160), { x: 0, y: 0, inside: true });
  assert.deepEqual(sourcePixel(0.99999, 0.5, 3840, 2160), { x: 3839, y: 1080, inside: true });
  assert.equal(sourcePixel(1.2, 0.5, 3840, 2160).inside, false);
});

test("the file on show: EXR frames, else the movie in the output folder, else the plate", () => {
  assert.equal(sourcePath({ frames: "output:paintaplate/r/review", url: "/api/view?x" }, "plates/a.mp4"), "output:paintaplate/r/review");
  assert.equal(sourcePath({ url: "/api/view?filename=s.mp4&subfolder=paintaplate%2Fr&type=output" }, "p"), "output:paintaplate/r/s.mp4");
  assert.equal(sourcePath(null, "plates/a.mp4"), "plates/a.mp4");
});

test("values as RV prints them, above 1.0 and below 0, and the running average", () => {
  assert.equal(formatValue(4), "4.000000");
  assert.equal(formatValue(-0.0999755859375), "-0.099976");
  const avg = addSample(addSample(null, [1, 2, 3]), [3, 2, 1]);
  const rows = inspectorRows({ x: 4, y: 5, frame: 1001, value: [4, 0.5, -0.1], final: [1, 0.5, 0], average: avg });
  assert.deepEqual(rows[0], ["Native Pixel", "4, 5"]);
  assert.deepEqual(rows.find((r) => r[0] === "Red"), ["Red", "4.000000"]);
  assert.ok(rows.some((r) => r[0] === "Average of 2"));
  assert.equal(rows.at(-3)[1], "2.000000");
});
