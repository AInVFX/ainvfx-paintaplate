"""A plate closed while its scene opens: nothing of that plate starts after the close, no render and no job (app.closePlate,
app.pipeline). A paint is saved as a scene, the page loads again and the scene opens; the mock holds the render's first
upload, so the close meets the render as its frames upload."""
ROWS = """(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
  return t.join() === '1. Paint' && !document.querySelector('#history li.busy'); })()"""


def run(browser, port, U):
    page = U.load(browser, port, "?blank=0&memory=small")
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.keyboard.press("p")
    page.fill("#prompt", "a red fire"); page.evaluate("document.activeElement.blur()")
    U.stroke(page, [(0.3, 0.6), (0.35, 0.65)])
    page.keyboard.press("Enter")
    page.wait_for_function(ROWS, timeout=120000)
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the full-size composite")
    U.settled(page)
    name, _ = U.save_scene(page)
    page.reload()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    page.evaluate(U.WATCH)
    U.open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Edit 1: done in'))", timeout=120000)
    U.mock_route(port, "/mock/slow", {"seconds": 6, "times": 1})  # the render's first upload waits
    page.wait_for_timeout(800)
    posted = []
    page.on("request", lambda req: posted.append(req.url) if req.method == "POST" and req.url.endswith("/prompt") else None)
    page.click("#close-btn")
    page.wait_for_timeout(9000)  # longer than the held upload
    lines = page.evaluate("window.__lines")
    closed = max((i for i, t in enumerate(lines) if t.startswith("Plate ") and " closed" in t), default=None)
    after = [t[:60] for t in lines[closed + 1:]] if closed is not None else ["(no close line)"]
    U.check(closed is not None and not any(t.startswith("Render v") for t in after) and not posted,
            f"after the close, no render starts and no job is posted: {after[:6]}, {len(posted)} jobs")
    page.close()
