"""Optional real TLS integration; run with the capture extra installed.

Only this test client trusts the temporary CA. No OS certificate or proxy settings
are changed and no external website is contacted.
"""
import importlib.util
import json
import os
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading

from wirebrain.capture import command, terminate_process
from wirebrain.store import Store


@unittest.skipUnless(importlib.util.find_spec('mitmproxy'), 'Install .[capture] for real HTTPS interception test')
class TLSCaptureTests(unittest.TestCase):
    def test_existing_web_protocols_over_real_tls_proxy(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            class Provider(BaseHTTPRequestHandler):
                def log_message(self, *_): pass

                def do_POST(self):
                    self.rfile.read(int(self.headers['Content-Length']))
                    if self.path == '/backend-api/conversation':
                        events = [{'message': {'author': {'role': 'assistant'}, 'content': {'content_type': 'text', 'parts': ['SQLite']}}},
                                  {'p': '/message/content/parts/0', 'o': 'append', 'v': ' uses'},
                                  {'v': ' a local'}, {'v': ' file.'}]
                    else:
                        events = [{'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Docker uses service names.'}}, {'type': 'message_stop'}]
                    self.send_response(200)
                    self.send_header('Content-Type', 'text/event-stream')
                    self.end_headers()
                    for event in events:
                        self.wfile.write(('data: ' + json.dumps(event) + '\n\n').encode())
                        self.wfile.flush()
                    self.wfile.write(b'data: [DONE]\n\n')

            provider = ThreadingHTTPServer(('127.0.0.1', 0), Provider)
            threading.Thread(target=provider.serve_forever, daemon=True).start()
            self.addCleanup(provider.server_close)
            self.addCleanup(provider.shutdown)
            stub = home / 'offline_provider.py'
            stub.write_text('''
def request(flow):
    flow.request.scheme = "http"
    flow.request.host = "127.0.0.1"
    flow.request.port = PORT
'''.replace('PORT', str(provider.server_port)), encoding='utf-8')
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            cmd = command(home, port) + ['--set', 'upstream_cert=false', '-s', str(stub)]
            with (home / 'proxy-test.log').open('wb') as log:
                proc = subprocess.Popen(cmd, env={**os.environ, 'WIREBRAIN_HOME': str(home)}, stdout=log, stderr=log)
                try:
                    cert = home / 'certificates' / 'mitmproxy-ca-cert.pem'
                    deadline = time.monotonic() + 30
                    while time.monotonic() < deadline:
                        if proc.poll() is not None:
                            self.fail('mitmdump failed: ' + (home / 'proxy-test.log').read_text(errors='replace'))
                        try:
                            with socket.create_connection(('127.0.0.1', port), timeout=.2):
                                if cert.exists(): break
                        except OSError: pass
                        time.sleep(.1)
                    else:
                        self.fail('Proxy startup timeout')
                    context = ssl.create_default_context(cafile=str(cert))
                    proxy = f'http://127.0.0.1:{port}'
                    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'https': proxy}), urllib.request.HTTPSHandler(context=context))
                    requests = [
                        ('https://chatgpt.com/backend-api/conversation', {'messages': [{'author': {'role': 'user'}, 'content': {'parts': ['wirebrain-tls-smoke SQLite']}}]}),
                        ('https://claude.ai/api/organizations/test/chat_conversations/test/completion', {'prompt': 'wirebrain-tls-smoke Docker'}),
                    ]
                    for url, body in requests:
                        request = urllib.request.Request(url, json.dumps(body).encode(), {'Content-Type': 'application/json', 'Cookie': 'private-session=not-saved'})
                        with opener.open(request, timeout=10) as response:
                            self.assertIn(b'data: ', response.read())
                    store = Store(home)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        rows = store.list('wirebrain-tls-smoke')
                        if len(rows) == 2 and all(r['status'] == 'complete' for r in rows): break
                        time.sleep(.05)
                    self.assertEqual({r['provider'] for r in rows}, {'chatgpt', 'claude'})
                    self.assertEqual({r['response'] for r in rows}, {'SQLite uses a local file.', 'Docker uses service names.'})
                    self.assertTrue(all(r['status'] == 'complete' for r in rows))
                    self.assertNotIn('private-session', store.export())
                finally:
                    terminate_process(proc)


if __name__ == '__main__':
    unittest.main()
