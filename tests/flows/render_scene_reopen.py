"""A saved scene opened again in a new session takes every job from the job index, on the same build. A paint renders to its full-size
composite and is saved as a scene; the page loads again, ComfyUI's cache is emptied (/free, as a restart does), and the
scene opens: nothing is posted to ComfyUI, every job of the edit and of the render comes from the job index, and the scene's line
says so."""

STEPS = ("ingest", "prompt", "edit", "snap", "clean", "cleanup", "shot", "matte", "comp", "review")
ROWS = """(() => { const t = [...document.querySelectorAll('#history li .title')].map((e) => e.textContent);
  return t.join() === '1. Paint' && !document.querySelector('#history li.busy'); })()"""


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, "?blank=0&memory=small", errors=errors)  # a 16 GB card: no model warms up when the page loads
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
    U.mock_route(port, "/free", {"unload_models": True, "free_memory": True})
    page.evaluate(U.WATCH)
    U.open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Scene opened'))", timeout=120000)
    page.wait_for_function(ROWS, timeout=120000)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('review: taken from the job index') || t.startsWith('review '))", timeout=180000)
    U.settled(page)
    grew = U.added(page, STEPS)
    posted = {k: v for k, v in grew.items() if k.endswith("posted") and v}
    U.check(not posted, f"the scene opened again in a new session posts no job: {posted}; from the index: {[k for k, v in grew.items() if k.endswith('before') and v]}")
    said = page.evaluate("window.__lines.filter((t) => t.startsWith('Scene opened'))")
    U.check(any("come from the job index" in t for t in said), f"the scene's line says where its results come from: {said}")
    U.no_errors(errors, "in the scene opened again")
    page.close()
