# Page flows by workstream

`tests/ui_mock.py` runs its own flows, then one flow per `tests/flows/*.py` module, named after its file. So a workstream adds a file here instead of editing `ui_mock.py`: `viewer_<topic>.py`, `pipeline_<topic>.py`. A file whose name starts with `_` is not a flow. A module defines one function:

```python
def run(browser, port, U):
    """U is tests/ui_mock.py itself: U.check, U.WATCH, U.added_line, U.wait_log, U.paint_once, U.open_path and the rest."""
    page = browser.new_page(viewport={"width": 1400, "height": 900}, accept_downloads=True)
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    ...
    page.close()
```

Each flow runs in its own process, against its own mock ComfyUI and its own browser. It starts from a fresh mock (an empty job index, the test plates in `input/`) and shares nothing with another flow. `python tests/ui_mock.py --only viewer` runs one flow; `--list` names them all. The run counts a flow's checks and times it, and a failed check ends that flow only.

The mock runs its jobs 8 times shorter than their simulated time (`--speed`). Wait on what the page shows, not on the clock: `U.wait_log` for a line of the log, `U.until` for a state of the page, `U.poll` for a test written in Python, `U.settled` for the end of every edit and render step, `U.rested` for SAM's answer and the caption after an erase stroke. A long file splits by topic into several, so its parts run side by side.

Today: `viewer.py` (the viewer, its colour and the colour inspector) and `pipeline.py` (renders, passes, Deliver, bit depth). Each check states what it proves, as the flows of `ui_mock.py` do.
