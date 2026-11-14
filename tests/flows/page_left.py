"""The edit workstream's check of an erase that the page's check holds back (tests/flows/README.md). Klein can answer an
erase with the frame as it was: on 12 November 2026 a stroke on a barn, with no words, left the barn in the whole shot, and
nothing said so. After the edit the page compares the first frame with the frame under it inside the object's mask
(logic.eraseCheck). The check can be wrong on a thin or faint object, or on one behind a fence, so the page asks (Adrien,
13 Nov 2026) in its question dialog, with History's row marked as the question opens: tests/ui_live.py ends a GPU case on
that mark. Esc or Cancel renders nothing and leaves what to do next in the status line, and the page goes on: another seed
asks again. « Render anyway », clicked or chosen by Enter, keeps the first frame and renders its shot. One question at a
time: a second erase is held back while the OCIO question is open (/mock/hold keeps its passes running), and its question
waits for that answer. The mock answers the next edit jobs with the frame as it was (/mock/leave)."""

FACT = "Edit 1: the object may still be there ("
QUESTION = ". Render the shot anyway?"
NAME = "Type its name in the prompt bar, then Generate."
ANYWAY = "Edit 1: rendered at your request. The check found the object still there."
ROW = """(() => { const li = document.querySelector('#history li');
  return li ? [li.className, li.dataset.left ?? '', li.querySelector('small').textContent] : null; })()"""
ASKED = """(() => { const d = document.querySelector('#ask');
  return d.open ? [d.querySelector('#ask-text').textContent, d.querySelector('#ask-yes').textContent, document.activeElement?.id ?? ''] : null; })()"""
FILE, LINEAR = "sRGB Encoded Rec.709 (sRGB)", "Linear Rec.709 (sRGB)"  # as tests/flows/page_ocio.py
COUNT = "(t) => window.__lines.filter((l) => l.includes(t)).length"


def held(page, port, U, start, what):  # one erase that the mock leaves as it was: the question opens over a marked row
    U.mock_route(port, "/mock/leave", {"times": 2})  # the erase's quick pass and its full-size pass
    start()
    page.wait_for_selector("#ask[open]", timeout=90000)
    asked, row = page.evaluate(ASKED), page.evaluate(ROW)
    U.check(bool(asked) and asked[0].startswith(FACT) and asked[0].endswith(QUESTION) and asked[1] == "Render anyway"
            and asked[2] == "ask-yes", f"{what}: the page asks, and Enter would choose Render anyway ({asked})")
    U.check(bool(row) and "failed" in row[0] and row[1] == "1" and row[2] == "The object is still there",
            f"{what}: History's row is marked while the question is open ({row})")
    return asked[0]


def cancelled(page, U, asked, facts, what):
    U.settled(page)
    status, lines, row = page.text_content("#status"), page.evaluate("window.__lines"), page.evaluate(ROW)
    U.check(page.is_hidden("#ask") and status == asked[: -len(QUESTION)] + ". " + NAME,
            f"{what}: the question closes, and the status line keeps what to do next ({status})")
    U.check(page.evaluate(COUNT, FACT) == facts and not any(NAME in t for t in lines),
            f"{what}: the log says each held-back erase once, and what to do next stays in the status line")
    U.check(not any(t.startswith("Render v") or ANYWAY in t for t in lines) and "failed" in row[0] and row[1] == "1",
            f"{what}: no shot renders, and History's row keeps its mark ({row})")


def rendered(page, U, n, what, line=ANYWAY, times=None):
    page.wait_for_function(f"(t) => window.__lines.filter((l) => l.includes(t)).length >= {times or n}", arg=line, timeout=60000)
    U.wait_log(page, U.added_line(f"Render v{n}"), 120000, f"render v{n} after Render anyway")
    row = page.evaluate(ROW)
    U.check(page.is_hidden("#ask") and "failed" not in row[0] and row[1] == "",
            f"{what}: the log says why the shot renders, the shot renders, and the mark goes ({row})")


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="erase"]')

    def stroke():  # one stroke on the bottle, with no words
        U.paint_once(page, "", [(0.6, 0.4), (0.62, 0.45)])
        page.keyboard.press("Enter")

    def another():  # Ctrl+Enter: the same edit with another seed
        page.evaluate("document.activeElement.blur()")
        page.keyboard.press("Control+Enter")

    def named():
        page.fill("#prompt", "bottle"); page.evaluate("document.activeElement.blur()")
        page.keyboard.press("Enter")

    asked = held(page, port, U, stroke, "an erase with no words that the check holds back")
    page.keyboard.press("Escape")
    cancelled(page, U, asked, 1, "Esc chooses Cancel")
    asked = held(page, port, U, another, "after Esc, another seed")  # Esc closed the question and stopped nothing
    page.click("#ask-no")
    cancelled(page, U, asked, 2, "Cancel")
    held(page, port, U, named, "the erase once the object is named")
    page.click("#ask-yes")
    rendered(page, U, 1, "Render anyway")
    U.settled(page)
    page.keyboard.press("n")  # New edit: edit 1 keeps its result, so the OCIO question has an edit to regenerate
    U.mock_route(port, "/mock/leave", {"times": 2})
    U.mock_route(port, "/mock/hold", {"output": "patch", "seconds": 6, "times": 2})  # edit 2's two passes last 6 s each
    U.paint_once(page, "bottle", [(0.6, 0.4), (0.62, 0.45)])
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line("Edit 2: Klein full-size pass"), 60000, "edit 2's full-size pass")
    U.menu(page, "OCIO", f"Colour space: {FILE}, from file", "Utility", LINEAR)
    page.wait_for_selector("#ask[open]", timeout=5000)
    ocio = page.text_content("#ask-text")
    U.wait_log(page, U.added_line("Edit 2: the object may still be there ("), 60000, "edit 2 held back")
    page.wait_for_timeout(500)
    asked = page.evaluate(ASKED)
    U.check(ocio.startswith("Changing the ") and bool(asked) and asked[0] == ocio and asked[1] == "Continue",
            f"a question that comes while another is open waits: the OCIO question stays as it was ({asked})")
    page.click("#ask-no")
    page.wait_for_function("() => document.querySelector('#ask').open && document.querySelector('#ask-text').textContent.startsWith('Edit 2: ')", timeout=5000)
    asked = page.evaluate(ASKED)
    U.check(asked[0].startswith("Edit 2: the object may still be there (") and asked[0].endswith(QUESTION) and asked[1] == "Render anyway"
            and asked[2] == "ask-yes", f"once that question is answered, edit 2's question opens, under Enter ({asked})")
    page.keyboard.press("Enter")
    rendered(page, U, 2, "Enter chooses Render anyway", line="Edit 2: rendered at your request.", times=1)
    U.no_errors(errors, "after an erase that the check held back")
    page.close()
