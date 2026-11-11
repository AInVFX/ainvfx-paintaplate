"""The codebase workstream's page checks for the log (tests/flows/README.md). The status line says what to do next and the
log records what happened: a hint shows in the status line only, and a fact is written to the log once."""

HINT = "Ready. Open a plate to start."
SAID = """() => { window.__said = []; const line = document.querySelector('#status');
  new MutationObserver(() => window.__said.push(line.textContent)).observe(line, { childList: true, characterData: true, subtree: true }); }"""  # every sentence the status line shows from now on: a later one cannot hide it


def run(browser, port, U):
    page = U.load(browser, port)  # ?blank=0: no plate opens at start
    status, lines = page.text_content("#status"), U.log_lines(page)
    U.check(status == HINT and not any("Open a plate" in t for t in lines) and any(t.startswith("Page ready in") for t in lines),
            f"at start the status line holds the hint, and the log holds what happened, without the hint: {status!r} {lines}")
    U.open_plate(page)
    page.evaluate(SAID)
    name, _ = U.save_scene(page)
    said, lines = page.evaluate("window.__said"), U.log_lines(page)
    fact, then = f"Scene {name} saved on this ComfyUI", "Open plate > Scenes opens it again, or downloads it."
    U.check(f"{fact}. {then}" in said and [t for t in lines if "saved on this ComfyUI" in t] == [fact] and not any(then in t for t in lines),
            f"a save is one fact in the log, and the status line adds what to do next: {said} {[t for t in lines if 'Scene' in t]}")
    page.select_option("#preview-size", index=1)
    page.wait_for_function("window.__said.some((t) => t.startsWith('Previews at'))", timeout=10000)
    fact = next(t for t in page.evaluate("window.__said") if t.startswith("Previews at"))
    U.check(U.log_lines(page).count(fact) == 1, f"a fact with no instruction still shows in the status line and goes to the log, once: {fact!r}")
    page.close()
