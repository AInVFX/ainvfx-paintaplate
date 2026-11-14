"""Messages: a failure writes one fact in the log, in red and with no action, and the status line says what stopped, why and
what to do. The mock ComfyUI stops while the edit's job runs (/mock/quit)."""
import json
import re
import urllib.request

STATUS = "document.querySelector('#status').textContent"
LINES = "[...document.querySelectorAll('#log li')].map((li) => [li.className, li.lastChild.textContent])"


def run(browser, port, U):
    mock = lambda path, body: urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/mock/{path}", data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}), timeout=5).close()  # noqa: E731
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function(f"{STATUS}.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    mock("hold", {"output": "patch", "seconds": 120})
    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    posted = lambda: any("patch" in p["outputs"] for p in json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/mock/posts", timeout=5)))  # noqa: E731
    for _ in range(120):  # until ComfyUI holds the edit's job
        if posted():
            break
        page.wait_for_timeout(500)
    mock("quit", {})
    U.until(page, f"{STATUS}.startsWith('Error: ') && !document.querySelector('#history li.busy')", 40000)
    status, lines = page.text_content("#status"), page.evaluate(LINES)
    red = [t for c, t in lines if c == "error"]
    U.check(bool(re.match(r"Error: Edit 1 failed: ComfyUI (stopped answering|did not answer)", status)) and status.endswith(("press Generate.", "Press Generate to try again.")),
            f"the status line says what stopped, why and what to do: {status[:220]}")
    U.check(sum(t.startswith("Error: Edit 1 failed: ComfyUI") for t in red) == 1, f"the log holds one red fact for the edit's failure: {red}")
    U.check(not any(w in t for _, t in lines for w in ("ComfyUI said", "press Generate", "Press Generate", "Start ComfyUI again")),
            f"no log line quotes ComfyUI again or says what to do: {[t for _, t in lines][-5:]}")
    page.close()
