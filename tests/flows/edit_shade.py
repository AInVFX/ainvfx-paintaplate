"""The edit workstream's check of a relight with a shade stroke (tests/flows/README.md). A dark stroke of the light brush is
a shade: it reaches Klein in words (logic.lightIntent: « The … of the frame falls into deep shadow. »), and the page uploads
no picture of it, so Relight Transfer darkens nothing in the stroke's shape. Darkened where painted, a shade read as a streak
of paint; Klein, told where the shadow falls, darkens that part of the frame as the scene's light would."""


def run(browser, port, U):
    errors, uploads = [], []
    page = U.load(browser, port, errors=errors)
    page.on("request", lambda r: uploads.append(r.post_data_buffer or b"") if "/upload/image" in r.url else None)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="light"]')
    page.click('.swatches [data-color="#ffd890"]')
    U.paint_once(page, "", [(0.05, 0.3), (0.05, 0.7)])  # a warm light along the left edge
    page.click('.swatches [data-color="#000000"]')
    U.paint_once(page, "", [(0.75, 0.6), (0.95, 0.9)])  # a shade at the bottom right
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Render v1"), 120000, "the relight's shot")
    asked = [t for t in page.evaluate("window.__lines") if "relight request: " in t]
    U.check(bool(asked) and "The bottom right of the frame falls into deep shadow." in asked[-1],
            f"the shaded place reaches Klein in words ({asked[-1][:160] if asked else None})")
    U.check(len(uploads) > 0 and not any(b"_shade.png" in u for u in uploads), f"the page uploads no shade ({len(uploads)} uploads)")
    U.no_errors(errors, "after a relight with a shade stroke")
    page.close()
