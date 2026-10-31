"""Crash recovery tests never write actual OS proxy settings."""
import io
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from wirebrain import proxy_guard


class ProxyGuardTests(unittest.TestCase):
    def test_eof_restores_only_the_owning_session_and_retries_transient_errors(self):
        with patch.object(proxy_guard, 'reset_proxy', side_effect=[OSError('busy'), None]) as reset, \
             patch.object(proxy_guard.time, 'sleep'):
            proxy_guard.watch('home', 'session-one', io.BytesIO(b''))
            self.assertEqual(reset.call_count, 2)
            reset.assert_called_with('home', expected_session='session-one')

    def test_failed_guard_start_never_changes_proxy(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(proxy_guard.subprocess, 'Popen') as popen, \
             patch.object(proxy_guard, 'reset_proxy') as reset:
            popen.return_value.poll.return_value = 1
            with self.assertRaisesRegex(ValueError, 'system proxy was not changed'):
                proxy_guard.start(directory, 'failed')
            popen.return_value.stdin.close.assert_called_once()
            reset.assert_not_called()

    def test_guard_starts_and_gracefully_finishes_without_a_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            guard = proxy_guard.start(directory, 'smoke')
            self.assertIsNone(guard.poll())
            proxy_guard.finish(guard)
            self.assertEqual(guard.returncode, 0)
            self.assertFalse(list(Path(directory).glob('*.ready')))

    def test_forced_owner_exit_triggers_independent_guard(self):
        # Only the OS restoration is mocked in the guard process. Pipe lifetime,
        # forced owner exit, and recovery dispatch are real subprocess behavior.
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            child = home / 'guard_child.py'
            child.write_text('''
import sys
from pathlib import Path
from wirebrain import proxy_guard
home = Path(sys.argv[1])
def restore(path, expected_session=None):
    (Path(path) / 'restored').write_text(expected_session)
proxy_guard.reset_proxy = restore
(home / 'ready').touch()
proxy_guard.watch(home, 'crashed-session', sys.stdin.buffer)
''', encoding='utf-8')
            owner_script = home / 'owner.py'
            owner_script.write_text('''
import os, subprocess, sys, time
from pathlib import Path
home = Path(sys.argv[1])
flags = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
child = subprocess.Popen([sys.executable, str(home/'guard_child.py'), str(home)], stdin=subprocess.PIPE,
    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags, start_new_session=os.name != 'nt')
(home/'guard-pid').write_text(str(child.pid))
while True: time.sleep(.1)
''', encoding='utf-8')
            env = {**os.environ, 'PYTHONPATH': str(Path(__file__).resolve().parents[1])}
            owner = subprocess.Popen([sys.executable, str(owner_script), str(home)], env=env)
            try:
                deadline = time.monotonic() + 10
                while not (home / 'ready').exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertTrue((home / 'ready').exists(), 'guard never became ready')
                self.assertFalse((home / 'restored').exists(), 'must not restore while owner lives')
                owner.kill()
                owner.wait(timeout=5)
                deadline = time.monotonic() + 10
                while not (home / 'restored').exists() and time.monotonic() < deadline:
                    time.sleep(.05)
                self.assertEqual((home / 'restored').read_text(), 'crashed-session')
            finally:
                if owner.poll() is None:
                    owner.kill()
                    owner.wait(timeout=5)
