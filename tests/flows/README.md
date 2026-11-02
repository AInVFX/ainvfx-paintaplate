# Page flows by workstream

`tests/ui_mock.py` runs its own flows, then every `tests/flows/*.py` module in name order, so a workstream adds a file
here instead of editing `ui_mock.py`. A module defines one function:

```python
def run(browser, port, U):
    """U is tests/ui_mock.py itself: U.check, U.WATCH, U.added_line, U.wait_log, U.paint_once, U.open_path and the rest."""
    page = browser.new_page(viewport={"width": 1400, "height": 900}, accept_downloads=True)
    page.goto(f"http://127.0.0.1:{port}/extensions/ainvfx-paintaplate/paintaplate.html?blank=0")
    page.wait_for_function("document.querySelector('#status').textContent.startsWith('Ready')", timeout=60000)
    ...
    page.close()
```

One file per workstream: `viewer.py` (the viewer, its colour and the colour inspector) and `pipeline.py` (renders,
passes, Deliver, bit depth). Each check states what it proves, as the flows of `ui_mock.py` do.
