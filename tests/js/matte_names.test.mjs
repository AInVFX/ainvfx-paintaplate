// The matte's naming request to the prompt upsampler: the edits' text prompts as typed, joined; none without a text prompt.
import { test } from "node:test";
import assert from "node:assert/strict";
import { nameRequest } from "../../web/logic.mjs";

test("the naming request holds the edits' text prompts, joined, and there is none without a text prompt", () => {
  assert.equal(nameRequest("paint", ["", "  ", undefined]), "");
  assert.ok(nameRequest("paint", ["a red car", " smoke "]).includes('"a red car; smoke"'));
  assert.ok(nameRequest("erase", ["the barn"]).startsWith("The edit removes this from the image: \"the barn\"."));
});

test("a text prompt goes in as typed: its double quotes become single, and « $& » is no pattern", () => {
  assert.ok(nameRequest("erase", ['the "old" barn']).includes("\"the 'old' barn\""));
  for (const text of ["a $& bill", "it costs $$5", "a $' sign", "a $` sign"]) assert.ok(nameRequest("paint", [text]).includes(`"${text}"`), text);
});
