// The page's messages: the colour a log message takes from its words, and a failure in plain words
import { test } from "node:test";
import assert from "node:assert/strict";
import { logLevel, plainError } from "../../web/logic.mjs";

test("a log message is red when a line starts « Error: », amber when one starts « Warning: », and plain otherwise", () => {
  assert.equal(logLevel("Error: SDR to HDR failed: ComfyUI stopped answering."), "error");
  assert.equal(logLevel("Warning: fluid shots off, ainvfx-fluid missing. Put it in models/loras."), "warn");
  assert.equal(logLevel("Follow Matte: 121 frames.\n  Warning: matte above 3x the object from frame 25 to 90. Check the composite there."), "warn");
  assert.equal(logLevel("Render v2: 2 edits.\n  Error: the shot failed."), "error");
  assert.equal(logLevel("Errors fixed: 2."), "");
  assert.equal(logLevel("Plate desk.mp4: opened in 1.2 s."), "");
});

test("a failure in plain words: the reason, for the log, ends with no full stop; the action, for the status line, ends with one", () => {
  for (const m of ["KSampler: Allocation on device", "ComfyUI stopped answering", "Failed to fetch", "UNETLoader: Value not in list", "something odd"]) {
    const { why, todo } = plainError(m);
    assert.ok(why && !why.endsWith("."), `${m}: ${why}`);
    assert.ok(todo.endsWith("."), `${m}: ${todo}`);
  }
  assert.match(plainError("ComfyUI stopped answering").todo, /Start ComfyUI again, then press Generate\.$/);
});
