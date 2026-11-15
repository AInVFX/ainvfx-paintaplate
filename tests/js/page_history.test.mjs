// The page workstream's check of History's row when the page asks for an object's name (logic.askedText): the row adds
// what the prompt writer saw when the edit holds it.
import assert from "node:assert/strict";
import { test } from "node:test";
import { askedText } from "../../web/logic.mjs";

test("askedText with and without what the prompt writer saw", () => {
  assert.equal(askedText(true), "Needs its name");
  assert.equal(askedText("the barn"), "Needs its name (the prompt writer saw the barn)");
  assert.equal(askedText(""), "Needs its name");
});
