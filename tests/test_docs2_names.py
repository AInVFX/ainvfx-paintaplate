"""Every name that ARCHITECTURE.md puts in backticks is found in the code: a field of the page's state (`S.name`), a member
of a module (`logic.name`, `routes.name`), a file, or any other name of the code. A name the code no longer has is a fault
of the document. A field must be the state's own; a member must be defined in its module, or used outside its comments."""
import os
import re
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CODE = (".py", ".mjs", ".js", ".json", ".sh", ".yml", ".yaml", ".toml", ".css", ".html", ".txt")
MODULES = {"logic": "web/logic.mjs", "app": "web/app.mjs", "frames": "web/frames.mjs", "display": "web/display.mjs",
           "inspector": "web/inspector.mjs", "xray": "web/xray.mjs", "graph": "web/graph.mjs", "comfy": "web/comfy.mjs",
           "models": "web/models.mjs", "routes": "routes.py", "mathops": "mathops.py", "ocio": "ocio.py", "plateio": "plateio.py",
           "folders": "folders.py", "nodes": "nodes.py", "cache": "cache.py", "build_workflows": "tools/build_workflows.py",
           "ui_mock": "tests/ui_mock.py"}
FILES = {"py", "mjs", "js", "json", "css", "html", "md", "sh", "yml", "toml", "txt", "mu", "cpp", "glsl", "png", "exr", "mp4", "zip"}  # a file's last part


def code():
    """Every text file of the code by its path from the root, and the names of all files without their extension."""
    texts, stems = {}, set()
    for folder, dirs, names in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        for name in names:
            stems.add(name.split(".")[0])
            if name.endswith(CODE):
                path = os.path.join(folder, name)
                with open(path, encoding="utf-8", errors="replace") as fh:
                    texts[os.path.relpath(path, ROOT).replace(os.sep, "/")] = fh.read()
    return texts, stems


def uncommented(text, js):
    return "\n".join(line.split("//")[0] if js else line.split("#")[0] for line in text.split("\n"))


def missing(doc, texts, stems):
    """The backticked names of `doc` that the code does not have."""
    blob = "\n".join(texts.values())
    app = texts["web/app.mjs"]
    state = app[app.index("const S = {"):app.index("\n};", app.index("const S = {"))]
    gone = []
    for token in sorted(set(re.findall(r"`([^`\n]+)`", doc))):
        name = token.strip().removesuffix("()")
        if not re.fullmatch(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*", name) or name.rsplit(".", 1)[-1] in FILES and "." in name:
            continue  # a path, a route, a value, a key or a file: other tests read those
        head, _, rest = name.partition(".")
        if head == "S" and rest:
            field = rest.split(".")[0]
            found = re.search(rf"\bS\.{field}\b", app) or re.search(rf"(?m)[{{,\s]{field}:", state)
        elif head in MODULES and rest:
            member, path = rest.split(".")[0], MODULES[head]
            js = path.endswith(".mjs")
            defined = (rf"(?m)^\s*export\s+(?:async\s+)?(?:function\*?|const|let|class)\s+{member}\b" if js
                       else rf"(?m)^(?:\s*(?:async\s+)?(?:def|class)\s+{member}\b|{member}\s*[:=])")
            found = re.search(defined, texts[path]) or re.search(rf"\b{member}\b", uncommented(texts[path], js))
        else:
            last = name.split(".")[-1]
            found = last in stems or re.search(rf"\b{re.escape(last)}\b", blob)
        if not found:
            gone.append(token)
    return gone


class Names(unittest.TestCase):
    def test_every_name_of_the_architecture_is_in_the_code(self):
        texts, stems = code()
        with open(os.path.join(ROOT, "ARCHITECTURE.md"), encoding="utf-8") as fh:
            self.assertEqual(missing(fh.read(), texts, stems), [], "ARCHITECTURE.md names what the code does not have")


if __name__ == "__main__":
    unittest.main()
