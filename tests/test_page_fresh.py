"""The page's own files are checked with the server at each load: setup() gives every answer under the page's address
« Cache-Control: no-cache », keeps a rule that an answer already has, and leaves every other address alone."""
import asyncio
import os
import sys
import tempfile
import types
import unittest

from _env import ROOT, require
require("aiohttp")

OUT = tempfile.mkdtemp(prefix="paintaplate_out_")
INPUT = tempfile.mkdtemp(prefix="paintaplate_in_")
TEMP = tempfile.mkdtemp(prefix="paintaplate_tmp_")
sys.path.insert(0, ROOT)
routes = None


def setUpModule():  # routes as another test file may have imported it, with its own stand-in for ComfyUI's module
    global routes
    if "folder_paths" not in sys.modules:  # run alone: ComfyUI's module stands in, as test_routes.py makes it
        sys.modules["folder_paths"] = types.SimpleNamespace(get_output_directory=lambda: OUT, get_input_directory=lambda: INPUT,
                                                            get_temp_directory=lambda: TEMP)
    import routes as module
    routes = module


class FreshPage(unittest.TestCase):
    def test_the_pages_files_are_checked_at_each_load(self):
        from aiohttp import web
        from aiohttp.test_utils import TestClient, TestServer
        folder = tempfile.mkdtemp()
        for name in ("app.mjs", "paintaplate.html", "open.js", "matte.json"):
            with open(os.path.join(folder, name), "w", encoding="utf-8") as f:
                f.write("x")

        @web.middleware
        async def scripts(request, handler):  # as ComfyUI's own rule for its .js files
            response = await handler(request)
            if request.path.endswith(".js"):
                response.headers.setdefault("Cache-Control", "no-store")
            return response

        async def run():
            app = web.Application(middlewares=[scripts])
            routes.setup(types.SimpleNamespace(app=app, routes=web.RouteTableDef()))
            app.add_routes([web.static(routes.PAGE.rstrip("/"), folder), web.static("/elsewhere", folder)])
            got = {}
            async with TestClient(TestServer(app)) as client:
                for path in (routes.PAGE + "app.mjs", routes.PAGE + "paintaplate.html", routes.PAGE + "matte.json", routes.PAGE + "open.js",
                             "/elsewhere/app.mjs"):
                    r = await client.get(path)
                    got[path[len(routes.PAGE):] if path.startswith(routes.PAGE) else path] = (r.status, r.headers.get("Cache-Control"))
                first = await client.get(routes.PAGE + "app.mjs")
                again = await client.get(routes.PAGE + "app.mjs", headers={"If-None-Match": first.headers["ETag"]})
                got["kept"] = (again.status, again.headers.get("Cache-Control"))
            return got

        got = asyncio.run(run())
        self.assertTrue(routes.PAGE.startswith("/extensions/") and routes.PAGE.endswith("/"), routes.PAGE)
        self.assertEqual(got, {"app.mjs": (200, "no-cache"), "paintaplate.html": (200, "no-cache"), "matte.json": (200, "no-cache"),
                               "open.js": (200, "no-store"), "/elsewhere/app.mjs": (200, None), "kept": (304, "no-cache")})


if __name__ == "__main__":
    unittest.main()
