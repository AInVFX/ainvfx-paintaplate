// The page workstream's check of the hint that a line naming a missing model file adds on the status line
// (logic.missingFileHint): the log keeps the fact, and the status line adds what to do.
import assert from "node:assert/strict";
import { test } from "node:test";
import { missingFileHint } from "../../web/logic.mjs";

test("a line that names models/vae_approx gets the command that fetches the file", () => {
  assert.equal(missingFileHint("Warning: live preview off: decoder taeltx2_3.safetensors not in models/vae_approx."), "Run python get_models.py.");
  assert.equal(missingFileHint("Warning: live preview off: no preview on this GPU."), "");
  assert.equal(missingFileHint("Render v1: Shot, preview: about 39 s.\n  models/vae_approx"), "", "the headline only");
});
