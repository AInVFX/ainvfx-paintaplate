"""The jobs Upscale ran, from a running ComfyUI's history, as ComfyUI API files: one file per job, exactly the prompt ComfyUI
ran (its node ids, classes, inputs and titles), the windows' upscale jobs in the order they ran, then the join of each part
(upscale_export). Dropped on ComfyUI's canvas, a file opens as the graph that ran; Queue runs it again on the same files of
the output folder.

  python tests/upscale_prompts.py --url http://127.0.0.1:8188 --out ~/paintaplate_gpu/prompts [--last 50]

--last: how many of ComfyUI's latest jobs to read (its history keeps the latest, up to its own limit)."""
import argparse
import json
import os
import sys
import urllib.request

KINDS = {"SeedVR2TemporalChunk": "upscale", "PaintAPlate_JoinWindows": "upscale_export"}  # the node that names each of Upscale's two workflows


def kind(prompt: dict) -> str:
    """upscale, upscale_export, or "" for a job of another workflow."""
    classes = {n.get("class_type") for n in prompt.values() if isinstance(n, dict)}
    return next((k for c, k in KINDS.items() if c in classes), "")


def jobs(history: dict) -> list:
    """Upscale's jobs in a /history answer, in the order they ran: (number, prompt id, kind, prompt, status)."""
    found = [(h["prompt"][0], pid, kind(h["prompt"][2]), h["prompt"][2], (h.get("status") or {}).get("status_str", ""))
             for pid, h in history.items() if len(h.get("prompt") or []) > 2 and kind(h["prompt"][2])]
    return sorted(found, key=lambda j: j[0])


def save(history: dict, out: str) -> list:
    """Writes each of Upscale's jobs as <n>_<kind>_<id>.json in `out`; returns (file, kind, status) for each."""
    os.makedirs(out, exist_ok=True)
    rows = []
    for n, (_, pid, k, prompt, status) in enumerate(jobs(history), 1):
        name = f"{n:03}_{k}_{pid[:8]}.json"
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            json.dump(prompt, f, indent=1)
        rows.append((name, k, status))
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8188")
    ap.add_argument("--out", required=True)
    ap.add_argument("--last", type=int, default=50, help="ComfyUI's latest jobs to read")
    a = ap.parse_args()
    with urllib.request.urlopen(f"{a.url}/history?max_items={a.last}") as r:
        rows = save(json.load(r), os.path.expanduser(a.out))
    print("| File | Workflow | Status |\n| --- | --- | --- |\n" + "\n".join(f"| {n} | {k} | {s} |" for n, k, s in rows))
    sys.exit(0 if rows else 1)  # no Upscale job in the history read


if __name__ == "__main__":
    main()
