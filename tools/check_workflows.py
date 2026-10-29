"""Check web/workflows against node definitions read from source (no GPU, no server).

    python tools/check_workflows.py /path/to/ComfyUI /path/to/ComfyUI-LTXVideo

Every class must exist and every input name must be one the class declares.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(__file__)
sys.path.insert(0, HERE)
from build_workflows import load  # noqa: E402


def scan(files):
    nodes, parents = {}, {}
    for path in files:
        src = open(path, encoding="utf-8", errors="ignore").read()
        # V3: node_id="X" ... Input("name" or id="name", until the next schema.
        for m in re.finditer(r'(?<![\w])node_id\s*=\s*"([^"]+)"', src):
            block = re.split(r'(?<![\w])node_id\s*=\s*"|\nclass ', src[m.end(): m.end() + 12000])[0]
            names = set(re.findall(r'\.Input\(\s*"([^"]+)"', block)) | set(re.findall(r'\bid\s*=\s*"([^"]+)"', block))
            nodes.setdefault(m.group(1), set()).update(names)
        # V1: NODE_CLASS_MAPPINGS entries or @comfy_node(name=...) classes, inputs from INPUT_TYPES (and the parent's, via super()).
        for key, cls in (re.findall(r'"([A-Za-z0-9_]+)"\s*:\s*([A-Za-z0-9_]+)\s*,', src)  # or ComfyUI-LTXVideo's decorator
                         + re.findall(r'@comfy_node\(\s*name\s*=\s*"([^"]+)"[^)]*\)\s*\nclass (\w+)', src)):
            cm = re.search(r'\nclass %s\b(?:\((\w+)\))?.*?(?=\nclass |\Z)' % re.escape(cls), src, re.S)
            if cm and "INPUT_TYPES" in cm.group(0):
                body = cm.group(0).split("INPUT_TYPES", 1)[1].split("RETURN_TYPES", 1)[0]
                nodes.setdefault(key, set()).update(re.findall(r'"([A-Za-z0-9_]+)"\s*:\s*\(', body))
                if "super().INPUT_TYPES" in body and cm.group(1):
                    parents[key] = cm.group(1)
    for key, parent in parents.items():
        nodes[key] |= nodes.get(parent, set())
    return nodes


def main(comfy, ltx):
    files = [os.path.join(comfy, "nodes.py"), *glob.glob(os.path.join(comfy, "comfy_extras", "*.py")),
             *glob.glob(os.path.join(ltx, "**", "*.py"), recursive=True), os.path.join(HERE, "..", "nodes.py")]
    known = scan(files)
    problems = 0
    folder = os.path.join(HERE, "..", "web", "workflows")
    for wf in sorted(glob.glob(os.path.join(folder, "*.json"))):
        prompt, slots, _ = load(os.path.splitext(os.path.basename(wf))[0], folder)
        for nid, node in prompt.items():
            cls = node["class_type"]
            if cls not in known:
                print(f"{os.path.basename(wf)} #{nid}: unknown class {cls}"); problems += 1; continue
            for name, value in node["inputs"].items():
                if name.split(".")[0] not in known[cls]:
                    print(f"{os.path.basename(wf)} #{nid} {cls}: unknown input '{name}'"); problems += 1
                if isinstance(value, list) and value[0] not in prompt:
                    print(f"{os.path.basename(wf)} #{nid} {cls}: link to missing node {value[0]}"); problems += 1
        for slot, targets in slots.items():
            for nid, name in targets:
                assert nid in prompt and name in prompt[nid]["inputs"], (wf, slot)
        print(f"{os.path.basename(wf)}: {len(prompt)} nodes, {len(slots)} slots")
    print("OK" if not problems else f"{problems} problem(s)")
    return problems


if __name__ == "__main__":
    sys.exit(1 if main(*sys.argv[1:3]) else 0)
