"""CI's live flow (tests/ui_live.py, flow) against the mock ComfyUI: the flow that CI's live job runs on a real ComfyUI.
Three edits (Paint, Clean, Light), History's eye off and on, the full-size render, then Export. The mock's Klein answers
the erase's two passes with the frame as it was (/mock/leave), so the page's check holds the erase back and asks « Render
anyway »: the flow must answer that question, or the live job waits until its timeout."""
import contextlib
import io
import tempfile

import ui_live


def run(browser, port, U):
    page = browser.new_page(viewport={"width": 1280, "height": 800}, accept_downloads=True)
    page.set_default_timeout(10000)
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    picked, said = ui_live.pick, io.StringIO()

    def pick(p, tool):  # as the flow picks Clean, the mock's next two edit jobs come back as they were
        if tool == "erase":
            U.mock_route(port, "/mock/leave", {"times": 2})
        picked(p, tool)

    ui_live.pick, final, names = pick, "", []
    try:
        with contextlib.redirect_stdout(said):  # the flow's own lines: « edit erase: asked | ... » when it answers the question
            final, names = ui_live.flow(page, f"http://127.0.0.1:{port}", lambda: U.open_path(page, "plates/desk.mp4"),
                                        tempfile.mkdtemp(prefix="paintaplate_live_"), wait_s=60)
    except Exception as exc:  # a wait that ran out: the check says where the flow stopped and what the page shows
        U.check(False, f"the live flow runs to the export: it stopped with {type(exc).__name__}: {str(exc).splitlines()[0][:120]}"
                       f"{U.page_state(page)} | its lines: {said.getvalue()[-400:]}")
    finally:
        ui_live.pick = picked
    U.check("edit erase: asked |" in said.getvalue(), "the check holds the erase back and asks « Render anyway »: the flow "
            "answers it, and the erase's shot renders")
    U.check(final.startswith(ui_live.ENDED), f"the flow ends on the status line that CI's live job reads, the export's or the download's: {final[:80]!r}")
    folders = sorted({n.split("/")[0] for n in names})
    U.check({"export", "matte"} <= set(folders), f"the flow reaches the export: {len(names)} files in the zip ({', '.join(folders)})")
    page.close()
