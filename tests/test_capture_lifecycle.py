import json
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from wirebrain.capture import reset_proxy, set_proxy, recover_proxy, setup_needed, start_background
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


class SetupNeededTests(unittest.TestCase):
    def test_unconfigured_home_reports_setup_and_refuses_resume(self):
        with tempfile.TemporaryDirectory() as directory, patch('wirebrain.capture.sys.platform', 'darwin'), patch('wirebrain.capture.os.name', 'posix'):
            self.assertIn('one-time device setup', setup_needed(directory))
            with self.assertRaises(ValueError):
                start_background(directory)


class ResumeAfterPauseTests(unittest.TestCase):
    def test_resume_while_pause_is_in_flight_waits_then_restarts(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(directory)
            store.capture_state({'running': True, 'heartbeat': time.time()})
            store.capture_stop(True)
            def recorder_exits(_seconds):
                store.capture_state({'running': False, 'heartbeat': time.time()})
            with patch('wirebrain.capture.setup_needed', return_value=None), patch('wirebrain.capture.executable'), \
                 patch('wirebrain.capture.time.sleep', side_effect=recorder_exits), patch('wirebrain.capture.subprocess.Popen') as popen:
                popen.return_value.wait.return_value = 0
                self.assertEqual(start_background(directory).get('starting'), True)
                popen.assert_called_once()

    def test_resume_while_running_is_a_noop(self):
        with tempfile.TemporaryDirectory() as directory:
            Store(directory).capture_state({'running': True, 'heartbeat': time.time()})
            with patch('wirebrain.capture.subprocess.Popen') as popen:
                self.assertEqual(start_background(directory), {'ok': True})
                popen.assert_not_called()


class RecoveryTests(unittest.TestCase):
    def test_abandoned_proxy_restored_only_when_listener_refuses(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'proxy-backup.json').write_text('{}')
            with patch('wirebrain.capture.socket.create_connection', side_effect=ConnectionRefusedError), patch('wirebrain.capture.reset_proxy') as reset:
                recover_proxy(directory)
                reset.assert_called_once_with(directory)

    def test_live_or_uncertain_listener_never_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            (Path(directory)/'proxy-backup.json').write_text('{}')
            with patch('wirebrain.capture.socket.create_connection') as connection, patch('wirebrain.capture.reset_proxy') as reset:
                with self.assertRaisesRegex(ValueError,'still listening'): recover_proxy(directory)
                connection.return_value.close.assert_called_once()
                reset.assert_not_called()
            with patch('wirebrain.capture.socket.create_connection', side_effect=TimeoutError), patch('wirebrain.capture.reset_proxy') as reset:
                with self.assertRaisesRegex(ValueError,'Could not verify'): recover_proxy(directory)
                reset.assert_not_called()


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
             patch('wirebrain.capture.notify_windows'), \
             patch('wirebrain.capture.connection_options', return_value=9) as options:
            set_proxy(directory, 8082)
            self.assertEqual(current['ProxyServer'][0], '127.0.0.1:8082')
            self.assertEqual(current['ProxyEnable'][0], 1)
            with self.assertRaises(ValueError): set_proxy(directory, 8083)
            backup = json.loads((Path(directory) / 'proxy-backup.json').read_text())
            self.assertEqual(backup['ProxyServer'][0], 'old.proxy:3128')
            self.assertEqual(backup['_connection_flags'], 9)
            options.assert_any_call(3, '127.0.0.1:8082', 'localhost;127.*;<local>')
            reset_proxy(directory)
            options.assert_any_call(9, 'old.proxy:3128', '')
            self.assertEqual(current, original)
            self.assertFalse((Path(directory) / 'proxy-backup.json').exists())
