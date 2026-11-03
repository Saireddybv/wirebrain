"""Process capture lifecycle with a simulated redirector; never changes OS state."""
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from wirebrain import capture
from wirebrain.mitm_addon import provider_host
from wirebrain.webcapture import ALLOW_HOSTS


class LocalCaptureTests(unittest.TestCase):
    def test_process_mode_keeps_host_filter_without_listener(self):
        with patch.object(capture, "executable", return_value="mitmdump"):
            args = capture.command(".", 8082, local_capture=True)
        self.assertEqual(args[args.index("--mode")+1], "local:chrome.exe,ChatGPT.exe,claude.exe")
        self.assertEqual(args[args.index("--allow-hosts")+1], ALLOW_HOSTS)
        self.assertNotIn("--listen-port", args)

    def test_local_parser_requires_matching_allowed_tls_and_http_hosts(self):
        flow = Mock()
        flow.metadata = {}
        flow.request.host = '192.0.2.1'
        flow.request.is_http2 = True
        flow.request.authority = 'chatgpt.com:443'
        flow.client_conn.sni = 'chatgpt.com'
        with patch.dict(os.environ, {'WIREBRAIN_LOCAL_READY': 'test'}):
            self.assertEqual(provider_host(flow), 'chatgpt.com')
            self.assertEqual(flow.request.host, '192.0.2.1')
            flow.client_conn.sni = 'other.example'
            self.assertEqual(provider_host(flow), '')
            flow.client_conn.sni = None
            self.assertEqual(provider_host(flow), '')
            flow.client_conn.sni = 'chatgpt.com'
            flow.request.authority = ''
            self.assertEqual(provider_host(flow), '')

    @unittest.skipUnless(os.name == "nt", "Windows prototype")
    def test_pause_and_failed_start_never_set_or_restore_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/"certificates").mkdir()
            (root/"certificates/mitmproxy-ca-cert.cer").touch()
            proc = Mock()
            proc.poll.return_value = None
            def launch(args, **kwargs):
                Path(kwargs["env"]["WIREBRAIN_LOCAL_READY"]).touch()
                return proc
            with patch("wirebrain.driver_guard.guard"), patch.object(capture, "executable", return_value="mitmdump"), patch.object(capture, "prepare_process_trust", return_value=True), patch.object(capture, "set_proxy") as configure, patch.object(capture, "reset_proxy") as restore, patch.object(capture, "remove_ca") as revoke, patch.object(capture, "Store") as store, patch.object(capture, "terminate_process"), patch.object(capture.subprocess, "Popen", side_effect=launch):
                store.return_value.capture_stop.return_value = True
                capture.run(root, install_ca=True, local_capture=True)
                proc.stdin.close.assert_called_once()
                self.assertTrue((root/"local-capture-authorized").exists())
                revoke.assert_not_called()
                proc.poll.return_value = 1
                with self.assertRaisesRegex(ValueError, "exited during startup"):
                    capture.run(root, install_ca=True, local_capture=True)
                revoke.assert_called_once_with(root)
                configure.assert_not_called()
                restore.assert_not_called()
                self.assertFalse(list(root.glob("local-ready-*")))
