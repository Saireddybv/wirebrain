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
from urllib.parse import urlencode
from wirebrain.extra_webcapture import GEMINI_PATH

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
                    raw = None
                    content_type = 'text/event-stream'
                    if self.path == '/backend-api/conversation':
                        events = [{'message': {'author': {'role': 'assistant'}, 'content': {'content_type': 'text', 'parts': ['SQLite']}}},
                                  {'p': '/message/content/parts/0', 'o': 'append', 'v': ' uses'},
                                  {'v': ' a local'}, {'v': ' file.'}]
                    elif self.path == GEMINI_PATH:
                        candidate=['rc_tls',['Gemini uses snapshots.'],None,None,None,None,None,None,[2]]
                        data=[None,['c_tls','r_tls'],None,None,[candidate]]
                        raw=b")]}'\n"+json.dumps([['wrb.fr',None,json.dumps(data)]]).encode()+b'\n'
                        content_type='text/plain'
                    elif self.path == '/rest/app-chat/conversations/new':
                        raw=json.dumps({'result':{'conversation':{'conversationId':'grok-tls'},'response':{'modelResponse':{'message':'Grok uses JSON lines.','responseId':'grok-answer'}}}}).encode()+b'\n'
                        content_type='application/x-ndjson'
                    elif self.path == '/api/graphql/':
                        raw=json.dumps({'data':{'node':{'bot_response_message':{'composed_text':{'content':[{'text':'Meta uses GraphQL snapshots.'}]},'streaming_state':'OVERALL_DONE'}}}}).encode()+b'\n'
                        content_type='application/json'
                    else:
                        events = [{'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Docker uses service names.'}}, {'type': 'message_stop'}]
                    self.send_response(200)
                    self.send_header('Content-Type', content_type)
                    self.end_headers()
                    if raw is not None:
                        self.wfile.write(raw)
                        return
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
                        ('https://gemini.google.com'+GEMINI_PATH, urlencode({'f.req':json.dumps([None,json.dumps([['wirebrain-tls-smoke Gemini'],['en'],['','']])])}).encode()),
                        ('https://grok.com/rest/app-chat/conversations/new', {'message':'wirebrain-tls-smoke Grok'}),
                        ('https://www.meta.ai/api/graphql/', urlencode({'fb_api_req_friendly_name':'useAbraSendMessageMutation','variables':json.dumps({'message':{'sensitive_string_value':'wirebrain-tls-smoke Meta'},'externalConversationId':'meta-tls'})}).encode()),
                    ]
                    for url, body in requests:
                        request = urllib.request.Request(url, body if isinstance(body,bytes) else json.dumps(body).encode(), {'Content-Type': 'application/x-www-form-urlencoded' if isinstance(body,bytes) else 'application/json', 'Cookie': 'private-session=not-saved'})
                        with opener.open(request, timeout=10) as response:
                            self.assertTrue(response.read())
                    store = Store(home)
                    deadline = time.monotonic() + 5
                    while time.monotonic() < deadline:
                        rows = store.list('wirebrain-tls-smoke')
                        if len(rows) == 5 and all(r['status'] == 'complete' for r in rows): break
                        time.sleep(.05)
                    self.assertEqual({r['provider'] for r in rows}, {'chatgpt', 'claude','gemini','grok','meta'})
                    self.assertEqual({r['response'] for r in rows}, {'SQLite uses a local file.', 'Docker uses service names.', 'Gemini uses snapshots.', 'Grok uses JSON lines.', 'Meta uses GraphQL snapshots.'})
                    self.assertTrue(all(r['status'] == 'complete' for r in rows))
                    self.assertNotIn('private-session', store.export())
                finally:
                    terminate_process(proc)


if __name__ == '__main__':
    unittest.main()
