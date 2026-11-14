// The page's plain words for the plate's errors (plainError in web/logic.mjs), in the old and the new wording of each.
import assert from "node:assert/strict";
import { test } from "node:test";
import { plainError } from "../../web/logic.mjs";

test("an image sequence that is not there names the step that saved no frames", () => {
  for (const m of ["PaintAPlate_LoadPlate: No image frames found in /w/output/paintaplate/a1/v2/640x352/clean",
    "PaintAPlate_LoadPlate: Image sequence not found: /w/output/paintaplate/a1/v2/640x352/clean. Check the folder and the frame numbers."])
    assert.equal(plainError(m), "the clean plate pass saved no frames, so there was nothing to read.");
});

test("a plate of another kind of file says so", () => {
  for (const m of ["PaintAPlate_LoadPlate: Unsupported plate: /x/y.abc",
    "PaintAPlate_LoadPlate: Plate not supported: /x/y.abc. Use a movie, an image or an image sequence."])
    assert.equal(plainError(m), "Paint a plate cannot read this kind of file.");
});

test("an OCIO colour space, view or look that the config lacks is not read as a missing file", () => {
  for (const m of ["Colour space not in the OCIO config: 'X'. Choose one of its colour spaces.",
    "View not in the OCIO config: 'v' on display 'd'. Choose one of the display's views.",
    "Look not in the OCIO config: 'l'. Choose one of its looks."])
    assert.notEqual(plainError(m), "a file it needs is missing.");
});
