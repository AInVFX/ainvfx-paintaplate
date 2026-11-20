// The page's own files are public writing: they say what the code is and how it works, for a reader who knows nothing of how
// it was made. No word of the work behind it (a wave, an agent, a handover…), and a GPU is a GPU, never a card.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (f) => readFileSync(new URL(`../../${f}`, import.meta.url), "utf8");
const FILES = ["web/app.mjs", "web/logic.mjs", "web/paintaplate.html", "README.md"];

test("no word of the work behind the code", () => {
  const words = /\b(waves?|workstreams?|agents?|hand-?overs?|orchestrators?|sandbox|laptop|yesterday|by mistake|previously)\b|\bAdrien\b/i;
  assert.deepEqual(FILES.filter((f) => words.test(read(f))), []);
});

test("a GPU is a GPU, never a card", () => {
  const gpu = /\b(?:the|a|larger|every|\d+ GB) card\b|\bcard's (?:reference|VRAM)|\bto the card\b|\bcards of \d/i;
  assert.deepEqual(FILES.filter((f) => gpu.test(read(f))), []);
});
