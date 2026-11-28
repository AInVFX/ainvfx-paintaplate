"""A drop on the page, as the browser makes it, for the drop flows: files, and folders whose files the page reads from their
entries (app.openDropped). A DataTransfer made by a script holds no folder, so a folder is a file of the folder's name, whose
entry the page gets as a folder: DataTransferItem.webkitGetAsEntry answers so for that name, and as the browser does otherwise.
A file is {"name", "text"} for bytes that are not a picture, or {"name", "png": [width, height, n]} for a PNG frame drawn in
the page."""
ENTRIES = """() => { if (window.__folders) return; window.__folders = {};
  const own = DataTransferItem.prototype.webkitGetAsEntry;
  DataTransferItem.prototype.webkitGetAsEntry = function () { const f = this.getAsFile(); return (f && window.__folders[f.name]) || own.call(this); }; }"""
DROP = """async ({ files, folders }) => {
  const png = ([w, h, n]) => { const c = new OffscreenCanvas(w, h), x = c.getContext("2d");
    x.fillStyle = `rgb(${40 + n * 20}, 90, 140)`; x.fillRect(0, 0, w, h); x.fillStyle = "#fff"; x.fillRect(10 + n * 8, 20, 40, 40);
    return c.convertToBlob({ type: "image/png" }); };
  const file = async (f) => new File([f.png ? await png(f.png) : f.text], f.name);
  const dt = new DataTransfer();
  for (const f of files) dt.items.add(await file(f));
  for (const [name, inside] of Object.entries(folders)) {
    const made = await Promise.all(inside.map(file)), entries = made.map((m) => ({ isFile: true, isDirectory: false, name: m.name, file: (got) => got(m) }));
    window.__folders[name] = { isDirectory: true, isFile: false, name, createReader: () => { let given = false;
      return { readEntries: (ok) => setTimeout(() => { ok(given ? [] : entries); given = true; }, 0) }; } };
    dt.items.add(new File([], name));
  }
  document.querySelector("#viewport").dispatchEvent(new DragEvent("drop", { dataTransfer: dt, bubbles: true, cancelable: true }));
}"""


def drop(page, files=(), folders=None):
    """Drops `files` and `folders` ({name: [file, ...]}) on the viewer."""
    page.evaluate(ENTRIES)
    page.evaluate(DROP, {"files": list(files), "folders": folders or {}})


def uploads(page):
    """The uploads the page posts from now on, as a list that grows."""
    posted = []
    page.on("request", lambda req: posted.append(req.url) if req.method == "POST" and "/upload/" in req.url else None)
    return posted


def displayed(page, spec):
    """The plate whose spec line was `spec` is still displayed, with no invitation and no opening screen over it."""
    return page.text_content("#spec") == spec and page.is_hidden("#empty") and page.is_hidden("#opening")
