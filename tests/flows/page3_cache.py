"""A new plate plans its frame cache afresh: a blank plate of 960 x 512, opened after desk.mp4 whose frames a small
budget kept smaller (about 960 x 528), keeps its frames at its own size, and the « Frame cache » line says so."""


def run(browser, port, U):
    page = U.load(browser, port, "?blank=0&cache=100")  # 100 MB, set in the address: desk.mp4's 49 frames fit at 960 x 528, not at their size on screen
    U.open_plate(page)  # desk.mp4, 1280 x 704
    cache = lambda: [t for t in U.log_lines(page) if t.startswith("Frame cache, ")]  # noqa: E731
    U.check(U.poll(page, lambda: any("Plate: " in t and "reduced size" in t for t in cache()), 20), f"desk.mp4's frames kept smaller than its own size: {cache()[-1:]}")
    seen = len(cache())
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "960"); page.fill("#b-height", "512"); page.select_option("#b-fps", "24")
    page.fill("#b-frames", "33"); page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.check(U.poll(page, lambda: len(cache()) > seen and "(960 x 512)" in cache()[-1], 20),
            f"the blank plate of 960 x 512 keeps its frames at its own size: {cache()[seen:]}")
    page.close()
