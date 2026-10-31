import base64
import gzip
import json
import tempfile
import time
import unittest
from types import SimpleNamespace

from wirebrain.claude_rpc import ClaudeTimeline, PERFORM_ACTION, STREAM_TIMELINE, prompt_request, timeline_conversation
from wirebrain.mitm_addon import WebCapture
from wirebrain.store import Store
from wirebrain.webcapture import generation_request

# Request bodies recorded from claude.ai (a short test prompt, no credentials).
PERFORM_ACTION_BODY = base64.b64decode(
    'CokBChkKFXNlc3NfN2Q5ZWMzZWI1NzQ5M2FhNBADEiQzOGQ1YjdmYy1lZmNhLTRhMDctODU0ZS0xY2M2OTdmYTVjOGMYAzoYCAEQARgBMAFAAVABsAEBwAEB4AEBiAIBcgVl'
    'bi1VU3ogPKBVN9/t13a7QKfCPgPzMyMtlcbQskr+wVw2feZVBaiYAQESrQEKJDRkZGMxMWY5LTY5MDctNDg2Mi1hZWVhLWMyODE0ZmMwNGMzMhIkNWIxZTgzZTMtYzQ5MC00'
    'Yjc2LTljYzUtMWUyNmVmMDIzNDNjGkZUaGlyZCBXaXJlYnJhaW4gdGVzdDogcmVwbHkgd2l0aCBleGFjdGx5IHRoZSB3b3JkcyBwYW5nLXdpcmVicmFpbi05MDQ2Yg1Bc2lh'
    'L0NhbGN1dHRhagVlbi1VU5ABAQ==')
STREAM_TIMELINE_BODY = base64.b64decode(
    'AAAAAGMKJDU1OTNiYjJhLWVjNzctNDZmYy1hZmRiLThmODcxZDU2ZjYzZRIRCg8xNzkzNDQzNTgzNzEwLTAYASIOMAGwAQHAAQHgAQGIAgEqBWVuLVVTMAFCDUFzaWEvQ2Fs'
    'Y3V0dGE=')
CONVERSATION = '38d5b7fc-efca-4a07-854e-1cc697fa5c8c'
NOW_MS = int(time.time() * 1000)


def varint(n):
    out = b''
    while True:
        byte = n & 127
        n >>= 7
        out += bytes([byte | (128 if n else 0)])
        if not n: return out


def field(number, value):
    if isinstance(value, int): return varint(number << 3) + varint(value)
    value = value.encode() if isinstance(value, str) else value
    return varint(number << 3 | 2) + varint(len(value)) + value


def envelope(payload, flags=0):
    return bytes([flags]) + len(payload).to_bytes(4, 'big') + payload


def event(stamp, *inner):
    return envelope(field(1, field(10, field(1, f'{stamp}-0')) + field(11, 2) + b''.join(inner)))


def block(ident, text=None, kind=2, final=False, group='dgrp_1'):
    body = field(1, ident) + field(2, group)
    if text is not None: body += field(9, text)
    body += field(10, field(1, kind))
    if final: body += field(24, 1)
    return field(1, field(5, body))


def delta(ident, text):
    return field(2, field(1, ident) + field(2, text))


def group_start(message_uuid, group='dgrp_1'):
    return field(1, field(4, field(1, group) + field(2, message_uuid)))


