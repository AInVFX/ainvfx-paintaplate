// The Preview menu's rules (logic.readPreview, previewDivOf, liveEvery) and the composite step's name for Light edits.
import { test } from "node:test";
import assert from "node:assert/strict";
import { liveEvery, PREVIEW_DEFAULT, previewDivOf, readPreview, stepLabel } from "../../web/logic.mjs";

test("Latent preview is the default: no preview pass, and every step sends its live preview", () => {
  assert.equal(PREVIEW_DEFAULT, "latent");
  assert.equal(previewDivOf(PREVIEW_DEFAULT), 0);
  assert.equal(liveEvery(PREVIEW_DEFAULT), 1);
});

test("Off makes no preview pass and asks the workflows for no live preview", () => {
  assert.equal(previewDivOf("off"), 0);
  assert.equal(liveEvery("off"), 0);
});

test("half and quarter size keep their preview pass and the live preview", () => {
  for (const d of [2, 4]) { assert.equal(previewDivOf(d), d); assert.equal(liveEvery(d), 1); }
});

test("a stored or saved choice reads back; a scene's 0, no preview pass, opens as Latent preview", () => {
  assert.equal(readPreview("off"), "off");
  assert.equal(readPreview("latent"), "latent");
  assert.equal(readPreview("2"), 2);
  assert.equal(readPreview(4), 4);
  assert.equal(readPreview(0), "latent");
  assert.equal(readPreview("0"), "latent");
});

test("anything else keeps the choice in use: an older scene's size in px, nothing stored", () => {
  for (const v of [640, "640", null, undefined, "", "half", 3]) assert.equal(readPreview(v), null, String(v));
});

test("for a set of Light edits only, the composite steps read Light transfer; other steps keep their names", () => {
  const comp = { id: "comp", label: "Composite, preview" }, review = { id: "review", label: "Composite, full size" }, shot = { id: "shot", label: "Shot, preview" };
  assert.equal(stepLabel(comp, true), "Light transfer, preview");
  assert.equal(stepLabel(review, true), "Light transfer, full size");
  assert.equal(stepLabel(shot, true), "Shot, preview");
  assert.equal(stepLabel(comp, false), "Composite, preview");
  assert.equal(stepLabel(review, false), "Composite, full size");
});
