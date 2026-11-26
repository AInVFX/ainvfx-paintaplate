// The lines that named the wrong thing: the memory line, the full-precision frames' line, the viewer's names for its picture
// and the big plate's warning (logic.freeAsk, deepLoading, pictureName, bigPlateWarning).
import { test } from "node:test";
import assert from "node:assert/strict";
import { bigPlateWarning, deepLoading, deepStopped, freeAsk, freesBefore, pictureName } from "../../web/logic.mjs";

const small = { frees: true }, GB = 2 ** 30;

test("memory is freed after a job that loaded models, never after one that loaded none", () => {
  assert.equal(freeAsk(small, "ingest", "fluid"), null); // opening the plate loads no model
  assert.equal(freeAsk(small, "review", "hdr"), null);
  assert.equal(freeAsk(small, "edit", "upscale"), "Memory freed before Upscale.\n  This GPU holds one model family at a time.");
  assert.deepEqual([freesBefore(small, "comp", "shot"), freesBefore(small, "matte", "comp")], [false, true]);
  assert.equal(freeAsk(small, "review", "matte", { free: 4 * GB, need: 14 * GB }), "Memory freed before the matte: 4 GB of RAM free, 14 GB needed for its frames.");
});

test("the full-precision frames' lines name the step displayed and the frames' own colour space", () => {
  assert.equal(deepLoading("Composite, HDR", 1920, "ACES2065-1"), "Full-precision frames of Composite, HDR: loading in the background, 1920 px on the long side, ACES2065-1.");
  assert.equal(deepStopped("Composite, HDR", "Failed to fetch"), "Error: full-precision frames of Composite, HDR: stopped (Failed to fetch). Viewer: 8-bit movie.");
});

test("the viewer names a picture that no step shows: an Upscale of another size, the edited first frame", () => {
  assert.equal(pictureName({ shot: true, upscaled: { label: "Plate, upscaled", size: ["2560", "1440"] } }), "Plate, upscaled to 2560 x 1440");
  assert.equal(pictureName({ edits: true }), "Edited first frame");
  assert.deepEqual([pictureName({ shot: true, edits: true }), pictureName()], ["Result", "Plate"]);
});

test("a plate above 2K on a GPU under 96 GB: renders take much longer", () => {
  assert.equal(bigPlateWarning({ width: 3840, height: 2160 }, 32 * GB),
    "Warning: this plate is 3840 x 2160, above 2K, and this GPU has 32 GB of VRAM. Renders take much longer here: use a 96 GB GPU for plates above 2K.");
  assert.equal(bigPlateWarning({ width: 3840, height: 2160 }, 96 * GB), null);
});
