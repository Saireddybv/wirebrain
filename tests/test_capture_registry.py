import json
from importlib.resources import files
import re
import unittest
from wirebrain.webcapture import ALLOW_HOSTS, load_registry

class RegistryTests(unittest.TestCase):
    def test_fail_closed(self):
        raw = files("wirebrain").joinpath("capture_hosts.json").read_text()
        for bad in [raw.replace('"version": 1','"version": true'), raw.replace('chatgpt.com','*.chatgpt.com'), raw.replace('chatgpt.com','new.example'), raw.replace('"version": 1','"version": 1,"version": 1'), '{"version":1}']:
            with self.subTest(bad=bad[:20]), self.assertRaises(ValueError):
                load_registry(bad)
        self.assertIsNone(re.search(ALLOW_HOSTS,'unexpected.chatgpt.com:443'))
        self.assertIsNone(re.search(ALLOW_HOSTS,'chatgpt.com.example:443'))
