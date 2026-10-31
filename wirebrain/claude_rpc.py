"""claude.ai's protobuf conversation RPC.

A chat turn is two calls: ``PerformAction`` submits the prompt as a plain
protobuf body with an empty reply, and ``StreamTimeline`` streams the reply as
Connect envelopes. Only the prompt, ids and assistant text blocks are read.
"""
import gzip
import json
import re

from .binarycapture import fields, text as proto_text

RPC = '/claudeai-rpc/anthropic.bard.api.v1alpha.ConversationService/'
PERFORM_ACTION = RPC + 'PerformAction'
STREAM_TIMELINE = RPC + 'StreamTimeline'
MAX_TEXT = 2 * 1024 * 1024
TEXT_BLOCK = 2
# Event ids are server-side epoch milliseconds. Allow for clock skew, but never
# take replayed history from before the prompt that was submitted.
SKEW_MS = 10_000


def _first(parsed, key):
    values = parsed.get(key)
    return values[0] if values else None


def _utf8(raw):
    try: return raw.decode('utf-8') if isinstance(raw, bytes) else ''
    except UnicodeError: return ''


def prompt_request(body):
    """Return the submitted prompt from a PerformAction body; None for other actions."""
    try:
        parsed = fields(body)
        header, message = _first(parsed, 1), _first(parsed, 2)
        if not isinstance(header, bytes) or not isinstance(message, bytes): return None
        prompt = proto_text(message, 3)
        if not prompt.strip(): return None
        return {'provider': 'claude', 'prompt': prompt[:MAX_TEXT], 'model': 'web · unknown',
                'conversation_id': proto_text(header, 2), 'message_id': proto_text(message, 1),
                'parent_message_id': proto_text(message, 2), 'reply_on_stream': True}
    except (ValueError, TypeError, IndexError):
        return None


def timeline_conversation(body):
    """Conversation id from a StreamTimeline request (one Connect envelope)."""
    try:
        if not isinstance(body, bytes) or len(body) < 5 or body[0] & 1: return ''
        size = int.from_bytes(body[1:5], 'big')
        return proto_text(body[5:5 + size], 1)
    except (ValueError, TypeError, IndexError):
        return ''


class ClaudeTimeline:
    """Incremental reader for StreamTimeline's Connect envelope stream."""
    def __init__(self, not_before_ms=None, message_id=''):
        # Until the prompt it answers is known, no event is trusted: a stream can open first.
        self.not_before = float('inf') if not_before_ms is None else int(not_before_ms) - SKEW_MS
        self.pending = b''
        self.blocks = {}
        self.order = []
        self.done = False
        self.error = False
        self.truncated = False
        self.conversation_id = ''
        self.response_message_id = ''
        self.own_messages = {message_id} if message_id else set()   # the user's own message, which the stream also carries
        self.groups = {}

    @property
    def text(self):
        return '\n\n'.join(self.blocks[b]['text'] for b in self.order
                           if self.blocks[b]['type'] == TEXT_BLOCK and self.blocks[b]['text'])[:MAX_TEXT]

    def feed(self, chunk):
        if self.truncated: return
        self.pending += chunk
        while len(self.pending) >= 5:
            flags, size = self.pending[0], int.from_bytes(self.pending[1:5], 'big')
            if size > MAX_TEXT:
                self.pending, self.truncated = b'', True
                return
            if len(self.pending) < 5 + size: return
            payload, self.pending = self.pending[5:5 + size], self.pending[5 + size:]
            if flags & 2:
                self._end(payload)
                continue
            if flags & 1:
                try: payload = gzip.decompress(payload)
                except (OSError, EOFError, ValueError): continue
            self._event(payload)

    def bind(self, prompt_ms, message_id=''):
        self.not_before = int(prompt_ms) - SKEW_MS
        if message_id: self.own_messages.add(message_id)

    def finish(self):
        pass

    def _end(self, payload):
        try: end = json.loads(payload) if payload else {}
        except (ValueError, UnicodeError): end = {}
        if isinstance(end, dict) and end.get('error'): self.error = True
        else: self.done = True

    def _event(self, payload):
        try:
            wrapper = _first(fields(payload), 1)
            if not isinstance(wrapper, bytes): return
            parsed = fields(wrapper)
            stamp = re.match(r'(\d{10,})-', proto_text(_first(parsed, 10) or b'', 1))
            if not stamp or int(stamp[1]) < self.not_before: return
            for item in parsed.get(1, []): self._update(fields(item))
            for item in parsed.get(2, []): self._delta(fields(item))
        except (ValueError, TypeError, IndexError):
            pass

    def _update(self, event):
        group = _first(event, 4)
        if isinstance(group, bytes):
            group_id, message_id = proto_text(group, 1), proto_text(group, 2)
            if group_id: self.groups[group_id] = message_id
            if message_id and message_id not in self.own_messages and not self.response_message_id:
                self.response_message_id = message_id
        block = _first(event, 5)
        if not isinstance(block, bytes): return
        parsed = fields(block)
        ident = _utf8(_first(parsed, 1))
        if not ident or self.groups.get(_utf8(_first(parsed, 2))) in self.own_messages: return
        known = self.blocks.setdefault(ident, {'type': None, 'text': ''})
        if ident not in self.order: self.order.append(ident)
        kind = _first(fields(_first(parsed, 10) or b''), 1)
        if isinstance(kind, int): known['type'] = kind
        if 9 in parsed: known['text'] = _utf8(_first(parsed, 9))

    def _delta(self, event):
        known = self.blocks.get(_utf8(_first(event, 1)))
        raw = _first(event, 2)
        # A float-only update is a nested message, not appended text.
        if known is None or not isinstance(raw, bytes) or (len(raw) == 5 and raw[0] == 0x2d): return
        known['text'] += _utf8(raw)

    @property
    def status(self):
        if self.truncated: return 'truncated'
        if self.error: return 'error'
        return 'complete' if self.done else 'interrupted'
