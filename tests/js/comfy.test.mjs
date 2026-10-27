// The ComfyUI client (web/comfy.mjs), with fetch stubbed.
import assert from "node:assert/strict";
import { test } from "node:test";
import { historyRecord } from "../../web/comfy.mjs";

test("outputs are read only once ComfyUI has recorded the prompt", async () => {
  const answers = [{}, { abc: { status: { completed: false } } }, { abc: { status: { completed: true }, outputs: { 9: { images: [1] } } } }];
  let calls = 0;
  globalThis.fetch = async () => ({ json: async () => answers[Math.min(calls++, answers.length - 1)] });
  const record = await historyRecord("abc", { wait: 1 });
  assert.equal(calls, 3); // success arrives before the record: the client waits for it
  assert.deepEqual(record.outputs, { 9: { images: [1] } });
  calls = 0;
  globalThis.fetch = async () => ({ json: async () => ({}) });
  assert.equal(await historyRecord("gone", { tries: 3, wait: 1 }), null);
});
