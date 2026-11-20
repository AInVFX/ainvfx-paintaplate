"""Export: « ComfyUI graph » is a tick box among Export's parts, and the scene's graph comes in the zip, beside the result.
The dialog's words come from one source, and none says « The zip downloads at once »."""
import json
import zipfile


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.36, 0.5)]); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    page.click("#export-btn")
    U.check(page.is_visible("#x-graph") and page.get_attribute("#x-graph", "type") == "checkbox" and not page.is_checked("#x-graph"),
            "ComfyUI graph is a tick box among Export's parts, off")
    U.check("downloads at once" not in (page.text_content("#export") or "") and page.text_content("#x-hint").startswith("Export writes the selected files"),
            f"the dialog says what Export does: {page.text_content('#x-hint')!r}, {page.text_content('#x-note')!r}")
    page.check("#x-graph")
    with page.expect_download(timeout=180000) as dl:
        page.click("#x-go")
    z = zipfile.ZipFile(dl.value.path())
    U.check("scene.comfyui.json" in z.namelist() and any(n.startswith("export/") for n in z.namelist()),
            f"the zip holds the graph beside the result: {sorted({n.split('/')[0] for n in z.namelist()})}")
    graph = json.loads(z.read("scene.comfyui.json"))
    U.check(bool(graph["nodes"]) and bool(graph["groups"]), f"the graph is a ComfyUI workflow: {len(graph['nodes'])} nodes in {len(graph['groups'])} groups")
    U.no_errors(errors, "after the export with its graph")
    page.close()
