import json
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from wirebrain.cli import DEFAULTS, seed
from wirebrain.gateway import Capture, handler_factory
from wirebrain.mcp import dispatch
from wirebrain.store import Store, redact


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)

    def test_search_redaction_and_delete(self):
        ident = self.store.add('openai', 'test', 'Docker secret=abcdefgh123456', 'Atlas')
        self.store.update(ident, 'Use postgres:5432')
        rows = self.store.list('postgres')
        self.assertEqual(rows[0]['id'], ident)
        self.assertNotIn('abcdefgh123456', self.store.export())
        self.assertEqual(self.store.list('" OR * :'), [])
        day = datetime.now(timezone.utc).date().isoformat()
        self.assertIn('Docker', self.store.reflection(day))
        self.store.delete(ident)
        self.assertEqual(self.store.list('postgres'), [])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM reflections').fetchone()[0], 0)

    def test_demo_is_idempotent(self):
        seed(self.store)
        seed(self.store)
        self.assertEqual(len(self.store.list()), 5)
        self.assertTrue(all(r['demo'] for r in self.store.list()))

    def test_projects_and_export(self):
        ident = self.store.add('anthropic', 'test', 'RLS policy', 'Atlas')
        self.store.update(ident, 'Scope by workspace')
        self.assertIn('Scope by workspace', self.store.projects()[0]['markdown'])
        self.assertEqual(json.loads(self.store.export())[0]['project'], 'Atlas')

    def test_mcp_lifecycle_and_errors(self):
        init = dispatch(self.store, {'id': 1, 'method': 'initialize'})
        self.assertEqual(init['result']['protocolVersion'], '2025-06-18')
        self.assertIsNone(dispatch(self.store, {'method': 'notifications/initialized'}))
        self.assertEqual({t['name'] for t in dispatch(self.store, {'id': 2, 'method': 'tools/list'})['result']['tools']}, {'search_memory','recent_memory','read_memory','context_handoff'})
        self.assertTrue(dispatch(self.store, {'id': 3, 'method': 'tools/call', 'params': {'name': 'bad'}})['result']['isError'])

    def test_mcp_process_stdout_is_json_only(self):
        proc = subprocess.run([sys.executable, '-m', 'wirebrain', '--home', self.tmp.name, 'mcp'],
                              input='{"jsonrpc":"2.0","id":1,"method":"tools/list"}\n',
                              capture_output=True, text=True, check=True)
        self.assertEqual(json.loads(proc.stdout)['id'], 1)
        self.assertEqual(proc.stderr, '')

    def test_redaction_patterns(self):
        for text in ('sk-' + 'x' * 30, 'gsk_' + 'a' * 30, 'password="hunter1234"'):
            self.assertIn('[REDACTED]', redact(text))


class CaptureTests(unittest.TestCase):
    def test_openai_stream(self):
        capture = Capture()
        capture.event({'choices': [{'delta': {'content': 'hello'}}]})
        capture.event({'usage': {'prompt_tokens': 10, 'completion_tokens': 4}})
        self.assertEqual(capture.text, 'hello')
        self.assertEqual(capture.usage['prompt_tokens'], 10)

    def test_anthropic_stream(self):
        capture = Capture()
        capture.event({'type': 'message_start', 'message': {'usage': {'input_tokens': 10}}})
        capture.event({'type': 'content_block_delta', 'delta': {'text': 'hello'}})
        capture.event({'type': 'message_delta', 'usage': {'output_tokens': 4}})
        self.assertEqual(capture.text, 'hello')
        self.assertEqual(capture.usage, {'input_tokens': 10, 'output_tokens': 4})

    def test_responses_stream_and_nonstream(self):
        for streaming in (True, False):
            capture = Capture()
            if streaming: capture.event({'type': 'response.output_text.delta', 'delta': 'hello'})
            response = {'output': [{'content': [{'type': 'output_text', 'text': 'hello'}]}], 'usage': {'input_tokens': 8}}
            capture.event({'type': 'response.completed', 'response': response} if streaming else response)
            self.assertEqual(capture.text, 'hello')
            self.assertEqual(capture.usage['input_tokens'], 8)


