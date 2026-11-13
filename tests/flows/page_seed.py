"""The check of the two options the GPU test puts in the page's address (tests/flows/README.md). ?seed=<n>: every new
edit starts from seed n, so a run makes the same pictures as the run before. ?index=0: the page takes no job from its job
index and writes none to it, so every job runs and is timed, on a machine that ran the same strokes before too. A page
opened without them finds the index as it was."""

OPEN = "document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden"
TAKEN = "taken from the job index"


def run(browser, port, U):
    ingests = lambda: sum("spec" in p["outputs"] for p in U.mock_route(port, "/mock/posts"))  # noqa: E731
    log = lambda page: page.eval_on_selector_all("#log li span", "els => els.map((e) => e.textContent)")  # noqa: E731

    def opened(query, errors=None):
        page = U.load(browser, port, query, errors=errors)
        U.open_path(page, "plates/desk.mp4")
        page.wait_for_function(OPEN, timeout=60000)
        return page

    opened("?blank=0").close()  # the index holds this plate's ingest from here on
    made, errors = ingests(), []
    page = opened("?blank=0&seed=7&index=0", errors)
    lines = log(page)
    U.check(ingests() == made + 1 and not any(TAKEN in t for t in lines),
            "?index=0: the ingest runs again, though the job index holds it")
    U.check(sum("Job index off" in t for t in lines) == 1 and sum("Seed 7 asked for" in t for t in lines) == 1, "the log names each option once")
    page.evaluate(U.WATCH)
    page.keyboard.press("b")
    U.paint_once(page, "a red fire", [(0.3, 0.6), (0.35, 0.65)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Composite, preview took"), 240000, "preview composite of the edit, with no job index")
    lines = page.evaluate("window.__lines")
    U.check(any(t.startswith("Edit 1:") and "seed 7," in t for t in lines) and any(t.startswith("Render v1:") and "seed 7," in t for t in lines),
            "?seed=7: the new edit and its render start from seed 7")
    U.check(not any(TAKEN in t for t in lines), "no job of the edit or of its render comes from the job index")
    U.no_errors(errors, "with ?seed= and ?index=0 in the address")
    page.close()
    posted = ingests()
    page = opened("?blank=0")
    U.check(any(TAKEN in t for t in log(page)) and ingests() == posted, "a page without the options takes the ingest from the job index, as before")
    page.close()
