"""Upscale's pass follows the GPU (logic.upscalePass): the log's « Upscale: … » line says what runs, and each job asks SeedVR2's
chunk node for the same. On a 16 GB card with 128 GB of RAM, a fluid shot of 121 frames upscaled to 2560 runs in one job of
4 even chunks of 37 frames, two neighbours sharing 3 latent frames: a pass there holds 15 latent frames (64.3 latent frames
times megapixels, as a 16 GB GPU measured); on a 96 GB card, desk.mp4 upscaled to 1600 runs in one pass."""


def custom(page, U, px):  # Finish > Upscale on, at a custom long side
    page.click("#finish-btn"); page.click("#finish-upscale")
    U.upscale_custom(page, px)
    page.keyboard.press("Escape")


def said(page, U, port, start):  # the lines « Upscale: … » and the chunk node's values of the jobs posted since `start`
    return ([t for t in U.log_lines(page) if t.startswith("Upscale: ")], [p["chunk"] for p in U.mock_route(port, "/mock/posts")[start:] if p.get("chunk")])


def run(browser, port, U):
    U.mock_route(port, "/mock/card", {"vram": 17.2e9, "ram": 128 * 2 ** 30})  # the shot in one job at 2560 x 1600
    page = U.load(browser, port)
    page.click("#open-btn"); page.click("#open [data-tab=blank]")
    page.select_option("#b-depth", "8"); page.fill("#b-width", "512"); page.fill("#b-height", "320"); page.select_option("#b-fps", "24"); page.fill("#b-frames", "121")
    page.dispatch_event("#b-frames", "input"); page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    page.click('.sw[data-color="#ffffff"]'); U.paint_once(page, "thick white smoke", [(0.3, 0.7), (0.5, 0.5), (0.7, 0.7)])
    page.evaluate(U.WATCH); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Fluid shot, full size: done in"), 240000, "the fluid shot")
    start = len(U.mock_route(port, "/mock/posts"))
    U.settled(page)
    custom(page, U, "2560")
    page.click("#generate")
    U.wait_log(page, U.added_line("Plate, upscaled: done in"), 240000, "Upscale on a 16 GB card")
    lines, chunks = said(page, U, port, start)
    U.check(any("1 job, in 4 chunks of 37 frames, each sharing 12 frames with the next." in t for t in lines) and chunks and all(c == [37, 3] for c in chunks),
            f"16 GB: even chunks of 37 frames sharing 3 latent frames, said and asked for: {lines}, {chunks}")
    page.close()
    U.mock_route(port, "/mock/card", {"vram": 102e9, "ram": 131 * 2 ** 30})
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    start = len(U.mock_route(port, "/mock/posts"))
    custom(page, U, "1600")
    page.click("#generate")
    U.wait_log(page, U.added_line("Plate, upscaled: done in"), 240000, "Upscale on a 96 GB card")
    lines, chunks = said(page, U, port, start)
    U.check(any("1 job, in one pass." in t for t in lines) and chunks and all(c == [49, 3] for c in chunks),
            f"96 GB: the plate's 49 frames in one pass, said and asked for: {lines}, {chunks}")
    page.close()
