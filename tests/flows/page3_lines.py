"""The memory line and an upscaled plate's name. On a 16 GB GPU, opening a plate loads no model, so no memory is freed after it and no
line says so; a free after a job that loaded models reads « Memory freed before the shot. » with its reason below. An
upscaled plate made at another size than the one now asked for is named with the size of the picture displayed, until
the new size is made."""

CARD = {"vram": 16e9, "ram": 64e9, "ram_free": 60e9}  # a 16 GB GPU: the small profile, which holds one family of models at a time


def run(browser, port, U):
    U.mock_route(port, "/mock/card", CARD)  # before the page loads
    page = U.load(browser, port)
    page.evaluate(U.WATCH)
    U.open_plate(page)
    page.keyboard.press("p")
    U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Memory freed before the shot"), 120000, "the free before the shot")
    freed = [t for t in page.evaluate("window.__lines") if t.startswith("Memory freed before")]
    U.check(freed and freed[0].startswith("Memory freed before the shot.") and "This GPU holds one model family at a time." in freed[0],
            f"no free after opening the plate, which loads no model; the first free comes after the edit's models: {freed}")
    U.settled(page)
    page.close()

    U.mock_route(port, "/mock/card", {"vram": 96e9, "ram": 256e9, "ram_free": 200e9})
    page = U.load(browser, port)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); page.click("#finish-upscale")
    U.upscale_custom(page, "1600"); page.keyboard.press("Escape")
    page.click("#generate")
    U.wait_log(page, U.added_line("Plate, upscaled: done in"), 240000, "the plate's upscaled step")
    page.keyboard.press("F6")  # the wipe names the picture displayed on its right side
    right = lambda: page.text_content("#wipe .label.right")  # noqa: E731
    U.check(U.poll(page, lambda: right() == "Plate, upscaled", 5), f"made at the size asked for: {right()!r}")
    page.evaluate(U.WATCH)
    page.click("#finish-btn"); U.upscale_custom(page, "1920"); page.keyboard.press("Escape")
    U.check(U.poll(page, lambda: right() == "Plate, upscaled to 1600 x 880", 5),
            f"another size asked for: the picture displayed is named with its own size: {right()!r}")
    if not U.until(page, U.added_line("Plate, upscaled: about"), 5000):
        page.click("#generate")
    U.wait_log(page, U.added_line("Plate, upscaled: done in"), 240000, "the new size")
    U.check(U.poll(page, lambda: right() == "Plate, upscaled", 5), f"the new size made: {right()!r}")
    page.close()
