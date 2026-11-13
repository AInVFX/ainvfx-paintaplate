// The page workstream's rules for the OCIO menu (web/logic.mjs): the plate's line, and the question before a change of the
// plate's colour space that makes results again.
import { test } from "node:test";
import assert from "node:assert/strict";
import { plateSpaceLine, remakeQuestion } from "../../web/logic.mjs";

test("the plate's line shows its colour space and where the value comes from", () => {
  assert.equal(plateSpaceLine({ cs: "sRGB Encoded Rec.709 (sRGB)" }), "Plate colour space: sRGB Encoded Rec.709 (sRGB), read from the file");
  assert.equal(plateSpaceLine({ cs: "ACEScg", pageSpaceChosen: true }), "Plate colour space: ACEScg, chosen by you");
  assert.equal(plateSpaceLine(null), "Plate colour space: no plate");
});

test("the question counts the edits that are made again", () => {
  assert.equal(remakeQuestion(1), "This makes the first frame and 1 edit again.");
  assert.equal(remakeQuestion(3), "This makes the first frame and 3 edits again.");
});
