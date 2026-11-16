"""The clean plate pass's erased grid (tests/flows/README.md): by default it grows by one block of 32 px; with ?grid=composite
in the address it grows as far as the composite pastes an erase (logic.gridGrow), at the size of each pass. The flow reads
the value from the graphs the page posts to /prompt."""
import json

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"


def grids(bodies):
    """The blocks each posted clean pass grows its grid by: the « expand » of the GrowMask that the slot grid_grow fills."""
    return [n["inputs"]["expand"] for b in bodies for n in (json.loads(b).get("prompt") or {}).values()
            if n.get("class_type") == "GrowMask" and n.get("_meta", {}).get("slots", {}).get("expand") == "grid_grow"]


def run(browser, port, U):
    for query, one in (("?blank=0", True), ("?blank=0&grid=composite", False)):
        errors, bodies = [], []
        page = U.load(browser, port, query, errors=errors)
        page.on("request", lambda q: bodies.append(q.post_data) if q.method == "POST" and q.url.endswith("/prompt") else None)
        U.open_path(page, "plates/desk.mp4")
        page.wait_for_function(OPEN, timeout=60000)
        page.evaluate(U.WATCH)
        page.click('.tools [data-tool="erase"]')
        U.paint_once(page, "the mug", [(0.45, 0.55), (0.5, 0.6)])
        page.keyboard.press("Enter")
        U.wait_log(page, U.added_line("Clean plate pass, preview: done in"), 240000, "the clean plate pass at the preview's size")
        made = grids(bodies)
        U.check(made and all((g == 1) if one else (g > 1) for g in made), f"{query}: the clean plate pass grows its grid by {made} blocks")
        U.no_errors(errors, query)
        page.close()
