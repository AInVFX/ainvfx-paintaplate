"""The check of the Open dialog's typed path (tests/flows/README.md). When ComfyUI runs on this machine, the Files tab
takes the full path of a movie, a frame of a sequence or a folder of frames, and a path in the input folder still
opens. The full path of a folder of plates lists it in the dialog, with the machine's folders as its trail. A path that
the server cannot read keeps the dialog open, with the server's one line; so does a full path in a request that a
proxy passed on (its X-Forwarded-For header), with the line that points to the Upload tab. When ComfyUI runs on
another machine, the field gives way to a note that points to the Upload tab."""
import json
import os
import sys

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
READY = "document.querySelector('#status').textContent.startsWith('Ready')"
SHOWN = "document.querySelector('#open').open"
REFUSED = "Full paths open only when ComfyUI runs on this machine. Upload the file instead."


def mock_input():  # the mock ComfyUI's input folder as a full path: ui_mock.py runs each flow with --root <its folder>
    return os.path.join(os.path.abspath(sys.argv[sys.argv.index("--root") + 1]), "input")


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
    folder = os.path.join(mock_input(), "plates")
    movie = os.path.join(folder, "desk.mp4")
    posted = []
    page.on("request", lambda req: posted.append(req.post_data or "") if req.method == "POST" and req.url.endswith("/prompt") else None)
    opened = lambda: sum(t.startswith("Plate desk: opened in") for t in U.log_lines(page))  # noqa: E731
    took = lambda: sum(any(n.get("inputs", {}).get("path") == movie for n in json.loads(b)["prompt"].values()) for b in posted if b)  # noqa: E731
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    page.set_extra_http_headers({"X-Forwarded-For": "203.0.113.7"})  # the mark a proxy adds to a request it passes on
    page.fill("#path", movie); page.click("#open-go")
    U.check(U.poll(page, lambda: page.text_content("#path-error").strip() != "", 10) and page.evaluate(SHOWN) and page.text_content("#path-error") == REFUSED,
            f"a full path in a request that a proxy passed on keeps the dialog open, with its line: {page.text_content('#path-error')!r}")
    page.set_extra_http_headers({})
    before = opened()
    page.fill("#path", movie); page.click("#open-go")
    U.check(U.poll(page, lambda: opened() > before and not page.evaluate(SHOWN), 60) and took() >= 1,
            f"without that mark, the full path of a movie opens it: {opened() - before} opening, {took()} job on {movie}")
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    page.fill("#path", folder); page.click("#open-go")
    listed = U.poll(page, lambda: page.query_selector(f"#browse .item[data-path='{movie}']") is not None, 10)
    trail = page.eval_on_selector_all("#crumbs button", "els => els.map((e) => e.textContent)")
    lit = page.eval_on_selector_all("#open [data-root].on", "els => els.map((e) => e.textContent)")
    U.check(listed and page.evaluate(SHOWN) and trail[0] == "/" and trail[-1] == "plates" and not lit and page.input_value("#path") == "",
            f"the full path of a folder of plates lists it, with the machine's folders as its trail and no root lit: {trail}, lit {lit}")
    before = opened()
    page.dblclick(f"#browse .item[data-path='{movie}']")
    U.check(U.poll(page, lambda: opened() > before and not page.evaluate(SHOWN), 60), "a plate of that list opens by its full path")
    page.close()
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0&remote=1")
    page.wait_for_function(READY, timeout=60000)
    page.click("#open-btn"); page.click("#open [data-tab=files]")
    U.check(page.is_hidden("#path-row") and page.is_visible("#path-remote") and "Upload tab" in page.text_content("#path-remote"),
            f"when ComfyUI runs on another machine, a note points to the Upload tab: {page.text_content('#path-remote')!r}")
    page.close()
