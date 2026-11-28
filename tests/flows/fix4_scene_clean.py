"""A Clean scene opened again in a new session posts no job at all: SAM 3.1's object search (snap) saves its masks, and the job
index gives them back with every other job (comfy.INDEXED). A Clean edit renders to its full-size composite and is saved as a
scene; the page loads again, ComfyUI's cache is emptied, as a restart does, and the scene opens with nothing posted."""
OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
MADE = "window.__lines.some((t) => t.includes('came from the job index') || t.startsWith('Error'))"


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, "?blank=0&memory=small", errors=errors)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function(OPEN, timeout=60000)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="erase"]')
    U.paint_once(page, "the mug", [(0.45, 0.55), (0.5, 0.6)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, full size: done in"), 240000, "the full-size composite")
    U.settled(page)
    name, _ = U.save_scene(page)
    page.reload()
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    U.mock_route(port, "/free", {"unload_models": True, "free_memory": True})
    page.evaluate(U.WATCH)
    posted = []
    page.on("request", lambda req: posted.append(req.url) if req.method == "POST" and req.url.endswith("/prompt") else None)
    U.open_scene(page, name)
    page.wait_for_function("window.__lines.some((t) => t.startsWith('Scene opened'))", timeout=120000)
    page.wait_for_function(MADE, timeout=180000)
    U.settled(page)
    snaps = page.evaluate("window.__lines.filter((t) => t.startsWith('snap'))")
    U.check(not posted, f"the Clean scene opened again posts no job, SAM's object search included: {len(posted)} jobs, {snaps[:3]}")
    U.no_errors(errors, "in the Clean scene opened again")
    page.close()
