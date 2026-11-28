"""The page suite's stand-in ComfyUI keeps a stopped or a failed job's message in its history, as ComfyUI keeps its status
messages: the page reads « execution_interrupted » there as a stop, and an « execution_error » as a failure with its cause."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request

from test_plate_finish import filled

HERE = os.path.dirname(os.path.abspath(__file__))


class StoppedOrFailed(unittest.TestCase):
    def test_the_history_keeps_the_message(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        root = tempfile.mkdtemp(prefix="mock_history_")
        mock = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_comfy.py"), "--port", str(port), "--root", root,
                                 "--speed", "16", "--plate"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = f"http://127.0.0.1:{port}"

        def post(path, body):
            req = urllib.request.Request(url + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            return json.loads(urllib.request.urlopen(req, timeout=10).read() or b"{}")

        def status(pid):
            for _ in range(240):
                st = json.loads(urllib.request.urlopen(f"{url}/history/{pid}", timeout=5).read()).get(pid, {}).get("status")
                if st:
                    return st
                time.sleep(0.25)
            self.fail(f"no history for {pid}")

        values = {"max_frames": 9, "width": 96, "height": 64}
        try:
            for _ in range(120):
                try:
                    urllib.request.urlopen(url + "/system_stats", timeout=2).close()
                    break
                except OSError:
                    time.sleep(0.5)
            post("/mock/hold", {"slot": "path", "seconds": 30})  # the job runs until the interrupt ends it
            held = post("/prompt", {"prompt": filled({"path": "plates/desk.mp4", "prefix": "t/a/f", "video_prefix": "t/a_movie", **values}), "client_id": "t"})["prompt_id"]
            time.sleep(1.5)
            post("/interrupt", {})
            self.assertEqual([m[0] for m in status(held)["messages"]], ["execution_interrupted"])
            failed = post("/prompt", {"prompt": filled({"path": "plates/missing.mp4", "prefix": "t/b/f", "video_prefix": "t/b_movie", **values}), "client_id": "t"})["prompt_id"]
            got = status(failed)
            self.assertEqual([m[0] for m in got["messages"]], ["execution_error"])
            self.assertTrue(got["messages"][0][1]["exception_message"])
        finally:
            mock.terminate()
            mock.wait(10)


if __name__ == "__main__":
    unittest.main()
