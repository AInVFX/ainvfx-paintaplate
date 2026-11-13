// The page workstream's rules for the OCIO menu (web/logic.mjs): the plate's line, and the one question before an OCIO
// change that regenerates (the plate's colour space or the config).
import { test } from "node:test";
import assert from "node:assert/strict";
import { plateSpaceLine, remakeQuestion } from "../../web/logic.mjs";

test("the plate's line shows its colour space, and whether it is the file's own or an override", () => {
  assert.equal(plateSpaceLine({ cs: "sRGB Encoded Rec.709 (sRGB)" }), "Colour space: sRGB Encoded Rec.709 (sRGB), from file");
  assert.equal(plateSpaceLine({ cs: "ACEScg", pageSpaceChosen: true }), "Colour space: ACEScg, override");
  assert.equal(plateSpaceLine(null), "Colour space: no plate");
});

test("one question for every OCIO change that regenerates: what changes, and the edits it counts", () => {
  assert.equal(remakeQuestion("colour space", 1), "Changing the colour space regenerates the first frame and 1 edit.");
  assert.equal(remakeQuestion("colour space", 3), "Changing the colour space regenerates the first frame and 3 edits.");
});
