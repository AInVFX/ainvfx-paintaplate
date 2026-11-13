"""The page workstream's check of the scene's ComfyUI graph and its images (tests/flows/README.md). ComfyUI's image loaders
list only the files at the top of the input folder, and its editor marks any other file as missing. So every image loader
of the saved graph reads a file at the top of input, the file is there, the README note names it, and the API graph in
the same file reads the same files."""
import json
import urllib.parse
import urllib.request

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a lantern", [(0.30, 0.50), (0.36, 0.50)])
    page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    with page.expect_download(timeout=60000) as dl:
        page.click("#export-btn"); page.click("#x-graph")
    with open(dl.value.path()) as f:
        graph = json.load(f)
    loaders = {n["title"]: n["widgets_values"][0] for n in graph["nodes"] if n["type"] in ("LoadImage", "LoadImageMask")}
    readme = next(n for n in graph["nodes"] if n["type"] == "MarkdownNote")["widgets_values"][0]

    def there(name):
        query = urllib.parse.urlencode({"filename": name, "type": "input", "subfolder": ""})
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/view?{query}", timeout=10) as r:
                return r.status == 200
        except OSError:
            return False

    names = sorted(loaders.values())
    U.check(len(names) == 2 and all("/" not in v and v.startswith("paintaplate_desk_e1_") for v in names),
            f"each image loader of the graph reads a file at the top of the input folder: {loaders}")
    U.check(all(there(v) for v in names), f"each of those files is in the input folder: {[(v, there(v)) for v in names]}")
    U.check("must be in ComfyUI's input folder" in readme and all(v in readme for v in names), f"the README note names the files that must be on disk: {readme[:500]!r}")
    api = graph["extra"]["paintaplate"]["prompt"]
    U.check(sorted(n["inputs"]["image"] for n in api.values() if n["class_type"] in ("LoadImage", "LoadImageMask")) == names,
            "the API graph in the same file reads the same files")
    page.close()
