import { test } from "node:test";
import assert from "node:assert/strict";
import { deepStopped, logLevel, statusOf } from "../../web/logic.mjs";

test("the full-precision frames' failure is one red line: the source, the cause, then what the viewer shows", () => {
  const line = deepStopped("horse", "Failed to fetch");
  assert.equal(line, "Error: full-precision frames of horse: stopped (Failed to fetch). Viewer: 8-bit movie.");
  assert.equal(logLevel(line), "error", "the log shows it in red");
  assert.deepEqual(statusOf(line), { text: line, level: "error" }, "the status line shows it in red");
  assert.equal(deepStopped("the full-size composite", "  frame 12\n unreadable "),
    "Error: full-precision frames of the full-size composite: stopped (frame 12 unreadable). Viewer: 8-bit movie.", "a cause on several lines reads as one");
  assert.equal(deepStopped("horse", ""), "Error: full-precision frames of horse: stopped (no reason given). Viewer: 8-bit movie.");
});
