// The ComfyUI client of the page: workflows, jobs, the WebSocket, uploads. No DOM and no app state.
// Every step of the app is a workflow from ./workflows, written by tools/build_workflows.py.

import { fillWorkflow, indexValues, parseWorkflow } from "./logic.mjs";

const CLIENT = crypto.randomUUID();
export const WF = {}; // name -> { prompt, slots, outputs, progress }
const live = new Set(); // jobs not finished yet (a job's own `live` is its live-preview callback)
const byId = new Map(); // prompt id -> job, for WebSocket messages
const early = new Map(); // results that arrived before /prompt answered
const memo = new Map(); // prompt -> outputs, for prompts ComfyUI serves entirely from its cache
const MEMO_MAX = 64;
const QUIET_MS = 15000; // a prompt not heard of for this long is looked up in /history
let running = null; // the prompt ComfyUI is executing now
let socket = false; // the WebSocket is open: when it is not, finished prompts are found by polling /history
let notice = () => {};
let log = () => {};
const infos = new Map(); // class -> /object_info answer, asked once
// The job index (routes.py): a finished job's outputs on disk, by the hash of its workflow, the plate and its values. A job
// that matches takes them back instead of running, in this session or a later one on the same machine. Only workflows whose
// outputs are saved files take part: the warm-up exists for its side effect, and SAM's object search keeps previews.
const INDEXED = new Set(["ingest", "prompt", "edit", "clean", "cleanup", "shot", "matte", "comp", "review", "export", "fluid"]);
const hashes = {}; // workflow name -> hash of its file: a new workflow makes new keys
let salt = null; // the plate's identity (path, size, time); null: no index, as when the plate could not be checked
export const setSalt = (s) => { salt = s; };

export async function hashHex(data) { // SHA-256 of a string or a Blob, in hex; null where the page has no WebCrypto (plain http)
  if (!globalThis.crypto?.subtle) return null;
  const bytes = typeof data === "string" ? new TextEncoder().encode(data) : new Uint8Array(await data.arrayBuffer());
  return [...new Uint8Array(await crypto.subtle.digest("SHA-256", bytes))].map((b) => b.toString(16).padStart(2, "0")).join("");
}

const indexKey = async (name, values) => (INDEXED.has(name) && salt !== null && hashes[name]
  ? hashHex(JSON.stringify([hashes[name], salt, indexValues(values)])) : null);

async function indexed(key) { // the outputs a finished job with this key made, if its files are all still there
  try { const r = await fetch(`/paintaplate/jobs/${key}`); return r.ok ? (await r.json()).outputs : null; } catch { return null; }
}

export const onNotice = (fn) => { notice = fn; };
// Until ComfyUI has released its models after /free: half of the GPU free, or `limit` ms. Its prompt worker applies a free
// between prompts, so the retry of a job that ran out of memory waits for it.
async function released(limit = 15000) {
  for (const t0 = Date.now(); Date.now() - t0 < limit; await new Promise((ok) => setTimeout(ok, 500))) {
    const gpu = (await fetch("/system_stats").then((r) => r.json()).catch(() => null))?.devices?.[0];
    if (!gpu?.vram_total || gpu.vram_free > gpu.vram_total / 2) return;
  }
} // what the client has to tell the person (a retry, for example)
export const onLog = (fn) => { log = fn; }; // every job posted, started, finished, failed or cancelled, with its timing
const short = (id) => (id ? String(id).slice(0, 8) : "?");
const took = (job) => `${((Date.now() - job.posted) / 1000).toFixed(1)} s`;

export const post = (path, body) =>
  fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

export async function loadWorkflows(names) { // all at once: ten small files, one round trip
  const loaded = await Promise.all(names.map(async (name) => {
    const text = await (await fetch(`workflows/${name}.json`)).text();
    return [name, parseWorkflow(JSON.parse(text)), await hashHex(text)];
  }));
  for (const [name, wf, hash] of loaded) [WF[name], hashes[name]] = [wf, hash];
}

export function objectInfo(cls) { // one request per class, however often it is asked
  if (!infos.has(cls)) infos.set(cls, fetch(`/object_info/${cls}`).then((r) => r.json()).then((j) => j[cls]).catch(() => { infos.delete(cls); return undefined; }));
  return infos.get(cls);
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
    x.onload = () => { // an answer that is not ComfyUI's JSON (a proxy's error page) fails the upload, never hangs it
      let j = null;
      try { j = JSON.parse(x.responseText); } catch { /* reported below */ }
      if (x.status < 200 || x.status > 299 || !j?.name) return reject(new Error(`Upload failed: ${name}`));
      resolve(j.subfolder ? `${j.subfolder}/${j.name}` : j.name);
    };
    x.send(form);
  });
}

