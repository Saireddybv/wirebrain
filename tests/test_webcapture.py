import json
import tempfile
import unittest
from types import SimpleNamespace
from datetime import datetime, timezone

from wirebrain.mitm_addon import WebCapture
from wirebrain.store import Store
from wirebrain.webcapture import WebStream, generation_request, history_pairs


def sse(*events):
    return b"".join(b"data: " + (json.dumps(e, ensure_ascii=False).encode() if isinstance(e, dict) else e) + b"\r\n\r\n" for e in events)


class WebProtocolTests(unittest.TestCase):
    def test_chatgpt_submitted_prompt_only(self):
        body = {'messages': [{'author': {'role': 'user'}, 'content': {'parts': ['Explain SQLite', {'asset_pointer': 'ignore-image'}]}},
                             {'author': {'role': 'assistant'}, 'content': {'parts': ['Not a prompt']}}], 'model': 'auto'}
        for path in ('/backend-api/conversation', '/backend-api/f/conversation'):
            result = generation_request('chatgpt.com', path, json.dumps(body))
            self.assertEqual(result['prompt'], 'Explain SQLite')
            self.assertEqual(result['provider'], 'chatgpt')
        for host, path in (('evil.chatgpt.com', '/backend-api/conversation'), ('chatgpt.com', '/backend-api/conversations'),
                           ('claude.ai', '/api/account'), ('example.com', '/backend-api/conversation')):
            self.assertIsNone(generation_request(host, path, json.dumps(body)))

    def test_claude_request(self):
        path = '/api/organizations/org/chat_conversations/chat/completion'
        result = generation_request('claude.ai', path, json.dumps({'prompt': 'Explain Docker', 'model': 'claude'}))
        self.assertEqual(result['prompt'], 'Explain Docker')
        for body in ('not json', '[]', '{"prompt":42}', '{}'):
            self.assertIsNone(generation_request('claude.ai', path, body))

    def test_chatgpt_snapshots_arbitrary_utf8_boundaries(self):
        chunks = sse({'message': {'author': {'role': 'assistant'}, 'content': {'content_type': 'text', 'parts': ['Hello']}}},
                     {'message': {'author': {'role': 'assistant'}, 'content': {'content_type': 'text', 'parts': ['Hello 世界']}, 'status': 'finished_successfully'}},
                     b'[DONE]')
        stream = WebStream('chatgpt')
        for byte in chunks: stream.feed(bytes([byte]))
        self.assertEqual(stream.text, 'Hello 世界')
        self.assertEqual(stream.status, 'complete')

    def test_chatgpt_patch_protocol(self):
        stream = WebStream('chatgpt')
        stream.feed(sse({'v': {'message': {'author': {'role': 'assistant'}, 'content': {'content_type': 'text', 'parts': ['Hi']}}}},
                        {'p': '/message/content/parts/0', 'o': 'append', 'v': ' there'},
                        {'o': 'append', 'v': '!'},
                        {'o': 'patch', 'v': [{'p': '/message/status', 'o': 'replace', 'v': 'finished_successfully'}]}))
        self.assertEqual(stream.text, 'Hi there!')
        self.assertEqual(stream.status, 'complete')

    def test_claude_stream_excludes_thinking_and_tool_data(self):
        stream = WebStream('claude')
        stream.feed(sse({'type': 'content_block_start', 'content_block': {'type': 'text', 'text': ''}},
                        {'type': 'content_block_delta', 'delta': {'type': 'thinking_delta', 'thinking': 'private'}},
                        {'type': 'content_block_delta', 'delta': {'type': 'text_delta', 'text': 'Use a network.'}},
                        {'type': 'message_stop'}))
        self.assertEqual(stream.text, 'Use a network.')
        self.assertEqual(stream.status, 'complete')

    def test_chatgpt_inherits_operation_and_path_for_full_reply(self):
        stream = WebStream('chatgpt')
        stream.feed(sse({'v': {'message': {'author': {'role': 'assistant'}, 'content': {'content_type': 'text', 'parts': ['Hello']}}}},
                        {'p': '/message/content/parts/0', 'o': 'append', 'v': ' there'},
                        {'v': '!\n\n'}, {'v': 'Here is the entire answer. '},
                        {'v': 'Including the last sentence.'}, b'[DONE]'))
        self.assertEqual(stream.text, 'Hello there!\n\nHere is the entire answer. Including the last sentence.')
        self.assertEqual(stream.status, 'complete')

    def test_chatgpt_inherits_batch_operation_without_child_context_leak(self):
        stream = WebStream('chatgpt')
        stream.feed(sse({'v': {'message': {'author': {'role': 'assistant'}, 'content': {'content_type': 'text', 'parts': ['A']}}}},
                        {'o': 'patch', 'v': [{'p': '/message/content/parts/0', 'o': 'append', 'v': 'B'}]},
                        {'v': [{'p': '/message/content/parts/0', 'o': 'append', 'v': 'C'}]},
                        {'p': '/message/content/parts/1', 'o': 'add', 'v': 'Second paragraph'},
                        {'o': 'append', 'v': '!'}, {'v': ' Done.'}, b'[DONE]'))
        self.assertEqual(stream.text, 'ABC\nSecond paragraph! Done.')

    def test_claude_legacy_and_partial_errors(self):
        stream = WebStream('claude')
        stream.feed(sse({'completion': 'Hello '}, {'completion': 'world', 'stop_reason': 'stop_sequence'}))
        self.assertEqual(stream.text, 'Hello world')
        self.assertEqual(stream.status, 'complete')
        incomplete = WebStream('claude')
        incomplete.feed(sse({'completion': 'partial'}))
        self.assertEqual(incomplete.status, 'interrupted')
        incomplete.feed(sse({'type': 'error', 'error': {'type': 'overloaded'}}))
        self.assertEqual(incomplete.status, 'error')


class AddonTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.addon = WebCapture(self.store)

    def flow(self, host='chatgpt.com', path='/backend-api/conversation', status=200):
        body = {'messages': [{'author': {'role': 'user'}, 'content': {'parts': ['What is sk-' + 'a' * 24]}}]}
        return SimpleNamespace(request=SimpleNamespace(method='POST', host=host, path=path,
                               content=json.dumps(body).encode(), headers={'authorization': 'Bearer do-not-save', 'cookie': 'session=secret'}),
                               response=SimpleNamespace(headers={'content-type': 'text/event-stream'}, status_code=status, stream=None), metadata={})

    def test_stream_is_unchanged_and_memory_is_redacted(self):
        flow = self.flow()
        self.addon.request(flow)
        self.addon.responseheaders(flow)
        raw = sse({'message': {'author': {'role': 'assistant'}, 'content': {'content_type': 'text', 'parts': ['SQLite is local.']}}}, b'[DONE]')
        self.assertEqual(flow.response.stream(raw), raw)
        self.assertEqual(flow.response.stream(b''), b'')
        self.addon.response(flow)
        row = self.store.list()[0]
        self.assertEqual(row['provider'], 'chatgpt')
        self.assertEqual(row['response'], 'SQLite is local.')
        self.assertEqual(row['status'], 'complete')
        export = self.store.export()
        self.assertNotIn('do-not-save', export)
        self.assertNotIn('session=secret', export)
        self.assertNotIn('a' * 24, export)

    def test_unrelated_domains_never_create_memory(self):
        for host in ('example.com', 'bank.example', 'evil.chatgpt.com'):
            flow = self.flow(host)
            self.addon.request(flow)
            self.addon.responseheaders(flow)
            self.assertIsNone(flow.response.stream)
        self.assertEqual(self.store.list(), [])

    def test_failure_retains_partial_text(self):
        flow = self.flow()
        self.addon.request(flow)
        self.addon.responseheaders(flow)
        flow.response.stream(sse({'message': {'author': {'role': 'assistant'}, 'content': {'content_type': 'text', 'parts': ['Partial']}}}))
        self.addon.error(flow)
        row = self.store.list()[0]
        self.assertEqual(row['status'], 'interrupted')
        self.assertEqual(row['response'], 'Partial')

    def test_unsupported_response_does_not_claim_success(self):
        flow = self.flow()
        flow.response.headers['content-type'] = 'application/json'
        self.addon.request(flow)
        self.addon.responseheaders(flow)
        self.addon.response(flow)
        self.assertEqual(self.store.list()[0]['status'], 'unsupported')


class HistoryRepairTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        self.now = datetime.now(timezone.utc).timestamp()
        self.data = {'current_node': 'answer', 'mapping': {
            'user': {'parent': None, 'message': {'author': {'role': 'user'}, 'create_time': self.now, 'content': {'content_type': 'text', 'parts': ['Hello']}}},
            'answer': {'parent': 'user', 'message': {'author': {'role': 'assistant'}, 'channel': 'final', 'status': 'finished_successfully', 'content': {'content_type': 'text', 'parts': ['Hello, here is the full answer.']}}},
            'alternative': {'parent': 'user', 'message': {'author': {'role': 'assistant'}, 'status': 'finished_successfully', 'content': {'content_type': 'text', 'parts': ['An unrelated alternative.']}}}
        }}

    def test_repair_only_matching_partial_capture_and_search_index(self):
        ident = self.store.add('chatgpt', 'auto', 'Hello')
        self.store.update(ident, 'Hello, here')
        self.assertEqual(self.store.repair_chatgpt_history(self.data), 1)
        self.assertEqual(self.store.list('full')[0]['response'], 'Hello, here is the full answer.')
        self.assertEqual(len(self.store.list()), 1)
        self.assertEqual(self.store.repair_chatgpt_history(self.data), 0)

    def test_history_is_not_imported_without_existing_capture(self):
        self.assertEqual(self.store.repair_chatgpt_history(self.data), 0)
        self.assertEqual(self.store.list(), [])
        self.assertEqual(history_pairs(self.data)[0]['response'], 'Hello, here is the full answer.')

    def test_ambiguous_or_different_reply_is_never_overwritten(self):
        for _ in range(2):
            ident = self.store.add('chatgpt', 'auto', 'Hello')
            self.store.update(ident, 'Hello, here')
        self.assertEqual(self.store.repair_chatgpt_history(self.data), 0)
        for row in self.store.list(): self.store.update(row['id'], 'Different answer')
        self.assertEqual(self.store.repair_chatgpt_history(self.data), 0)

    def test_history_get_repairs_through_addon(self):
        ident = self.store.add('chatgpt', 'auto', 'Hello')
        self.store.update(ident, 'Hello, here')
        flow = SimpleNamespace(request=SimpleNamespace(method='GET', host='chatgpt.com',
            path='/backend-api/conversation/12345678-1234-1234-1234-123456789abc'),
            response=SimpleNamespace(status_code=200, content=json.dumps(self.data).encode()), metadata={})
        addon = WebCapture(self.store)
        addon.request(flow)
        addon.response(flow)
        self.assertEqual(self.store.list()[0]['response'], 'Hello, here is the full answer.')


if __name__ == '__main__':
    unittest.main()
