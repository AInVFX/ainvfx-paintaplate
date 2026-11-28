// Tests of what the page says when its check holds an erase back (web/logic.mjs: leftLines, leftHint).
import { test } from "node:test";
import assert from "node:assert/strict";
import { beyondDetail, leftHint, leftLines } from "../../web/logic.mjs";

const check = { changed: 0.17, edges: 0.62, left: true };

test("the question gives the check's two figures, then asks", () => {
  assert.equal(leftLines(1, check).question, "Edit 1: the object may still be there (17% of it changed, edges held at 0.62). Render the shot anyway?");
});

test("the log's line is the question's fact, once", () => {
  assert.equal(leftLines(1, check).fact, "Warning: edit 1, the object may still be there (17% of it changed, edges held at 0.62).");
});

test("a figure that the check could not measure is left out", () => {
  assert.equal(leftLines(2, { changed: 0.054, edges: null }).question, "Edit 2: the object may still be there (5% of it changed). Render the shot anyway?");
  assert.equal(leftLines(2, { changed: null, edges: null }).fact, "Warning: edit 2, the object may still be there.");
});

test("figures round as the check's other lines do: whole percents, edges to two decimals", () => {
  assert.equal(leftLines(3, { changed: 0.296, edges: 0.8549 }).fact, "Warning: edit 3, the object may still be there (30% of it changed, edges held at 0.85).");
});

test("after « Render anyway » the log says why the shot rendered", () => {
  assert.equal(leftLines(1, check).rendered, "Edit 1: kept at your request. The check found the object still there.");
});

test("after Cancel the status line is the fact, then what to do next", () => {
  const { fact } = leftLines(1, check);
  assert.equal(`${fact} ${leftHint("")}`, "Warning: edit 1, the object may still be there (17% of it changed, edges held at 0.62). Type its name in the text prompt, then press Enter.");
  assert.equal(`${fact} ${leftHint("barn")}`, "Warning: edit 1, the object may still be there (17% of it changed, edges held at 0.62). Use another text prompt, then press Enter. Press Ctrl+Enter to try another seed.");
});

test("an erase held back for the area around its object: the warning, the question, the kept line, and the detail line", () => {
  const around = { changed: 0.96, edges: -0.01, left: false, beyond: 0.324, beyondEdges: 0.73, why: "beyond" }, lines = leftLines(1, around);
  assert.equal(lines.fact, "Warning: edit 1, the erase also changed the area around the object (32% of that area changed, edges held at 0.73).");
  assert.equal(lines.question, "Edit 1: the erase also changed the area around the object (32% of that area changed, edges held at 0.73). Render the shot anyway?");
  assert.equal(lines.rendered, "Edit 1: kept at your request. The check found the area around the object changed.");
  assert.equal(beyondDetail({ beyond: 0.021, beyondEdges: 0.95 }), "\n  Around the object: 2% changed, edges held at 0.95.");
  assert.equal(beyondDetail({ beyond: undefined }), ""); // a check with no band
});
