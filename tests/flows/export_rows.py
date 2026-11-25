"""Export: each row of the dialog says what its file is, in the Render panel's own step names. A plate of EXR frames
offers « Composite, full size » as its own frames and « Composite, full size, as a movie »; a movie plate offers its
composite as a movie, with no second movie; a fluid shot alone offers « Fluid shot ». A hidden row adds nothing to the zip,
even ticked on another plate, and the log's download line names the rows the zip holds. The Help's Export entry opens with
the dialog's own line, then names the composite's step."""

ROWS = """() => [...document.querySelectorAll('#export label.check')].filter((l) => !l.hidden)
  .map((l) => [l.querySelector('input').id, l.querySelector('span').textContent, l.querySelector('small').textContent])"""
STAGES = "() => [...document.querySelectorAll('#stages li')].map((li) => li.textContent).join(' | ')"
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
    stages = page.evaluate(STAGES)
    page.click("#export-btn")
    rows = page.evaluate(ROWS)
    U.check([r[:2] for r in rows] == [["x-export", "Composite, full size"], ["x-review", "Composite, full size, as a movie"], ["x-matte", "Matte"],
                                      ["x-shot", "Shot, full size"], ["x-source", "Source plate"], ["x-graph", "ComfyUI graph"]] and rows[0][2] == "EXR frames" and rows[1][2] == "H.264 MP4",
            f"a plate of EXR frames: the composite as its own frames, and the same composite as a movie: {rows}")
    U.check("Composite, full size" in stages and "Shot, full size" in stages, f"the rows take the Render panel's step names: {stages}")
    page.check("#x-review")
    page.keyboard.press("Escape")
    U.open_plate(page)  # plates/desk.mp4, an H.264 movie
    painted(page, U)
    page.click("#export-btn")
    rows = page.evaluate(ROWS)
    U.check([r[:2] for r in rows] == [["x-export", "Composite, full size"], ["x-matte", "Matte"], ["x-shot", "Shot, full size"], ["x-source", "Source plate"],
                                      ["x-graph", "ComfyUI graph"]]
            and rows[0][2] == "H.264 movie", f"a movie plate: its composite is a movie, with no second one: {rows}")
    U.check(page.is_checked("#x-review"), "the composite's movie keeps its tick from the plate of frames, hidden")
    page.evaluate(U.WATCH)
    with page.expect_download(timeout=180000):
        page.click("#x-go")
    U.wait_log(page, U.added_line("Download: "), 60000, "the download's line")
    said = page.evaluate(SAID)
    U.check("Composite, full size." in said and "Matte." in said and "as a movie" not in said and page.text_content("#status").startswith("Download: "),
            f"the hidden row adds nothing, and the log names the rows the zip holds: {said!r}")
    page.click("#open-btn"); page.click("#open [data-tab=blank]")  # a fluid shot alone
    page.fill("#b-frames", "17"); page.dispatch_event("#b-frames", "input")
    page.evaluate(U.WATCH)
    page.click("#open-go")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('Fluid shot on a blank plate')", timeout=60000)
    U.paint_once(page, "thick white smoke", [(0.4, 0.8), (0.5, 0.7), (0.6, 0.8)]); page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("under the edits: the fluid shot v"), 240000, "the fluid shot")
    page.click("#export-btn")
    rows = page.evaluate(ROWS)
    U.check(rows[0] == ["x-export", "Fluid shot", "ProRes 4444 movie"] and not any(r[0] in ("x-review", "x-matte", "x-shot", "x-source") for r in rows),
            f"a fluid shot alone: one row of its own: {rows}")
    page.keyboard.press("Escape")
    U.check(page.text_content("#help-export") == "Export writes the selected files to ComfyUI's output folder, then downloads them as one zip. "
            "Composite, full size keeps the plate's format. With SDR to HDR, a plate that holds values up to 1.0 only, such as a movie, gives half-float EXR frames.",
            f"the Help's Export entry: the dialog's line, then the composite's step: {page.text_content('#help-export')!r}")
    U.no_errors(errors, "after the three dialogs")
    page.close()
