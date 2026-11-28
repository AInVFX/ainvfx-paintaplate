// The repository is public writing: the page, the pack, the tests and the documents say what the code is and how it works,
// for a reader who knows nothing of how it was made. No word of the work behind it (a wave or its folder, a round, an
// agent, a handover…), and on the page a GPU is a GPU, never a card.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";

const read = (f) => readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
const FILES = ["web/app.mjs", "web/logic.mjs", "web/paintaplate.html", "README.md"];
const under = (dir, ext) => readdirSync(new URL(`../../${dir}`, import.meta.url)).filter((n) => n.endsWith(ext)).map((n) => `${dir}${n}`);
const PUBLIC = [...new Set([...FILES, "ARCHITECTURE.md", "TESTING.md", "CONTRIBUTING.md", ...under("web/", ".mjs"), ...under("", ".py"), ...under("tests/", ".py"),
  ...under("tests/flows/", ".py"), ...under("tests/js/", ".mjs").filter((f) => !f.endsWith("words_public.test.mjs"))])]; // this file holds the words it looks for

test("no word of the work behind the code", () => {
  const words = /(?<!User-)\b(waves?|workstreams?|agents?|hand-?overs?|orchestrators?|sandbox|laptop|yesterday|by mistake|previously|w1\d|(?:round|candidate|turn) \d+)\b|\bAdrien\b/i;
  assert.deepEqual(PUBLIC.filter((f) => words.test(read(f))).map((f) => `${f}: « ${read(f).match(words)[0]} »`), []);
});

test("a GPU is a GPU, never a card", () => {
  const gpu = /\b(?:the|a|larger|every|\d+ GB) card\b|\bcard's (?:reference|VRAM)|\bto the card\b|\bcards of \d/i;
  assert.deepEqual(FILES.filter((f) => gpu.test(read(f))), []);
});
