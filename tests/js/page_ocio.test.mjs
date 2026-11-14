// The page workstream's rules for the OCIO menu (web/logic.mjs): the plate's line, and the one question before an OCIO
// change that regenerates (the plate's colour space or the OCIO config), and the families of the plate's tree.
import { test } from "node:test";
import assert from "node:assert/strict";
import { plateFamily, plateSpaceLine, remakeQuestion } from "../../web/logic.mjs";

test("the plate's line shows its colour space, and whether it is the file's own or an override", () => {
  assert.equal(plateSpaceLine({ cs: "sRGB Encoded Rec.709 (sRGB)" }), "Colour space: sRGB Encoded Rec.709 (sRGB), from file");
  assert.equal(plateSpaceLine({ cs: "ACEScg", pageSpaceChosen: true }), "Colour space: ACEScg, override");
  assert.equal(plateSpaceLine(null), "Colour space: no plate");
});

test("one question for every OCIO change that regenerates: the cause, the edits it regenerates, then Continue", () => {
  assert.equal(remakeQuestion("plate's colour space", 1), "Changing the plate's colour space affects generation: 1 edit will be regenerated. Continue?");
  assert.equal(remakeQuestion("plate's colour space", 3), "Changing the plate's colour space affects generation: 3 edits will be regenerated. Continue?");
  assert.equal(remakeQuestion("OCIO config", 1), "Changing the OCIO config affects generation: 1 edit will be regenerated. Continue?");
});

test("the plate's tree shows the config's family Display as Display-referred, and every other family by its own name", () => {
  assert.equal(plateFamily("Display"), "Display-referred");
  for (const name of ["ACES", "Utility", "Input", "ARRI", "Displays", "display"]) assert.equal(plateFamily(name), name);
});
