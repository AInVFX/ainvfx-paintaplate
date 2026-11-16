// A render's step lines in the log, the form of choice 13: « Render vN: <the step's label>: <what happened>. ». The line of a
// step that a new edit stops, or that finishes first, takes the same form as its start and its end.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

test("every line of a render's step names the step, then a colon, then what happened", () => {
  const app = readFileSync(new URL("../../web/app.mjs", import.meta.url), "utf8");
  const lines = [...app.matchAll(/log\(`Render v\$\{r\.v\}: \$\{(?:def\.label|STAGES\.find\(\(x\) => x\.id === id\)\.label)\}([^`]*)`\)/g)].map((m) => m[1]);
  assert.ok(lines.length >= 5, `${lines.length} step lines found`);
  for (const rest of lines) assert.match(rest, /^: /, rest);
});
