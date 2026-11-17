"""Save scene: the scenes route answers the full path of the scene's file, which the page names in its confirmation."""
import asyncio
import json
import os
import types
import unittest

from _env import require

require("aiohttp")
import test_routes  # noqa: E402  its folder stub loads routes first, whatever order the tests run in

routes = test_routes.routes


class SceneSaved(unittest.TestCase):
    def test_the_route_answers_the_file_path(self):
        scene = {"format": "paintaplate-scene", "plate": {"path": "plates/shot.mov"}, "edits": []}
        body = json.dumps(scene).encode()

        async def read():
            return body
        answer = json.loads(asyncio.run(routes.scene_post(types.SimpleNamespace(match_info={"name": "shot020"}, read=read))).body)
        path = os.path.join(test_routes.OUT, "paintaplate", "scenes", "shot020.paintaplate.json")
        self.addCleanup(lambda: os.path.exists(path) and os.remove(path))  # the scenes folder is shared with test_routes
        self.assertEqual(answer, {"saved": "shot020", "path": path})
        self.assertTrue(os.path.isabs(answer["path"]))
        with open(answer["path"], encoding="utf-8") as fh:
            self.assertEqual(json.load(fh), scene)


if __name__ == "__main__":
    unittest.main()
