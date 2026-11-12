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

import { promptBody, PREVIEW_METHOD } from "../../web/comfy.mjs";

test("every job asks ComfyUI for the step previews it wants in its own post, so no start flag is needed", () => {
  const shown = promptBody({ 1: {} }, { front: true, preview: true });
  assert.deepEqual(shown.extra_data, { preview_method: PREVIEW_METHOD }, "a job that shows its steps, such as a Klein pass");
  assert.equal(PREVIEW_METHOD, "latent2rgb");
  assert.equal(shown.front, true);
  assert.deepEqual(shown.prompt, { 1: {} });
  assert.deepEqual(promptBody({}).extra_data, { preview_method: "none" }, "any other job: ComfyUI makes no preview for it");
  assert.equal(promptBody({}).front, false);
});

// ---------- Render: a job's lines in the log ----------
import { QUEUE_SAID_MS, jobDone, jobFailed, jobStopped, jobWaited } from "../../web/comfy.mjs";

test("a job writes one line when it ends, with its nodes, ComfyUI's cache and its previews folded in", () => {
  const job = { name: "ingest", id: "ef88a8f3-4a51-4c0e-9d0b-2f6f6f0f1a11", posted: 1000, sent: 1000, nodes: 10, cached: 3, previews: 8 };
  assert.equal(jobDone(job, 3000), "ingest ef88a8f3: done in 2.0 s (10 nodes, 3 from ComfyUI's cache, 8 previews)");
  assert.equal(jobDone({ ...job, cached: 0, previews: 1 }, 3000), "ingest ef88a8f3: done in 2.0 s (10 nodes, 1 preview)");
  assert.equal(jobDone({ ...job, nodes: 1, cached: 0, previews: 0 }, 1040), "ingest ef88a8f3: done in 0.0 s (1 node)");
  assert.equal(jobDone({ ...job, cached: 10, previews: 0 }, 1100, false), "ingest ef88a8f3: done in 0.1 s (10 nodes, 10 from ComfyUI's cache, outputs as it made them before)");
});

test("a job says that it waited only when it starts over a second after its post", () => {
  const job = { name: "shot", id: "0a1b2c3d-0000", posted: 0, sent: 5000, nodes: 24, number: 7, front: false };
  assert.equal(QUEUE_SAID_MS, 1000);
  assert.equal(jobWaited(job, 5000 + QUEUE_SAID_MS), null, "a second or less: no line, and the wait counts from the last post");
  assert.equal(jobWaited(job, 8200), "shot 0a1b2c3d: started after 3.2 s in ComfyUI's queue (number 7)");
  assert.equal(jobWaited({ ...job, front: true, number: undefined }, 8200), "shot 0a1b2c3d: started after 3.2 s in ComfyUI's queue (posted at the front)");
});

test("a job that failed or was stopped says it in one line; a stopped job says where it was", () => {
  const job = { name: "shot", id: "0a1b2c3d-0000", posted: 0, sent: 0, nodes: 24, cached: 20, previews: 3, started: 400, at: "SamplerCustomAdvanced" };
  assert.equal(jobFailed(job, 12000, "SamplerCustomAdvanced: Allocation on device"),
    "shot 0a1b2c3d: failed after 12.0 s (24 nodes, 20 from ComfyUI's cache, 3 previews): SamplerCustomAdvanced: Allocation on device");
  assert.equal(jobStopped(job, 12000), "shot 0a1b2c3d: stopped after 12.0 s in SamplerCustomAdvanced (24 nodes, 20 from ComfyUI's cache, 3 previews)");
  const queued = { ...job, cached: 0, previews: 0, started: null, at: null };
  assert.equal(jobStopped(queued, 2500), "shot 0a1b2c3d: stopped after 2.5 s in ComfyUI's queue (24 nodes)");
  assert.equal(jobStopped(queued, 2500, false), "shot 0a1b2c3d: stopped after 2.5 s (24 nodes)", "no WebSocket: the page does not know whether the job had started");
  assert.equal(jobStopped({ ...queued, id: undefined }, 100), "shot ?: stopped after 0.1 s before ComfyUI answered its post (24 nodes)");
});

// ---------- A stop: a job asked for under it is not posted ----------
import { WF, onStop, run } from "../../web/comfy.mjs";

test("under a stop, a job of a kind the stop ends is not posted: it ends as a cancelled job", async () => {
  WF.probe = { prompt: { 1: { class_type: "Probe", inputs: {} } }, slots: {}, outputs: {}, progress: null };
  const asked = [];
  globalThis.fetch = async (url) => { asked.push(String(url)); return { ok: false, json: async () => ({}) }; };
  onStop((kind) => kind === "matte"); // the page's rule: a stop is in force for the tracking jobs
  try {
    await assert.rejects(run("probe", {}, { kind: "matte" }).done, /^Error: cancelled$/);
    assert.deepEqual(asked, []); // neither the job index nor /prompt was asked
  } finally {
    onStop(() => false);
    delete WF.probe;
  }
});