class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.received = []
        received = self.received

        class Mock(BaseHTTPRequestHandler):
            def log_message(self, *_): pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                received.append((body, dict(self.headers)))
                if body.get('model') == 'redirect':
                    self.send_response(307)
                    self.send_header('Location', '/credential-leak')
                    self.end_headers()
                    return
                if body.get('model') == 'error':
                    self.send_response(401)
                    self.end_headers()
                    self.wfile.write(b'{"error":"sensitive upstream message"}')
                    return
                stream = body.get('stream', False)
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream' if stream else 'application/json')
                self.end_headers()
                if stream:
                    for event in ({'choices': [{'delta': {'content': 'hello '}}]},
                                  {'choices': [{'delta': {'content': 'world'}}]},
                                  {'usage': {'prompt_tokens': 12, 'completion_tokens': 2}}):
                        self.wfile.write(b'data: ' + json.dumps(event).encode() + b'\n\n')
                        self.wfile.flush()
                    self.wfile.write(b'data: [DONE]\n\n')
                else:
                    self.wfile.write(json.dumps({'choices': [{'message': {'content': 'hello world'}}],
                                                 'usage': {'prompt_tokens': 12, 'completion_tokens': 2}}).encode())

        self.mock = self.server(Mock)
        self.config = dict(DEFAULTS)
        upstream = {'openai': f'http://127.0.0.1:{self.mock.server_port}'}
        self.gateway = self.server(handler_factory(self.store, self.config, upstreams=upstream))
        self.dashboard = self.server(handler_factory(self.store, self.config, True))
        self.base = f'http://127.0.0.1:{self.gateway.server_port}'
        self.ui = f'http://127.0.0.1:{self.dashboard.server_port}'

    def server(self, handler):
        server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def request(self, url, data=None, headers=None, method=None):
        req = urllib.request.Request(url, json.dumps(data).encode() if data is not None else None,
                                     headers or {}, method=method)
        return urllib.request.urlopen(req, timeout=5)

    def test_gateway_to_storage_to_dashboard(self):
        for streaming in (True, False):
            with self.request(self.base + '/openai/v1/chat/completions',
                              {'model': 'test', 'messages': [{'role': 'user', 'content': 'Docker networks'}], 'stream': streaming},
                              {'Authorization': 'Bearer never-save-me', 'X-Wirebrain-Project': 'Atlas'}) as response:
                raw = response.read()
                self.assertIn(b'hello', raw)
            with self.request(self.ui + '/api/feed?q=Docker') as response:
                row = json.load(response)[0]
            self.assertEqual(row['response'], 'hello world')
            self.assertEqual(row['input_tokens'], 12)
            self.assertEqual(row['status'], 'complete')
            self.assertEqual(row['project'], 'Atlas')
        self.assertEqual(self.received[0][1]['Authorization'], 'Bearer never-save-me')
        self.assertNotIn('never-save-me', self.store.export())
        with self.request(self.ui + '/api/ask', {'query': 'networks'}) as response:
            self.assertEqual(len(json.load(response)['sources']), 2)

    def test_wire_redaction_is_opt_in(self):
        secret = 'sk-' + 'x' * 30
        for enabled in (False, True):
            self.config['redact_on_wire'] = enabled
            with self.request(self.base + '/openai/v1/chat/completions', {'model': 'test', 'messages': [{'role': 'user', 'content': secret}]}): pass
            forwarded = self.received[-1][0]['messages'][0]['content']
            self.assertEqual(forwarded, '[REDACTED]' if enabled else secret)
        self.assertNotIn(secret, self.store.export())

    def test_system_prompt_history_and_extended_redaction(self):
        self.config['redact_on_wire']=True
        key='-----BEGIN PRIVATE KEY-----\nprivate-material\n-----END PRIVATE KEY-----'
        payload={'model':'test','system':'State machine policy. '+key,'instructions':'Preserve source links.',
                 'messages':[{'role':'user','content':'Authorization: Bearer abcdefghijklmnop'}]}
        with self.request(self.base+'/openai/v1/chat/completions',payload,{'Authorization':'Bearer provider-auth'}):pass
        forwarded,headers=self.received[-1]
        self.assertNotIn('private-material',forwarded['system'])
        self.assertNotIn('abcdefghijklmnop',forwarded['messages'][0]['content'])
        self.assertEqual(headers['Authorization'],'Bearer provider-auth')
        prompt=self.store.list()[0]['prompt']
        self.assertIn('State machine policy',prompt);self.assertIn('Preserve source links',prompt)
        self.assertNotIn('private-material',prompt)

    def test_upstream_errors_are_recorded(self):
        with self.assertRaises(urllib.error.HTTPError) as exc:
            self.request(self.base + '/openai/v1/chat/completions', {'model': 'error'})
        self.assertEqual(exc.exception.code, 401)
        self.assertNotIn(b'sensitive', exc.exception.read())
        self.assertEqual(self.store.list()[0]['status'], 'error')

    def test_reject_unknown_routes_and_cross_origin(self):
        for url, headers, code in ((self.base + '/evil/v1/messages', {}, 404),
                                   (self.ui + '/api/feed', {'Origin': 'https://evil.example'}, 403),
                                   (self.ui + '/api/feed', {'Host': 'evil.example'}, 403)):
            with self.assertRaises(urllib.error.HTTPError) as exc:
                self.request(url, headers=headers)
            self.assertEqual(exc.exception.code, code)

    def test_upstream_redirect_is_never_followed(self):
        with self.assertRaises(urllib.error.HTTPError) as exc:
            self.request(self.base + '/openai/v1/chat/completions', {'model': 'redirect'},
                         {'Authorization': 'Bearer private'})
        self.assertEqual(exc.exception.code, 307)
        self.assertEqual(len(self.received), 1)

    def test_dashboard_assets_and_delete(self):
        for path in ('/', '/style.css', '/app.js', '/health', '/api/stats', '/api/projects'):
            with self.request(self.ui + path) as response:
                self.assertEqual(response.status, 200)
                self.assertTrue(response.read())
        ident = self.store.add('openai', 'test', 'erase me')
        with self.request(self.ui + '/api/conversations/' + ident, method='DELETE'): pass
        self.assertEqual(self.store.list(), [])

    def test_capture_can_be_stopped_from_dashboard(self):
        self.store.capture_stop(False)
        with self.request(self.ui + '/api/capture/stop', {}) as response:
            self.assertTrue(json.load(response)['ok'])
        self.assertTrue(self.store.capture_stop())

    def test_diary_note_and_saved_memory_roundtrip(self):
        ident=self.store.add('claude','web','A daily memory')
        with self.request(self.ui+'/api/diary/note',{'day':'2026-10-30','body':'My personal thought'}) as response:
            self.assertTrue(json.load(response)['ok'])
        with self.request(self.ui+'/api/journal?day=2026-10-30&offset=330') as response:
            self.assertEqual(json.load(response)['note'],'My personal thought')
        with self.request(self.ui+'/api/entries/'+ident+'/favorite',{'favorite':True}) as response:
            self.assertTrue(json.load(response)['favorite'])
        with self.request(self.ui+'/api/feed?saved=1') as response:
            self.assertEqual(json.load(response)[0]['id'],ident)
        with self.request(self.ui+'/api/diary/export') as response:
            self.assertEqual(json.load(response)['notes'][0]['body'],'My personal thought')


if __name__ == '__main__':
    unittest.main()
