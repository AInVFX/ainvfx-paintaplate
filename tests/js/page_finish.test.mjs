// Tests of the Finish menu's options (logic.FINISH, logic.finishLabel): one row per option, in the
// order the render runs them, and a button that counts the options that are on.
import assert from "node:assert/strict";
import { test } from "node:test";
import { FINISH, finishLabel } from "../../web/logic.mjs";

test("each option has an id, a name and a line; SDR to HDR asks first", () => {
  assert.equal(new Set(FINISH.map((o) => o.id)).size, FINISH.length);
  for (const o of FINISH) assert.ok(o.id && o.name && o.line.endsWith("."), o.id);
  assert.ok(FINISH.find((o) => o.id === "hdr").ask.endsWith("."));
});

test("finishLabel counts the options that are on", () => {
  assert.equal(finishLabel(0), "Finish");
  assert.equal(finishLabel(2), "Finish · 2");
});
