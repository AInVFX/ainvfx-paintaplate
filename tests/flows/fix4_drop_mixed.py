"""A movie dropped with frames over an open plate opens nothing, and nothing is uploaded: the line says what a drop takes, and
the plate open stays displayed, with no invitation over it (app.openDropped, logic.dropRefusal)."""
import fix4_drops

LINE = "Error: Nothing opened: this drop holds a movie and frames. Drop one movie, or one folder of frames."


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    spec, posted = page.text_content("#spec"), fix4_drops.uploads(page)
    fix4_drops.drop(page, files=[{"name": "take.mp4", "text": "a movie"}, {"name": "shot.0001.png", "png": [320, 176, 1]}])
    U.poll(page, lambda: (page.text_content("#status") or "").startswith("Error"), 10)
    status = page.text_content("#status") or ""
    U.check(status == LINE and not posted, f"a movie with frames: refused before any upload, with what a drop takes: {status!r}, {len(posted)} uploads")
    U.check(fix4_drops.displayed(page, spec), f"the plate open stays displayed, with no invitation over it: {page.text_content('#spec')!r}")
    page.close()
