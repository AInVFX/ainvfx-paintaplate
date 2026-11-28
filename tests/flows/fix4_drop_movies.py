"""Two movies dropped over an open plate open nothing, and nothing is uploaded: the line says what a drop takes, one movie or
one folder of frames, and the plate open stays displayed, with no invitation over it (app.openDropped, logic.dropRefusal)."""
import fix4_drops

LINE = "Error: Nothing opened: this drop holds 2 movies. Drop one movie, or one folder of frames."


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    spec, posted = page.text_content("#spec"), fix4_drops.uploads(page)
    fix4_drops.drop(page, files=[{"name": "take_1.mp4", "text": "a movie"}, {"name": "take_2.mp4", "text": "another movie"}])
    U.poll(page, lambda: (page.text_content("#status") or "").startswith("Error"), 10)
    status = page.text_content("#status") or ""
    U.check(status == LINE and not posted, f"two movies: refused before any upload, with what a drop takes: {status!r}, {len(posted)} uploads")
    U.check(fix4_drops.displayed(page, spec), f"the plate open stays displayed, with no invitation over it: {page.text_content('#spec')!r}")
    page.close()
