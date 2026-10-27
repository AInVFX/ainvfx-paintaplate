// The ComfyUI client of the page: workflows, jobs, the WebSocket, uploads. No DOM and no app state.
// Every step of the app is a workflow from ./workflows, written by tools/build_workflows.py.

import { fillWorkflow, parseWorkflow } from "./logic.mjs";

const CLIENT = crypto.randomUUID();
export const WF = {}; // name -> { prompt, slots, outputs, progress }
const live = new Set(); // jobs not finished yet
const byId = new Map(); // prompt id -> job, for WebSocket messages
const early = new Map(); // results that arrived before /prompt answered
const memo = new Map(); // prompt -> outputs, for prompts ComfyUI serves entirely from its cache
const MEMO_MAX = 64;
const QUIET_MS = 15000; // a prompt not heard of for this long is looked up in /history
let running = null; // the prompt ComfyUI is executing now
let socket = false; // the WebSocket is open: when it is not, finished prompts are found by polling /history
let notice = () => {};

export const onNotice = (fn) => { notice = fn; }; // what the client has to tell the person (a retry, for example)

export const post = (path, body) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export async function loadWorkflows(names) {
  for (const name of names) WF[name] = parseWorkflow(await (await fetch(`workflows/${name}.json`)).json());
}

export async function objectInfo(cls) {
  return (await (await fetch(`/object_info/${cls}`)).json())[cls];
}

export function upload(blob, name, sub, onProgress) { // XMLHttpRequest, not fetch: it reports upload progress
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("image", blob, name);
    form.append("subfolder", sub);
    form.append("overwrite", "true");
    const x = new XMLHttpRequest();
    x.open("POST", "/upload/image");
    x.upload.onprogress = (e) => onProgress?.(e.loaded);
    x.onerror = () => reject(new Error(`Upload failed: ${name}`));
    x.onload = () => {
      if (x.status < 200 || x.status > 299) return reject(new Error(`Upload failed: ${name}`));
      const j = JSON.parse(x.responseText);
      resolve(j.subfolder ? `${j.subfolder}/${j.name}` : j.name);
    };
    x.send(form);
  });
}

// Post a workflow with its slots filled. `kind` groups jobs for cancel(); `progress` receives 0..1 from the node
// marked as the workflow's progress; `preview` receives step images; `step` receives the class of each node that runs.
export function run(name, values, { kind = name, preview, progress, step, front = false } = {}) {
  const wf = fillWorkflow(WF[name], values);
  const job = { kind, preview, progress, retries: 1, key: JSON.stringify(wf.prompt), main: wf.progress,
    step: step && ((id) => step(wf.prompt[id]?.class_type)) };
  job.done = new Promise((resolve, reject) => Object.assign(job, { resolve, reject }));
  job.submit = () => post("/prompt", { prompt: wf.prompt, client_id: CLIENT, front }).then((r) => r.json()).then((j) => {
    if (!j.prompt_id) throw new Error(rejection(j));
    job.id = j.prompt_id;
    job.heard = Date.now();
    if (job.cancelled) return void drop(job); // cancelled while it was being posted
    byId.set(job.id, job);
    if (early.has(job.id)) finish(job.id, early.get(job.id));
  }).catch((e) => job.reject(e));
  live.add(job);
  job.submit();
  return job;
}

function rejection(j) {
  const node = Object.values(j.node_errors ?? {})[0];
  const err = node?.errors?.[0];
  return node ? `${node.class_type}: ${err?.details || err?.message}` : j.error?.message ?? "Workflow rejected";
}

async function finish(id, error) {
  if (id === running) running = null;
  const job = byId.get(id);
  if (!job) return void early.set(id, error);
  byId.delete(id);
  early.delete(id);
  // An interrupt can land on the next prompt when the one it targeted had just finished: run it again once.
  if (error === "cancelled" && !job.cancelled && job.retries-- > 0) return job.submit();
  if (error && /out of memory|allocation on device/i.test(error) && !job.freed) { // models and caches piled up on the GPU
    job.freed = true;
    notice("The GPU ran out of memory: freeing ComfyUI's memory, then trying once more.");
    await post("/free", { unload_models: true, free_memory: true });
    return job.submit();
  }
  live.delete(job);
  if (error) return job.reject(new Error(error));
  let out = (await historyRecord(id))?.outputs ?? {};
  if (files(out).length || Object.values(out).some((o) => o.text?.length)) memo.set(job.key, out);
  else out = memo.get(job.key) ?? out;
  if (memo.size > MEMO_MAX) memo.delete(memo.keys().next().value);
  job.resolve(out);
}

