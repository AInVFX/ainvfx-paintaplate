// Models and licences: which models made the result displayed, and every model with its licence, from the registry
// web/models.json. The models behind a result come from the workflows that made it: each workflow's own files, read from
// its API JSON (the loaders' file names), matched to the registry. Pure functions, tested in tests/js/models.test.mjs.

// The model files a workflow loads: every input value that names a .safetensors file
export function workflowFiles(prompt) {
  const out = new Set();
  for (const node of Object.values(prompt ?? {}))
    for (const v of Object.values(node?.inputs ?? {})) if (typeof v === "string" && v.endsWith(".safetensors")) out.add(v.split("/").pop());
  return out;
}

// The registry's entries for the files these workflows load, in the registry's order, each with the workflows that use it
export function modelsBehind(registry, workflows, promptOf) {
  const by = new Map();
  for (const name of workflows) for (const f of workflowFiles(promptOf(name))) by.set(f, [...(by.get(f) ?? []), name]);
  return registry.models.filter((m) => by.has(m.file)).map((m) => ({ ...m, workflows: by.get(m.file) }));
}
