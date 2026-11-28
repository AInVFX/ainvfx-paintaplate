"""README.md and CONTRIBUTING.md against the repository, beside tests/test_readme.py: every jump link reaches a heading,
the install steps list the Hugging Face page of every gated model and no other, and each count the README states equals
its source."""
import json
import os
import re
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
import get_models  # noqa: E402


def read(*path):
    with open(os.path.join(ROOT, *path), encoding="utf-8") as fh:
        return fh.read()


def anchors(text):
    """The anchors GitHub gives the headings of a Markdown text: the heading's words in lower case, punctuation dropped,
    each space a hyphen, and -1, -2 after a repeated one. Lines inside a code block are not headings."""
    found, seen, fence = set(), {}, False
    for line in text.splitlines():
        if line.lstrip().startswith("```"):
            fence = not fence
        heading = None if fence else re.match(r"#{1,6} +(.+?) *$", line)
        if heading:
            words = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading.group(1)).replace("`", "")
            slug = re.sub(r"[^\w\- ]", "", words.lower()).replace(" ", "-")
            found.add(slug if slug not in seen else f"{slug}-{seen[slug]}")
            seen[slug] = seen.get(slug, 0) + 1
    return found


README = read("README.md")


def section(title):
    """The README's section under `## title`, up to the next section of that level."""
    start = README.index(f"\n## {title}\n")
    end = README.find("\n## ", start + 1)
    return README[start:end if end > 0 else None]


class ReadmeLinks(unittest.TestCase):
    def test_every_jump_link_reaches_a_heading(self):
        missing = []
        for doc in ("README.md", "CONTRIBUTING.md"):
            for path, anchor in re.findall(r"\]\((?!https?:)([^)#\s]*)#([^)\s]+)\)", read(doc)):
                if path and not os.path.isfile(os.path.join(ROOT, path)):
                    missing.append(f"{doc}: {path}")
                elif anchor not in anchors(read(path or doc)):
                    missing.append(f"{doc}: {path}#{anchor}")
        self.assertEqual(missing, [], "jump links to files or headings that do not exist")
        contents = re.search(r"^\*\*Contents:\*\* (.+)$", README, re.M)
        self.assertEqual(re.findall(r"\]\(#([^)]+)\)", contents.group(1)), [a for a in (re.sub(r"[^\w\- ]", "", h.lower()).replace(" ", "-") for h in re.findall(r"^## (.+)$", README, re.M))],
                         "the contents line links every section, in order")

    def test_the_install_steps_list_every_gated_model_and_no_other(self):
        gated = {m["source"] for m in json.loads(read("web", "models.json"))["models"] if m.get("gated")}
        listed = set(re.findall(r"\]\((https://huggingface\.co/(?!datasets/|settings/)[\w.-]+/[\w.-]+)\)", section("Install")))
        self.assertEqual(sorted(listed), sorted(gated), "the Hugging Face pages whose terms come first")

    def test_each_count_equals_its_source(self):
        nodes = [n for n in re.search(r"^NODES = \[([^\]]*)\]", read("nodes.py"), re.M).group(1).split(",") if n.strip()]
        workflows = [n for n in os.listdir(os.path.join(ROOT, "web", "workflows")) if n.endswith(".json")]
        size = sum(get_models.SIZES[os.path.basename(path)] for _, path, _ in get_models.MODELS)
        stated = {name: re.search(pattern, README) for name, pattern in (
            ("nodes", r"a pack of (\d+) nodes"), ("workflows", r"one of (\d+) ComfyUI workflows"),
            ("files", r"(\d+) files, \d+ GB in all"), ("GB of disk", r"\*\*(\d+) GB of disk\*\*"))}
        self.assertEqual({k: int(v.group(1)) if v else None for k, v in stated.items()},
                         {"nodes": len(nodes), "workflows": len(workflows), "files": len(get_models.MODELS), "GB of disk": round(size / 1e9)})


if __name__ == "__main__":
    unittest.main()
