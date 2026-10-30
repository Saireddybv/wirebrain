import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from wirebrain.capture import reset_proxy, set_proxy
from wirebrain.store import Store


class CaptureStateTests(unittest.TestCase):
    def test_status_stop_and_stale_heartbeat(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            self.assertFalse(store.capture_state()['running'])
            store.capture_state({'running': True, 'heartbeat': time.time(), 'system_proxy': True})
            self.assertTrue(store.capture_state()['running'])
            store.capture_state({'running': True, 'heartbeat': time.time() - 60})
            self.assertFalse(store.capture_state()['running'])
            self.assertTrue(store.capture_state()['stale'])
            store.capture_stop(True)
            self.assertTrue(store.capture_stop())
            store.capture_stop(False)
            self.assertFalse(store.capture_stop())


@unittest.skipUnless(os.name == 'nt', 'Windows registry lifecycle')
class WindowsProxyTests(unittest.TestCase):
    def test_original_proxy_values_restored_without_touching_real_registry(self):
        import winreg
        original = {'ProxyEnable': [0, winreg.REG_DWORD], 'ProxyServer': ['old.proxy:3128', winreg.REG_SZ]}
        current = dict(original)

        def query(key, name):
            if name not in current: raise FileNotFoundError()
            return tuple(current[name])

        def write(key, name, reserved, kind, value):
            current[name] = [value, kind]

        def delete(key, name):
            if name not in current: raise FileNotFoundError()
            del current[name]

        with tempfile.TemporaryDirectory() as directory, \
             patch.object(winreg, 'OpenKey'), \
             patch.object(winreg, 'QueryValueEx', side_effect=query), \
             patch.object(winreg, 'SetValueEx', side_effect=write), \
             patch.object(winreg, 'DeleteValue', side_effect=delete), \
             patch('wirebrain.capture.notify_windows'):
            set_proxy(directory, 8082)
            self.assertEqual(current['ProxyServer'][0], '127.0.0.1:8082')
            self.assertEqual(current['ProxyEnable'][0], 1)
            with self.assertRaises(ValueError): set_proxy(directory, 8083)
            backup = json.loads((Path(directory) / 'proxy-backup.json').read_text())
            self.assertEqual(backup['ProxyServer'][0], 'old.proxy:3128')
            reset_proxy(directory)
            self.assertEqual(current, original)
            self.assertFalse((Path(directory) / 'proxy-backup.json').exists())