// Post a workflow with its slots filled. `kind` groups jobs for cancel(); `progress` receives 0..1 from the node
// marked as the workflow's progress; `preview` receives step images; `step` receives the class of each node that runs;
// `live` receives the live previews of a shot.
export function run(name, values, { kind = name, preview, progress, step, live: onLive, front = false } = {}) {
  const wf = fillWorkflow(WF[name], values);
  const job = { kind, name, preview, progress, live: onLive, retries: 1, key: JSON.stringify(wf.prompt), main: wf.progress, posted: Date.now(),
    step: step && ((id) => step(wf.prompt[id]?.class_type)), classes: Object.fromEntries(Object.entries(wf.prompt).map(([id, n]) => [id, n.class_type])) };
  job.done = new Promise((resolve, reject) => Object.assign(job, { resolve, reject }));
  job.submit = () => post("/prompt", { prompt: wf.prompt, client_id: CLIENT, front }).then((r) => r.json()).then((j) => {
    if (!j.prompt_id) throw new Error(rejection(j));
    job.id = j.prompt_id;
    job.heard = Date.now();
    log(`${name}: posted as ${short(job.id)} (${Object.keys(wf.prompt).length} nodes${front ? ", front of the queue" : ""}${j.number != null ? `, number ${j.number}` : ""})`);
    if (job.cancelled) return void drop(job); // cancelled while it was being posted
    byId.set(job.id, job);
    if (early.has(job.id)) finish(job.id, early.get(job.id));
  }).catch((e) => job.reject(e));
  live.add(job);
  indexKey(name, values).then(async (key) => { // the job index first: a job made before with the same inputs is not run again
    job.index = key;
    const outputs = key && (await indexed(key));
    if (job.cancelled) return;
    if (!outputs) return job.submit();
    live.delete(job);
    log(`${name}: made before with the same inputs, taken from the job index`);
    progress?.(1);
    job.resolve(outputs);
  }).catch(() => { if (!job.cancelled) job.submit(); });
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
  if (error === "cancelled" && !job.cancelled && job.retries-- > 0) { log(`${job.name} ${short(id)}: interrupted by a stray interrupt, posted again`); return job.submit(); }
  if (error && /out of memory|allocation on device/i.test(error) && !job.freed) { // models and caches piled up on the GPU
    job.freed = true;
    notice("The GPU ran out of memory: freeing ComfyUI's memory, then trying once more.");
    await post("/free", { unload_models: true, free_memory: true }).catch(() => {}); // unanswered, the retry still runs
    await released(); // ComfyUI frees between prompts: a job posted at once ran first, with every model still loaded (29 Oct)
    return job.submit();
  }
  live.delete(job);
  if (error) { log(`${job.name} ${short(id)}: failed after ${took(job)}: ${error}`, "error"); return job.reject(new Error(error)); }
  let out = (await historyRecord(id))?.outputs ?? {};
  const fresh = files(out).length || Object.values(out).some((o) => o.text?.length);
  if (fresh) memo.set(job.key, out);
  else out = memo.get(job.key) ?? out;
  if (memo.size > MEMO_MAX) memo.delete(memo.keys().next().value);
  log(`${job.name} ${short(id)}: done in ${took(job)}${fresh ? "" : " (served from ComfyUI's cache)"}`);
  if (job.index && (files(out).length || Object.values(out).some((o) => o.text?.length))) // recorded for later sessions
    if (recordable(out)) post(`/paintaplate/jobs/${job.index}`, { workflow: job.name, outputs: out }).catch(() => {});
  job.resolve(out);
}

// ComfyUI reports success from inside the run and records the history just after (execution.py, then main.py's
// task_done): read too early, the record is missing and the outputs look empty. So wait for the record. A read that
// fails (a dropped connection, a proxy's error page) is asked again: thrown from finish(), it left a done job waiting.
export async function historyRecord(id, { tries = 100, wait = 100 } = {}) {
  for (let i = 0; i < tries; i++) {
    const record = await fetch(`/history/${id}`).then((r) => r.json()).then((h) => h?.[id]).catch(() => undefined);
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
    log(`${job.name} ${short(job.id)}: cancelled after ${took(job)}`);
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
  if (type === "execution_start") { running = d.prompt_id; job?.progress?.(0); if (job) log(`${job.name} ${short(d.prompt_id)}: ComfyUI started it ${took(job)} after the post`); }
  else if (type === "execution_cached" && job && d.nodes?.length) log(`${job.name} ${short(d.prompt_id)}: ${d.nodes.length} of ${Object.keys(job.classes).length} nodes from ComfyUI's cache`);
  else if (type === "executing" && d.node) {
    job?.step?.(d.node);
    if (job?.main.has(String(d.node))) { if (!job.inMain) log(`${job.name} ${short(d.prompt_id)}: ${job.classes[String(d.node)]} is running`); job.inMain = true; }
    else if (job?.inMain) job.progress?.(0.97); // the main node is done; saving remains
  } else if (type === "progress") {
    if (job && (!job.main.size || job.main.has(String(d.node)))) job.progress?.(0.02 + (0.93 * d.value) / d.max);
  } else if (type === "paintaplate.live") job?.live?.(d); // a live preview of a shot being sampled (nodes.py, Live Preview)
  else if (type === "execution_success") finish(d.prompt_id);
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

// The files a job made, as ComfyUI's history lists them; `files` holds what Save Plate wrote (ComfyUI's frontend ignores it)
export const files = (out) => Object.values(out).flatMap((o) => [...(o.images ?? []), ...(o.gifs ?? []), ...(o.video ?? []), ...(o.files ?? [])]);
// A job the job index can keep: it made something, and every file it made is in the output folder, as routes.write_job
// asks. A preview in the temporary folder is gone after a restart; posting it only earns a refusal, which browsers log.
export const recordable = (out) => Object.keys(out ?? {}).length > 0 && files(out).every((f) => f.type === "output");
export const outputFiles = (name, out, key) => files({ x: out[WF[name].outputs[key]] ?? {} });
export const outputFile = (name, out, key) => outputFiles(name, out, key)[0];
export const outputText = (name, out, key) => out[WF[name].outputs[key]]?.text?.[0];
export const viewUrl = (f) => `/view?${new URLSearchParams({ filename: f.filename, subfolder: f.subfolder, type: f.type })}`;
