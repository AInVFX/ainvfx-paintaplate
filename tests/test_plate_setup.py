"""The pod's setup clones ComfyUI at its pin one commit deep, from the pin's tag, before it tries a full clone."""
import os
import re
import subprocess
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(*parts):
    with open(os.path.join(ROOT, *parts), encoding="utf-8") as f:
        return f.read()


class ShallowClone(unittest.TestCase):
    def test_the_setup_clones_the_pins_tag_one_commit_deep_first_and_parses(self):
        setup = read("tools", "pod_setup.sh")
        shallow = setup.index('clone -q --depth 1 --branch "$COMFY_TAG"')
        self.assertLess(shallow, setup.index('clone https://github.com/comfyanonymous/ComfyUI "$W/ComfyUI"\ncd'))
        self.assertEqual(subprocess.run(["bash", "-n", os.path.join(ROOT, "tools", "pod_setup.sh")]).returncode, 0)

    @unittest.skipUnless(os.path.isdir(os.path.join(os.environ.get("COMFYUI_DIR", ""), ".git")), "no ComfyUI clone in COMFYUI_DIR")
    def test_the_tag_is_at_the_pin(self):
        pins = dict(re.findall(r"^(COMFY_\w+)=(\S+)", read("tools", "pins.sh"), re.M))
        head = subprocess.run(["git", "-C", os.environ["COMFYUI_DIR"], "rev-parse", f"{pins['COMFY_TAG']}^{{commit}}"],
                              capture_output=True, text=True).stdout
        self.assertTrue(head.startswith(pins["COMFY_PIN"]), (pins, head))


if __name__ == "__main__":
    unittest.main()
