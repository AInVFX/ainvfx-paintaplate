"""The check of « No, cancel » on an erase that the page's check holds back (tests/flows/README.md). After a
stop, Enter runs the edit that was stopped, then every edit that waited and every edit with no result (queueWaiting). An
erase refused at the question has no result. After « No »: no job of this edit runs, the question does not come back until
the edit changes, and the status line says what to do. Another seed changes the edit: it runs, and the check asks again.
The mock keeps the erase's first pass open (/mock/hold) so that Esc stops it, then answers the next edit jobs with the frame
as it was (/mock/leave), so the object stays in every pass."""
import json
import urllib.request

ASKS = "Edit 1: the object may still be there ("  # the dialog's question
QUESTION = ". Render the shot anyway?"
FACT = "Warning: edit 1, the object may still be there ("  # the log's line, once per question
NAME = "Type its name in the text prompt, then Generate."
YES, NO = ("Yes, render anyway",), ("Cancel", "No, cancel")  # the page's dialog takes the « No » label of its caller
KLEIN = "Edit 1: Klein edit preview"  # one line per pass of the edit
COUNT = "(t) => window.__lines.filter((l) => l.includes(t)).length"
ASKED = """(() => { const d = document.querySelector('#ask');
  return d.open ? [d.querySelector('#ask-text').textContent, d.querySelector('#ask-yes').textContent, d.querySelector('#ask-no').textContent] : null; })()"""
OPEN = "document.querySelector('#ask').open"
ROW = """(() => { const li = document.querySelector('#history li');
  return li ? [li.className, li.dataset.left ?? '', li.querySelector('small').textContent] : null; })()"""


def edit_jobs(port):  # the edit jobs posted to the mock so far: Klein's passes write the patch
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/mock/posts", timeout=5) as r:
        return sum("patch" in json.dumps(p.get("outputs")) for p in json.load(r))


def run(browser, port, U):
    errors = []
    page = U.load(browser, port, errors=errors)
    U.open_plate(page)
    page.evaluate(U.WATCH)
    page.click('.tools [data-tool="erase"]')

    # 1. A stop: Esc while the erase's first pass runs
    U.mock_route(port, "/mock/hold", {"output": "patch", "seconds": 6, "times": 1})
    U.paint_once(page, "", [(0.6, 0.4), (0.62, 0.45)])  # one stroke on the bottle, with no words
    page.keyboard.press("Enter")
    U.wait_log(page, U.added_line(KLEIN), 60000, "the erase's first pass")
    page.keyboard.press("Escape")
    U.wait_log(page, U.added_line("Stopped"), 10000, "the stop")

    # 2. Enter after the stop: the erase runs, keeps its object, and the check asks
    U.mock_route(port, "/mock/leave", {"times": 4})  # two passes, twice: a second run would keep the object too
    page.keyboard.press("Enter")
    page.wait_for_selector("#ask[open]", timeout=90000)
    asked = page.evaluate(ASKED)
    U.check(bool(asked) and asked[0].startswith(ASKS) and asked[0].endswith(QUESTION) and asked[1] in YES and asked[2] in NO,
            f"the check holds the erase back, and the two buttons say what they do ({asked})")
    before = edit_jobs(port)
    page.click("#ask-no")
    again = U.until(page, OPEN, 8000)
    status = page.text_content("#status")
    U.check(not again and page.evaluate(COUNT, FACT) == 1,
            f"after « No » the question does not come back ({page.evaluate(COUNT, FACT)} questions)")
    U.check(edit_jobs(port) == before and page.evaluate(COUNT, KLEIN) == 2,
            f"after « No » no job of the edit runs ({edit_jobs(port) - before} edit jobs, {page.evaluate(COUNT, KLEIN)} passes)")
    U.check(status.startswith(FACT) and status.endswith(NAME), f"the status line says what to do ({status})")

    # 3. Words typed and taken back, then Enter: the edit is unchanged and nothing of it runs. Another seed runs it, and the
    # check asks again
    page.fill("#prompt", "bottle"); page.fill("#prompt", ""); page.evaluate("document.activeElement.blur()")
    page.keyboard.press("Enter")
    row = page.evaluate(ROW)
    U.check(not U.until(page, OPEN, 3000) and edit_jobs(port) == before and row and row[1] == "1" and row[2] == "The object may still be there"
            and page.text_content("#status").endswith(NAME), f"Enter with the edit unchanged runs nothing of it, and its row keeps its mark ({row})")
    page.keyboard.press("Control+Enter")
    page.wait_for_selector("#ask[open]", timeout=90000)
    U.check(page.evaluate(COUNT, FACT) == 2 and edit_jobs(port) > before, "another seed changes the edit: it runs, and the check asks again")
    page.click("#ask-no")
    U.no_errors(errors, "after « No » on an erase that the check held back")
    page.close()
