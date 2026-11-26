"""Finish > Upscale in a scene opened again, and on its plate opened again with no edit: each opening of a plate has its own folder,
and the job index gives the windows back from the opening that made them. The steps read the windows where their own job wrote
them: the scene's three steps are made again with no Upscale window posted, the player shows the upscaled composite, and Export
zips the upscaled set from this opening's folder. The plate alone then takes the same windows for « Plate, upscaled ». It asks
for 1600 x 880, a size above the plate's 1280 x 704 that the mock holds in a small machine's memory, in three windows of 21
frames: the first window says where a part's windows are, and the others are written beside it."""
import zipfile
import zip_rows  # noqa: E402

ROWS = "els => els.map((e) => [e.querySelector('.name').textContent, e.querySelector('.time').textContent, e.className])"
UP = ["Plate, upscaled", "Layer, upscaled", "Composite, upscaled"]
CANVAS = "() => { const c = document.querySelector('canvas[data-picture]'); return [c.width, c.height]; }"
RESTS = "['full size ready', 'finish ready'].includes(document.querySelector('#render-left').textContent) || document.querySelector('#status').textContent.startsWith('Error')"


def run(browser, port, U):
    errors = []
    card = {"vram": 17.2e9, "ram": 24 * 2 ** 30}  # a 16 GB GPU with 24 GB of RAM: windows of 21 frames
    U.mock_route(port, "/mock/card", card)
    page = U.load(browser, port, "?blank=0&memory=small", errors=errors)  # a 16 GB GPU: no model warms up when the page loads
    U.open_plate(page)
    page.evaluate(U.WATCH)
    rows = lambda: page.eval_on_selector_all("#stages li", ROWS)  # noqa: E731
    ups = lambda: [r for r in rows() if r[0] in UP]  # noqa: E731
    made = lambda: len(ups()) == 3 and all("done" in r[2].split() for r in ups())  # noqa: E731
    canvas = lambda: page.evaluate(CANVAS)  # noqa: E731
    status = lambda: page.text_content("#status") or ""  # noqa: E731
    bad = lambda: [t for t in page.evaluate("window.__lines") if t.startswith("Error") or ": failed after" in t]  # noqa: E731

    def upscale_at(px):  # Finish > Upscale on, at a size typed in Custom…
        page.click("#finish-btn")
        if not page.is_checked("#finish-upscale"):
            page.click("#finish-upscale")
        page.select_option("#finish-upscale-size", "custom"); page.wait_for_selector("#ask-field", state="visible", timeout=10000)
        page.fill("#ask-field", px); page.keyboard.press("Enter"); page.wait_for_selector("#ask", state="hidden", timeout=10000)
        page.click("#finish-btn")

    upscale_at("1600")
    page.keyboard.press("p"); U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, upscaled: done in"), 240000, "Upscale's steps")
    page.wait_for_function(RESTS, timeout=60000)
    U.settled(page)
    said = [t for t in U.log_lines(page) if t.startswith("Upscale: ")]
    U.check(any("3 windows of 21 frames" in t for t in said), f"the plate's 49 frames make three windows: {said}")
    name, _ = U.save_scene(page)
    page.reload()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    U.mock_route(port, "/free", {"unload_models": True, "free_memory": True})
    U.mock_route(port, "/mock/card", card)
    page.evaluate(U.WATCH)
    U.open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Scene opened'))", timeout=120000)
    page.wait_for_function(RESTS, timeout=200000)
    U.settled(page)
    grew = U.added(page, ("upscale", "upscale_export", "export"))
    U.poll(page, lambda: made() and canvas() == [1600, 880], 3)
    U.check(made() and canvas() == [1600, 880] and status().startswith("Composite, upscaled: ready, in the viewer.") and not bad() and not grew.get("upscale: posted"),
            f"the scene opened again makes Upscale's steps from the windows the job index gives back, with none posted: {ups()}, canvas {canvas()}, {status()!r}, {grew}, {bad()}")
    page.click("#export-btn"); page.check("#x-matte")  # beside the composite, upscaled, which the dialog opens on
    with page.expect_download(timeout=240000) as dl:
        page.click("#x-go")
    parts = {zip_rows.row_of(n) for n in zipfile.ZipFile(dl.value.path()).namelist() if zip_rows.row_of(n).endswith("_upscaled")}
    U.check(parts == {"composite_upscaled", "matte_upscaled"} and not bad(), f"Export zips the upscaled set of the scene opened again: {sorted(parts)}, {bad()}")
    U.open_plate(page)  # the same plate, opened again with no edit: another folder once more
    page.evaluate(U.WATCH)
    upscale_at("1600")
    page.click("#generate")
    page.wait_for_function("window.__lines.some((t) => t.includes('Plate, upscaled: done in')) || document.querySelector('#status').textContent.startsWith('Error')", timeout=200000)
    U.settled(page)
    grew = U.added(page, ("upscale", "upscale_export"))
    U.poll(page, lambda: canvas() == [1600, 880], 3)
    U.check(canvas() == [1600, 880] and status().startswith("Plate, upscaled: ready, in the viewer.") and not bad() and not grew.get("upscale: posted"),
            f"the plate alone takes the same windows for its step, with none posted: canvas {canvas()}, {status()!r}, {grew}, {bad()}")
    U.no_errors(errors, "in the scene and the plate opened again")
    page.close()