class PromptTests(unittest.TestCase):
    def test_real_perform_action_body_is_a_prompt(self):
        capture = prompt_request(PERFORM_ACTION_BODY)
        self.assertEqual(capture['prompt'], 'Third Wirebrain test: reply with exactly the words pang-wirebrain-9046')
        self.assertEqual(capture['conversation_id'], CONVERSATION)
        self.assertEqual(capture['message_id'], '4ddc11f9-6907-4862-aeea-c2814fc04c32')
        self.assertEqual(capture['parent_message_id'], '5b1e83e3-c490-4b76-9cc5-1e26ef02343c')
        self.assertTrue(capture['reply_on_stream'])
        routed = generation_request('claude.ai', PERFORM_ACTION, PERFORM_ACTION_BODY)
        self.assertEqual(routed['prompt'], capture['prompt'])

    def test_users_own_message_in_the_stream_is_not_the_reply(self):
        stream = ClaudeTimeline(NOW_MS, '4ddc11f9-6907-4862-aeea-c2814fc04c32')
        stream.feed(event(NOW_MS, group_start('4ddc11f9-6907-4862-aeea-c2814fc04c32', 'dgrp_human'), block('h1', 'my own prompt', group='dgrp_human')) +
                    event(NOW_MS, group_start('assistant-1'), block('b1', 'real reply')) + envelope(b'{}', 2))
        self.assertEqual((stream.text, stream.response_message_id), ('real reply', 'assistant-1'))
        late = ClaudeTimeline()          # stream opened first; the prompt id arrives when it is bound
        late.bind(NOW_MS, '4ddc11f9-6907-4862-aeea-c2814fc04c32')
        late.feed(event(NOW_MS, group_start('4ddc11f9-6907-4862-aeea-c2814fc04c32', 'dgrp_human'), block('h1', 'my own prompt', group='dgrp_human')) + envelope(b'{}', 2))
        self.assertEqual(late.text, '')

    def test_actions_without_a_prompt_and_garbage_are_ignored(self):
        self.assertIsNone(prompt_request(base64.b64decode('CkkSJDM4ZDViN2ZjLWVmY2EtNGEwNy04NTRlLTFjYzY5N2ZhNWM4YxgDOhgIARABGAEwAUABUAGwAQE=')))
        self.assertIsNone(prompt_request(b'\xff\xff\xff'))
        self.assertIsNone(prompt_request(b''))

    def test_timeline_request_names_its_conversation(self):
        self.assertEqual(timeline_conversation(STREAM_TIMELINE_BODY), '5593bb2a-ec77-46fc-afdb-8f871d56f63e')
        self.assertEqual(timeline_conversation(b'junk'), '')


class TimelineTests(unittest.TestCase):
    def test_streams_start_deltas_and_final_text_across_byte_boundaries(self):
        raw = (event(NOW_MS, group_start('assistant-1'), block('b1', 'zing')) + event(NOW_MS + 5, delta('b1', 'irebrain-')) +
               event(NOW_MS + 9, delta('b1', '2208')) + event(NOW_MS + 10, block('b1', 'zing-wirebrain-2208', final=True)) +
               envelope(b'{}', 2))
        stream = ClaudeTimeline(NOW_MS)
        for byte in raw: stream.feed(bytes([byte]))
        self.assertEqual(stream.text, 'zing-wirebrain-2208')
        self.assertEqual((stream.status, stream.response_message_id), ('complete', 'assistant-1'))

    def test_partial_stream_is_interrupted_and_end_error_is_an_error(self):
        stream = ClaudeTimeline(NOW_MS)
        stream.feed(event(NOW_MS, block('b1', 'half')))
        self.assertEqual((stream.text, stream.status), ('half', 'interrupted'))
        stream.feed(envelope(b'{"error":{"code":"unavailable"}}', 2))
        self.assertEqual(stream.status, 'error')

    def test_thinking_float_updates_and_old_history_are_not_saved(self):
        stream = ClaudeTimeline(NOW_MS)
        stream.feed(event(NOW_MS, block('think', 'secret reasoning', kind=5)) + event(NOW_MS, block('b1', 'answer')) +
                    event(NOW_MS, field(2, field(1, 'b1') + field(2, b'\x2d\x00\x00\x80\x3f'))) +
                    event(NOW_MS - 3_600_000, block('old', 'replayed earlier reply')) + envelope(b'{}', 2))
        self.assertEqual(stream.text, 'answer')

    def test_gzip_envelope_is_read_and_large_message_is_bounded(self):
        stream = ClaudeTimeline(NOW_MS)
        plain = event(NOW_MS, block('b1', 'compressed reply'))
        stream.feed(envelope(gzip.compress(plain[5:]), 1) + envelope(b'{}', 2))
        self.assertEqual(stream.text, 'compressed reply')
        bounded = ClaudeTimeline(NOW_MS)
        bounded.feed(b'\x00' + (3 * 1024 * 1024).to_bytes(4, 'big'))
        self.assertEqual(bounded.status, 'truncated')


