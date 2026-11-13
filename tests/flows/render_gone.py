"""ComfyUI stops while a job runs (tests/flows/README.md): the page says so and what to do, where it waited for ever.
The mock ComfyUI stops at /mock/quit, as a ComfyUI that the system stopped for its memory."""
import json
import urllib.request

STATUS = "document.querySelector('#status').textContent"


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1400, "height": 900})
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function(f"{STATUS}.startsWith('Ready')", timeout=60000)
    U.open_path(page, "plates/desk.mp4")
    page.wait_for_function("document.querySelector('#spec').textContent.startsWith('desk') && document.querySelector('#opening').hidden", timeout=60000)
    request = urllib.request.Request(f"http://127.0.0.1:{port}/mock/hold", data=json.dumps({"output": "patch", "seconds": 120}).encode(), headers={"Content-Type": "application/json"})
    urllib.request.urlopen(request, timeout=5).close()
    page.keyboard.press("p")
    U.paint_once(page, "a lantern", [(0.3, 0.5), (0.34, 0.56)])
    page.keyboard.press("Enter")
    page.wait_for_function("document.querySelector('#history li.busy .state')", timeout=60000)
    posted = lambda: any("patch" in p["outputs"] for p in json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/mock/posts", timeout=5)))  # noqa: E731
    for _ in range(120):  # until ComfyUI holds the edit's job: before that, the page is still sending it pictures
        if posted():
            break
        page.wait_for_timeout(500)
    urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/mock/quit", data=b"{}", headers={"Content-Type": "application/json"}), timeout=5).close()
    said = U.until(page, f"/ComfyUI (stopped answering|did not answer)/.test({STATUS}) && !document.querySelector('#history li.busy')", 40000)
    U.check(said, f"ComfyUI stops while an edit is generated: the page says so, and nothing stays busy: {page.text_content('#status')[:170]}")
    page.close()
