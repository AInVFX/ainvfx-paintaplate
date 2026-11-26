"""Export's ticks: the dialog shows the elements (What) and the stages (Stage) that the render displayed can give, in the
dialog's words, and opens on the result at its last stage, each time it opens. A paint on a plate of EXR frames offers the
plate, the shot, the layer, the matte and the composite; a fluid shot alone offers its plate alone. The log's download
lines name the files the zip holds, in the Render panel's step names. The Help's Export entry opens with the dialog's line."""

TICKS = """() => [...document.querySelectorAll('#export label.check')].filter((l) => !l.hidden)
  .map((l) => [l.querySelector('input').id, l.querySelector('span').textContent, l.querySelector('small')?.textContent ?? '', l.querySelector('input').checked])"""
WHAT = ("x-plate", "x-shot", "x-layer", "x-matte", "x-composite", "x-graph")
SAID = "() => [...document.querySelectorAll('#log li')].map((li) => li.textContent).filter((t) => t.includes('Download: ')).at(-1) ?? ''"


def painted(page, U, full=False):
    page.click('.tools [data-tool="paint"]')
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.36, 0.5)])
    page.evaluate(U.WATCH); page.keyboard.press("Enter")
    page.wait_for_function(U.DONE.format(n=1), timeout=120000)
    if full:  # the render's full-size steps end before another plate opens, which stops them
        U.wait_log(page, U.added_line(U.REVIEWED), 180000, "the full-size composite")


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page, "paintaplate/hdr_room")  # a plate of EXR frames
    painted(page, U, full=True)
    page.click("#export-btn")
    ticks = page.evaluate(TICKS)
    what, words, on = [t[:2] for t in ticks if t[0] in WHAT], {t[0]: t[2] for t in ticks}, [t[0] for t in ticks if t[3]]
    U.check(what == [["x-plate", "Plate"], ["x-shot", "Shot"], ["x-layer", "Layer"], ["x-matte", "Matte"], ["x-composite", "Composite"], ["x-graph", "ComfyUI graph"]]
            and words["x-plate"].startswith("the plate under the edits") and words["x-shot"] == "the frames the model made" and words["x-layer"] == "the shot as the composite blends it"
            and words["x-matte"] == "where the plate changed, 16-bit PNG frames" and words["x-composite"] == "the result",
            f"a paint on a plate of EXR frames: its five elements and the graph, in the dialog's words: {ticks}")
    U.check("Full size" in [t[1] for t in ticks if t[0] not in WHAT] and on == ["x-composite", "x-full"], f"the dialog opens on the composite at full size: {ticks}")
    page.check("#x-shot")
    page.keyboard.press("Escape")
    page.click("#export-btn")
    U.check(not page.is_checked("#x-shot") and page.is_checked("#x-composite"), "the dialog opens again on the result at its last stage")
    page.keyboard.press("Escape")
    U.open_plate(page)  # plates/desk.mp4, an H.264 movie
    painted(page, U)
    page.click("#export-btn")
    page.evaluate(U.WATCH)
    with page.expect_download(timeout=180000):
        page.click("#x-go")
    U.wait_log(page, U.added_line("Download: "), 60000, "the download's line")
    said = page.evaluate(SAID)
    U.check("Composite, full size." in said and "Matte." not in said and page.text_content("#status").startswith("Download: "),
            f"the log names the files the zip holds, in the Render panel's step names: {said!r}")
    page.click("#open-btn"); page.click("#open [data-tab=blank]")  # a fluid shot alone
    page.fill("#b-frames", "17"); page.dispatch_event("#b-frames", "input")
    page.evaluate(U.WATCH)
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)]); page.keyboard.press("Enter")
    page.wait_for_function("[...document.querySelectorAll('#log li span')].some((e) => /^Render v\\d+: Fluid shot, full size: done in /.test(e.textContent))",
                           timeout=240000)  # the fluid shot, made by its render's steps
    page.click("#export-btn")
    ticks = page.evaluate(TICKS)
    shown, on = [t[0] for t in ticks if t[0] in WHAT], [t[0] for t in ticks if t[3]]
    U.check(shown[:1] == ["x-plate"] and not set(shown) & {"x-shot", "x-layer", "x-matte", "x-composite"} and on == ["x-plate", "x-full"],
            f"a fluid shot alone: its plate alone, at full size: {ticks}")
    page.keyboard.press("Escape")
    U.check(page.text_content("#help-export") == "Export writes the selected files to ComfyUI's output folder, then downloads them as one zip. "
            "Frames keep their format, and a movie gives ProRes 4444 XQ. With SDR to HDR, « HDR » gives half-float EXR frames in ACES2065-1.",
            f"the Help's Export entry: the dialog's line, then the composite's step: {page.text_content('#help-export')!r}")
    U.no_errors(errors, "after the dialogs")
    page.close()