class AddonTests(unittest.TestCase):
    def flow(self, path, body, content_type, status=200):
        return SimpleNamespace(request=SimpleNamespace(host='claude.ai', path=path, method='POST', content=body, headers={'cookie': 'secret-cookie'}),
                               response=SimpleNamespace(status_code=status, headers={'content-type': content_type}, stream=None), metadata={})

    def run_flow(self, addon, flow, raw=b''):
        addon.request(flow)
        addon.responseheaders(flow)
        if flow.response.stream: flow.response.stream(raw), flow.response.stream(b'')
        addon.response(flow)

    def test_prompt_and_reply_from_separate_calls_land_in_one_exchange(self):
        with tempfile.TemporaryDirectory() as directory:
            store, addon = Store(directory), WebCapture(Store(directory))
            self.run_flow(addon, self.flow(PERFORM_ACTION, PERFORM_ACTION_BODY, 'application/proto'))
            row = store.list()[0]
            self.assertEqual((row['provider'], row['status']), ('claude', 'streaming'))
            timeline = self.flow(STREAM_TIMELINE, b'\x00' + len(field(1, CONVERSATION)).to_bytes(4, 'big') + field(1, CONVERSATION), 'application/connect+proto')
            reply = (event(int(time.time() * 1000), group_start('a1'), block('b1', 'pong')) +
                     event(int(time.time() * 1000), delta('b1', '-wirebrain-7731')) + envelope(b'{}', 2))
            self.run_flow(addon, timeline, reply)
            self.assertEqual(timeline.request.headers['accept-encoding'], 'identity')
            row = store.list()[0]
            self.assertEqual((len(store.list()), row['response'], row['status']), (1, 'pong-wirebrain-7731', 'complete'))
            self.assertIn('pang-wirebrain-9046', row['prompt'])
            self.assertNotIn('secret-cookie', store.export())

    def timeline_flow(self):
        return self.flow(STREAM_TIMELINE, b'\x00' + len(field(1, CONVERSATION)).to_bytes(4, 'big') + field(1, CONVERSATION), 'application/connect+proto')

    def test_new_chat_opens_the_stream_before_the_prompt(self):
        with tempfile.TemporaryDirectory() as directory:
            store, addon = Store(directory), WebCapture(Store(directory))
            timeline = self.timeline_flow()
            addon.request(timeline)
            addon.responseheaders(timeline)
            early = event(int(time.time() * 1000) - 60_000, block('old', 'replayed earlier reply'))
            timeline.response.stream(early)        # nothing is trusted before the prompt is known
            self.run_flow(addon, self.flow(PERFORM_ACTION, PERFORM_ACTION_BODY, 'application/proto'))
            now = int(time.time() * 1000)
            timeline.response.stream(event(now, group_start('a1'), block('b1', 'pong')) + event(now, delta('b1', '-wirebrain-7731')) + envelope(b'{}', 2))
            timeline.response.stream(b'')
            addon.response(timeline)
            rows = store.list()
            self.assertEqual((len(rows), rows[0]['response'], rows[0]['status']), (1, 'pong-wirebrain-7731', 'complete'))

    def test_late_empty_stream_never_wipes_a_saved_reply(self):
        with tempfile.TemporaryDirectory() as directory:
            store, addon = Store(directory), WebCapture(Store(directory))
            self.run_flow(addon, self.flow(PERFORM_ACTION, PERFORM_ACTION_BODY, 'application/proto'))
            now = int(time.time() * 1000)
            self.run_flow(addon, self.timeline_flow(), event(now, block('b1', 'kept reply')) + envelope(b'{}', 2))
            self.run_flow(addon, self.timeline_flow(), envelope(b'{}', 2))     # reconnect after the answer was sent
            row = store.list()[0]
            self.assertEqual((row['response'], row['status']), ('kept reply', 'complete'))

    def test_timeline_without_a_prompt_and_failed_prompt_do_not_create_or_hide_data(self):
        with tempfile.TemporaryDirectory() as directory:
            store, addon = Store(directory), WebCapture(Store(directory))
            stray = self.flow(STREAM_TIMELINE, STREAM_TIMELINE_BODY, 'application/connect+proto')
            self.run_flow(addon, stray, event(NOW_MS, block('b1', 'history')) + envelope(b'{}', 2))
            self.assertEqual(store.list(), [])
            failed = self.flow(PERFORM_ACTION, PERFORM_ACTION_BODY, 'application/proto', status=429)
            self.run_flow(addon, failed)
            self.assertEqual(store.list()[0]['status'], 'error')


if __name__ == '__main__':
    unittest.main()
