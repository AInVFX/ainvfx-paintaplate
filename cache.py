"""The cache that renders leave in ComfyUI's output folder, and the part of it nothing uses. Under output/paintaplate,
each opening of a plate gets a folder named by its id: the plate's own files (its proxy movie, the first frames the
ingest makes), a folder for each render (v1, v2, ...) and one for the edits. A saved scene names the folders it uses
(its « folders »), and the page names those of the plate on screen: the rest is unused. An export (inside a folder named
export, or a file whose name holds « export ») and the scenes always stay. Clearing also drops the job index records
whose files went, so the index never offers a result it cannot give back. Pure file work: no ComfyUI, no torch."""
import json
import os
import re

ROOT = "paintaplate"
SCENES = "scenes"
JOBS = "jobs"
PART = re.compile(r"v\d+|edits")  # the folders of a plate's folder: a render's, the edits'


def is_export(path: str) -> bool:
    return "export" in os.path.basename(path) or "export" in path.replace(os.sep, "/").split("/")[:-1]


def scene_folders(out: str) -> set:
    """The folders that the saved scenes name, as paths under the output folder."""
    where, kept = os.path.join(out, ROOT, SCENES), set()
    for name in sorted(os.listdir(where)) if os.path.isdir(where) else []:
        try:
            with open(os.path.join(where, name), encoding="utf-8") as fh:
                kept.update(str(f) for f in json.load(fh).get("folders") or [])
        except (OSError, ValueError, AttributeError):
            continue
    return kept


def unused(out: str, keep=()) -> list:
    """The files of the unused cache under out/paintaplate, as (path, bytes). keep: folders the page still uses.
    A symbolic link is never followed nor listed, so clearing removes no file through a link, and no link."""
    root, kept, found = os.path.join(out, ROOT), set(keep) | scene_folders(out), []
    for plate in sorted(os.listdir(root)) if os.path.isdir(root) else []:
        home = os.path.join(root, plate)
        if plate in (SCENES, JOBS) or os.path.islink(home) or not os.path.isdir(home):
            continue
        entries = sorted(os.listdir(home))
        if not any(PART.fullmatch(e) and os.path.isdir(os.path.join(home, e)) for e in entries):
            continue  # not a plate's folder: it holds no render and no edit
        for e in entries:
            path = os.path.join(home, e)
            if os.path.islink(path):
                continue
            if os.path.isdir(path):
                if PART.fullmatch(e) and f"{ROOT}/{plate}/{e}" not in kept:
                    found += [(p, os.path.getsize(p)) for top, _, names in os.walk(path) for p in (os.path.join(top, n) for n in names)
                              if not os.path.islink(p) and not is_export(p)]
            elif f"{ROOT}/{plate}" not in kept and not is_export(path):
                found.append((path, os.path.getsize(path)))
    return found


def stale_jobs(out: str) -> list:
    """The job index records that name an output file which is no longer there."""
    where, gone = os.path.join(out, ROOT, JOBS), []
    for name in sorted(os.listdir(where)) if os.path.isdir(where) else []:
        path = os.path.join(where, name)
        try:
            with open(path, encoding="utf-8") as fh:
                record = json.load(fh)
        except (OSError, ValueError):
            continue
        outputs = record.get("outputs", record) if isinstance(record, dict) else {}
        files = [f for o in outputs.values() if isinstance(o, dict) for k in ("images", "gifs", "video", "files") for f in (o.get(k) or [])]
        if any(isinstance(f, dict) and f.get("type") == "output"
               and not os.path.isfile(os.path.join(out, str(f.get("subfolder") or ""), str(f.get("filename") or ""))) for f in files):
            gone.append(path)
    return gone


def clear(out: str, keep=()) -> tuple:
    """Removes the unused cache, the folders it leaves empty and the job index records whose files went: (files, bytes)."""
    found, root = unused(out, keep), os.path.join(out, ROOT)
    for path, _ in found:
        os.remove(path)
    for top, _, _ in sorted(os.walk(root), key=lambda w: -len(w[0])):  # the deepest folders first
        if top != root and os.path.basename(top) not in (SCENES, JOBS) and not os.listdir(top):
            os.rmdir(top)
    for path in stale_jobs(out):
        os.remove(path)
    return len(found), sum(size for _, size in found)
