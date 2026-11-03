// Models and licences: which models made the result on show, and every model with its licence, from the registry
// web/models.json. The models behind a result come from the workflows that made it: each workflow's own files, read from
// its API JSON (the loaders' file names), matched to the registry. Pure functions, tested in tests/js/models.test.mjs.

// The model files a workflow loads: every input value that names a .safetensors file
export function workflowFiles(prompt) {
  const out = new Set();
  for (const node of Object.values(prompt ?? {}))
    for (const v of Object.values(node?.inputs ?? {})) if (typeof v === "string" && v.endsWith(".safetensors")) out.add(v.split("/").pop());
  return out;
}

// The workflows behind a result: the edits on show by tool, a fluid shot, SDR to HDR, and the live preview's decoder
export function workflowsFor({ tools = [], fluid = false, hdr = false }) {
  const t = new Set(tools), w = new Set();
  if (fluid) w.add("fluid");
  if (t.size) ["prompt", "edit", "comp", "review"].forEach((n) => w.add(n));
  if (t.has("erase")) ["snap", "matte", "clean", "cleanup"].forEach((n) => w.add(n));
  if (t.has("paint")) ["shot", "matte"].forEach((n) => w.add(n));
  if (t.has("light")) w.add("shot");
  if (hdr && (fluid || t.size)) w.add("hdr");
  return [...w];
}

// The registry's entries for the files these workflows load, in the registry's order, each with the workflows that use it
export function modelsBehind(registry, workflows, promptOf) {
  const by = new Map();
  for (const name of workflows) for (const f of workflowFiles(promptOf(name))) by.set(f, [...(by.get(f) ?? []), name]);
  return registry.models.filter((m) => by.has(m.file)).map((m) => ({ ...m, workflows: by.get(m.file) }));
}
