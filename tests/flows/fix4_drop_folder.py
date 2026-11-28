"""A folder dropped over an open plate opens its frames as a sequence: the page reads the folder's files from its entry
(app.openDropped). First, a folder whose frames ComfyUI cannot read: the opening fails at the server, the line says so, and
the plate open comes back displayed, with no invitation over it (app.comeBack)."""
import fix4_drops


def run(browser, port, U):
    page = U.load(browser, port)
    U.open_plate(page)
    spec = page.text_content("#spec")
    fix4_drops.drop(page, folders={"broken": [{"name": f"broken.{i:04d}.png", "text": "not a picture"} for i in range(1, 4)]})
    U.poll(page, lambda: (page.text_content("#status") or "").startswith("Error"), 30)
    status = page.text_content("#status") or ""
    U.check(status.startswith("Error") and fix4_drops.displayed(page, spec),
            f"frames ComfyUI cannot read: the line says so, and the plate open comes back displayed: {status!r}, {page.text_content('#spec')!r}")
    fix4_drops.drop(page, folders={"plates": [{"name": f"shot.{i:04d}.png", "png": [320, 176, i]} for i in range(1, 10)]})
    U.check(U.until(page, "document.querySelector('#frame-total').textContent.trim() === '/ 9' && document.querySelector('#opening').hidden", 60000),
            f"a folder of 9 frames opens as a sequence: {page.text_content('#frame-total')!r}, {page.text_content('#spec')!r}")
    page.close()
