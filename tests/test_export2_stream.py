"""A zip that streams as it downloads (routes.stream_zip): a file that cannot be read fails the download, since the
response ends before its last chunk, and a zip whose files all read ends whole."""
import asyncio
import io
import os
import shutil
import sys
import unittest
import zipfile

from _env import ROOT

sys.path.insert(0, ROOT)
from aiohttp import ClientPayloadError, web  # noqa: E402
from aiohttp.test_utils import TestClient, TestServer  # noqa: E402
from test_export_source import load_routes, write  # noqa: E402


class StreamedZip(unittest.TestCase):
    def setUp(self):
        self.routes = load_routes()
        out = self.routes.folders.folder_paths.get_output_directory()
        self.run = os.path.join(out, f"paintaplate/streamtest{os.getpid()}/v1")
        self.addCleanup(shutil.rmtree, os.path.dirname(self.run), True)
        self.movie = os.path.join(self.run, "export", "plate.mp4")
        write(self.movie, b"m" * (3 << 20))  # larger than the writer's buffer: its bytes go out before the next file is read

    def fetch(self, files):
        async def go():
            async def handler(request):
                return await self.routes.stream_zip(request, "shot_v1", files, [], "shot")
            app = web.Application()
            app.router.add_get("/zip", handler)
            async with TestClient(TestServer(app)) as client:
                r = await client.get("/zip")
                return await r.read()
        return asyncio.run(go())

    def test_a_file_that_cannot_be_read_fails_the_download(self):
        gone = os.path.join(self.run, "matte", "plate_00001_.png")  # listed, and not there when the zip reads it
        with self.assertLogs("aiohttp.server", "ERROR"), self.assertRaises(ClientPayloadError):
            self.fetch([(self.movie, "shot_composite_full_size.mp4", "export"), (gone, "matte/shot_matte_00001_.png", "matte")])

    def test_a_zip_whose_files_all_read_ends_whole(self):
        body = self.fetch([(self.movie, "shot_composite_full_size.mp4", "export")])
        with zipfile.ZipFile(io.BytesIO(body)) as z:
            self.assertEqual(z.namelist(), ["shot_composite_full_size.mp4"])
            self.assertEqual(z.read("shot_composite_full_size.mp4"), b"m" * (3 << 20))


if __name__ == "__main__":
    unittest.main()
