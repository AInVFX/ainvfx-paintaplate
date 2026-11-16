"""The check of the Open dialog's typed path (tests/flows/README.md). When ComfyUI runs on this machine, the Files tab
takes the full path of a movie, a frame of a sequence or a folder of frames, and a path in the input folder still
opens. A path that the server cannot read keeps the dialog open, with the server's one line. When ComfyUI runs on
another machine, the field gives way to a note that points to the Upload tab."""

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
READY = "document.querySelector('#status').textContent.startsWith('Ready')"
SHOWN = "document.querySelector('#open').open"


def run(browser, port, U):
    page = U.load(browser, port)
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    U.check(page.is_visible("#path") and page.is_hidden("#path-remote") and "full path" in page.text_content("#path-row"),
            f"on this machine, the Files tab takes a full path: {page.text_content('#path-row').strip()[:60]!r}")
    page.fill("#path", "plates/no_such_plate.mp4"); page.click("#open-go")
    U.check(U.poll(page, lambda: page.text_content("#path-error").strip() != "", 10) and page.evaluate(SHOWN),
            f"a path the server cannot read keeps the dialog open, with the server's one line: {page.text_content('#path-error')!r}")
    page.fill("#path", "plates/desk.mp4")
    U.check(page.text_content("#path-error") == "", "typing clears the line")
    page.click("#open-go")
    page.wait_for_function(OPEN, timeout=60000)
    U.check(not page.evaluate(SHOWN), "a path in the input folder still opens, and the dialog closes")
    page.close()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0&remote=1")
    page.wait_for_function(READY, timeout=60000)
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    U.check(page.is_hidden("#path-row") and page.is_visible("#path-remote") and "Upload tab" in page.text_content("#path-remote"),
            f"when ComfyUI runs on another machine, a note points to the Upload tab: {page.text_content('#path-remote')!r}")
    page.close()
