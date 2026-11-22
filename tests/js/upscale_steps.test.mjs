import { test } from "node:test";
import assert from "node:assert/strict";
import { doneIn, span } from "../../web/logic.mjs";

test("a time reads in seconds under 100 s, then in minutes, in the Render panel's rows and the render's log lines", () => {
  assert.equal(span(39.4), "39 s");
  assert.equal(span(99.4), "99 s");
  assert.equal(span(1380), "23 min");
  assert.equal(doneIn(57.46, 39), "done in 57.5 s (estimate 39 s)");
  assert.equal(doneIn(1374, 1380), "done in 22.9 min (estimate 23 min)");
});
