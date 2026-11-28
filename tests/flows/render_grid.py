"""The clean plate pass's erased grid (tests/flows/README.md): it grows as far as the composite pastes an erase
(logic.gridGrow), at the size of each pass, with no option in the address. The flow reads each clean pass that the page
posts to /prompt, at the preview's size and at full size: its width, and the blocks of 32 px that its grid grows by."""
import json

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"


def grids(bodies):
    """(width, blocks) of each posted clean pass: the width that the slot « width » fills, and the « expand » of the
    GrowMask that the slot grid_grow fills."""
    made = []
    for body in bodies:
        nodes = list((json.loads(body).get("prompt") or {}).values())
        filled = lambda slot, key: [n["inputs"][key] for n in nodes if n.get("_meta", {}).get("slots", {}).get(key) == slot]
        blocks, width = filled("grid_grow", "expand"), filled("width", "width")
        if blocks and width:
            made.append((width[0], blocks[0]))
    return made


def run(browser, port, U):
    errors, bodies = [], []
    page = U.load(browser, port, "?blank=0", errors=errors)
    page.on("request", lambda q: bodies.append(q.post_data) if q.method == "POST" and q.url.endswith("/prompt") else None)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "the mug", [(0.45, 0.55), (0.5, 0.6)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Clean plate pass, full size: done in"), 240000, "the clean plate pass at full size")
    made = sorted(grids(bodies))
    U.check(len({w for w, _ in made}) >= 2 and all(g > 1 for _, g in made) and [g for _, g in made] == sorted(g for _, g in made),
            f"each clean pass grows its grid by more than one block, and a wider pass by at least as many: {made} (width, blocks)")
    U.no_errors(errors, "the erased grid")
    page.close()
