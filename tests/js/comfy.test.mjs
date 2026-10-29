// The ComfyUI client (web/comfy.mjs), with fetch stubbed.
import assert from "node:assert/strict";
import { test } from "node:test";
import { recordable, historyRecord, upload } from "../../web/comfy.mjs";

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

test("the job index keeps only jobs whose files are all in the output folder", () => {
  const saved = { 9: { images: [{ filename: "f_00001_.png", subfolder: "x", type: "output" }] }, 3: { text: ["1 file(s)"] } };
  assert.equal(recordable(saved), true);
  assert.equal(recordable({ ...saved, 20: { images: [{ filename: "ComfyUI_temp_a_00001_.png", subfolder: "", type: "temp" }] } }), false);
  assert.equal(recordable({ 3: { text: ["a caption"] } }), true); // the prompt writer's words: no file at all
  assert.equal(recordable({}), false);
});

test("a failed read of the history is asked again: a dropped connection or a proxy's error page never strands a done job", async () => {
  let calls = 0;
  globalThis.fetch = async () => {
    calls++;
    if (calls === 1) throw new TypeError("Failed to fetch");
    if (calls === 2) return { json: async () => { throw new SyntaxError("Unexpected token '<'"); } };
    return { json: async () => ({ abc: { status: { completed: true }, outputs: { 9: { images: [1] } } } }) };
  };
  assert.deepEqual((await historyRecord("abc", { wait: 1 })).outputs, { 9: { images: [1] } });
  assert.equal(calls, 3);
});

test("an upload answered by an error page fails instead of waiting forever", async () => {
  globalThis.XMLHttpRequest = class {
    upload = {};
    open() {}
    send() { [this.status, this.responseText] = [200, "<html>502 Bad Gateway</html>"]; queueMicrotask(() => this.onload()); }
  };
  await assert.rejects(upload(new Blob(["x"]), "a.png", "paintaplate/up"), /Upload failed: a\.png/);
});
