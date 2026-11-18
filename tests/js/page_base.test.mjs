// Tests of the status line's note while an edit with active edits above it changes
// (logic.hidesNote): the first frame shows the edits below it only, and the note names the edits it hides.
import assert from "node:assert/strict";
import { test } from "node:test";
import { hidesNote } from "../../web/logic.mjs";

test("hidesNote names no edit, one edit or several edits above", () => {
  assert.equal(hidesNote(1, []), "");
  assert.equal(hidesNote(1, [2]), "Edit 1 changes: Edit 2 hides until Generate. Esc cancels the change.");
  assert.equal(hidesNote(2, [3, 4, 5]), "Edit 2 changes: Edits 3, 4 and 5 hide until Generate. Esc cancels the change.");
});