// ComfyUI reports success from inside the run and records the history just after (execution.py, then main.py's
// task_done): read too early, the record is missing and the outputs look empty. So wait for the record.
export async function historyRecord(id, { tries = 100, wait = 100 } = {}) {
  for (let i = 0; i < tries; i++) {
    const record = (await (await fetch(`/history/${id}`)).json())[id];
    if (record?.status?.completed || record?.status?.status_str === "error") return record;
    await new Promise((ok) => setTimeout(ok, wait));
  }
  return null;
}

function drop(job) { // remove it from the queue, and stop it if it is the one running (ComfyUI checks the id)
  if (!job.id) return;
  post("/queue", { delete: [job.id] });
  post("/interrupt", { prompt_id: job.id });
}

export function cancel(...kinds) {
  for (const job of live) {
    if (!kinds.includes(job.kind)) continue;
    job.cancelled = true;
    live.delete(job);
    byId.delete(job.id);
    job.reject(new Error("cancelled"));
    drop(job);
  }
}

function message({ data }) {
  if (typeof data !== "string") { // step preview with metadata: [type=4][length][json][image]
    const v = new DataView(data);
    if (v.getUint32(0) !== 4) return;
    const n = v.getUint32(4);
    const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(data, 8, n)));
    byId.get(meta.prompt_id)?.preview?.(new Blob([new Uint8Array(data, 8 + n)], { type: meta.image_type }));
    return;
  }
  const { type, data: d } = JSON.parse(data);
  const job = byId.get(d?.prompt_id);
  if (job) job.heard = Date.now();
  if (type === "execution_start") { running = d.prompt_id; job?.progress?.(0); }
  else if (type === "executing" && d.node) {
    job?.step?.(d.node);
    if (job?.main.has(String(d.node))) job.inMain = true;
    else if (job?.inMain) job.progress?.(0.97); // the main node is done; saving remains
  } else if (type === "progress") {
    if (job && (!job.main.size || job.main.has(String(d.node)))) job.progress?.(0.02 + (0.93 * d.value) / d.max);
  } else if (type === "execution_success") finish(d.prompt_id);
  else if (type === "execution_error") finish(d.prompt_id, `${d.node_type}: ${d.exception_message}`);
  else if (type === "execution_interrupted") finish(d.prompt_id, "cancelled");
}

async function poll() { // some networks block WebSockets: then, and for prompts gone quiet, ask /history
  for (const job of [...byId.values()]) {
    if (socket && Date.now() - job.heard < QUIET_MS) continue;
    let st;
    try { st = (await (await fetch(`/history/${job.id}`)).json())[job.id]?.status; } catch { continue; }
    if (!st || !byId.has(job.id)) continue;
    job.heard = Date.now();
    const err = st.messages?.find((m) => m[0] === "execution_error")?.[1];
    if (st.status_str === "error") finish(job.id, st.messages?.some((m) => m[0] === "execution_interrupted") ? "cancelled"
      : err ? `${err.node_type}: ${err.exception_message}` : "The workflow failed");
    else if (st.completed) finish(job.id);
  }
}

export function connect() {
  const open = () => {
    const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws?clientId=${CLIENT}`);
    ws.binaryType = "arraybuffer";
    ws.onopen = () => { socket = true; ws.send(JSON.stringify({ type: "feature_flags", data: { supports_preview_metadata: true } })); };
    ws.onclose = () => { socket = false; setTimeout(open, 2000); };
    ws.onmessage = message;
  };
  open();
  setInterval(poll, 1500);
}

// ---------- Outputs ----------

export const files = (out) => Object.values(out).flatMap((o) => [...(o.images ?? []), ...(o.gifs ?? []), ...(o.video ?? [])]);
export const outputFiles = (name, out, key) => files({ x: out[WF[name].outputs[key]] ?? {} });
export const outputFile = (name, out, key) => outputFiles(name, out, key)[0];
export const outputText = (name, out, key) => out[WF[name].outputs[key]]?.text?.[0];
export const viewUrl = (f) => `/view?${new URLSearchParams({ filename: f.filename, subfolder: f.subfolder, type: f.type })}`;
