"""A step reused from another render reaches the zip (tests/flows/README.md): a paint, then another matte strategy, whose
render takes « Shot, full size » from render v1; Export with every row it shows ticked holds every one of them, the shot
among them, and the log's download lines name each row."""
import io
import zipfile

import zip_rows

MENU = "#history li label.matte select"
TICKS = ("#x-plate", "#x-shot", "#x-layer", "#x-matte", "#x-graph")  # every element a paint on a movie plate shows, beside the composite


def run(browser, port, U):
    U.mock_route(port, "/mock/follow", {"auto": "Object and effects"})
    page = U.load(browser, port)
    errors = []
    page.on("pageerror", lambda e: errors.append(f"pageerror: {e}"))
    U.open_plate(page)  # plates/desk.mp4
    page.fill("#prompt", "a red fire"); page.evaluate("document.activeElement.blur()")
    U.stroke(page, [(0.3, 0.5), (0.4, 0.52), (0.5, 0.5)])
    page.select_option("#preview-size", label="Off")
    page.click("#generate")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    U.wait_log(page, "document.querySelector('#render-left').textContent === 'full size ready'", 180000, "full-size composite")
    U.settled(page)
    page.evaluate(U.WATCH)
    page.select_option(MENU, "Whole shot")
    U.wait_log(page, U.added_line("Edit 1: matte Whole shot. The matte and the composite run again."), 10000, "the menu's log line")
    U.wait_log(page, "document.querySelector('#render-left').textContent === 'full size ready'", 180000, "full-size composite again")
    U.settled(page)
    reused = page.evaluate("window.__lines.some((t) => t.includes('Shot, full size: reused from render v1.'))")
    U.check(reused, "render v2 takes « Shot, full size » from render v1, whose folder holds its file")
    page.click("#export-btn")
    shown = [t for t in TICKS if page.is_visible(t)]
    U.check(shown == list(TICKS) and page.is_checked("#x-composite") and page.is_checked("#x-full"), f"a paint on a movie plate shows these ticks, and opens on the composite at full size: {shown}")
    for tick in TICKS:
        page.check(tick)
    page.evaluate(U.WATCH)
    with page.expect_download(timeout=180000) as dl:
        page.click("#x-go")
    names = zipfile.ZipFile(io.BytesIO(open(dl.value.path(), "rb").read())).namelist()
    have = {row: zip_rows.files(names, row) for row in ("composite_full_size", "layer_full_size", "matte", "shot_full_size", "source_plate", "comfyui_graph")}
    U.check(all(have.values()), f"every row ticked is in the zip, the shot that render v1 made among them: {have} {names}")
    U.wait_log(page, "window.__lines.some((t) => t.startsWith('Download: '))", 30000, "the download's line")
    said = "\n".join(page.evaluate("window.__lines"))
    U.check("Shot, full size." in said and "Matte." in said, f"the download's lines name the rows the zip holds: {said!r}")
    U.check(not errors, f"no page errors: {errors}")
    page.close()
