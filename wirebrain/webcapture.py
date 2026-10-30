"""Text-only adapters for allowlisted AI website protocols.

No cookies, authorization headers, page titles, or unrelated traffic are stored.
Parsing is intentionally independent of mitmproxy so it can be tested offline.
"""
import json
import re
from urllib.parse import urlsplit

HOSTS = {"chatgpt.com": "chatgpt", "chat.openai.com": "chatgpt", "claude.ai": "claude",
         "gemini.google.com":"gemini", "geminiweb-pa.clients6.google.com":"gemini", "grok.com":"grok", "www.grok.com":"grok",
         "meta.ai":"meta", "www.meta.ai":"meta", "graph.meta.ai":"meta", "gateway.meta.ai":"meta"}
ALLOW_HOSTS = r"^(" + '|'.join(re.escape(host) for host in HOSTS) + r")(:443)?$"
MAX_TEXT = 2 * 1024 * 1024


def generation_request(host, path, body):
    """Return a supported submitted prompt, never a draft or history response."""
    provider = HOSTS.get(host.lower())
    if provider in ('gemini','grok','meta'):
        from .extra_webcapture import submitted
        return submitted(provider,path,body)
    path = urlsplit(path).path
    if provider == "chatgpt":
        if not re.fullmatch(r"/backend-api/(?:f/)?conversation", path):
            return None
    elif provider == "claude":
        if not re.fullmatch(r"/api/organizations/[^/]+/chat_conversations/[^/]+/completion", path):
            return None
    else:
        return None
    try:
        data = json.loads(body)
    except (ValueError, UnicodeError, TypeError):
        return None
    if not isinstance(data, dict):
        return None
    if provider == "chatgpt":
        prompts = []
        message_id = ""
        for message in data.get("messages", []):
            if not isinstance(message, dict) or message.get("author", {}).get("role") != "user":
                continue
            content = message.get("content", {})
            if isinstance(content, dict):
                prompts.extend(p for p in content.get("parts", []) if isinstance(p, str))
                message_id = message.get("id", "")
        prompt = "\n\n".join(prompts)
        conversation_id = data.get("conversation_id", "")
        parent_id = data.get("parent_message_id", "")
    else:
        prompt = data.get("prompt", "")
        match = re.fullmatch(r"/api/organizations/([^/]+)/chat_conversations/([^/]+)/completion", path)
        conversation_id = f"{match[1]}/{match[2]}"
        ids = data.get("turn_message_uuids", {})
        message_id = ids.get("human_message_uuid", "") if isinstance(ids, dict) else ""
        parent_id = data.get("parent_message_uuid", "")
    if not isinstance(prompt, str) or not prompt.strip():
        return None
    return {"provider": provider, "prompt": prompt[:MAX_TEXT], "model": str(data.get("model", "web · unknown"))[:200],
            "conversation_id": conversation_id, "message_id": message_id, "parent_message_id": parent_id}


def history_pairs(data):
    """Read final text along the selected ChatGPT history branch, not alternatives."""
    if not isinstance(data, dict) or not isinstance(data.get("mapping"), dict): return []
    mapping, cursor = data["mapping"], data.get("current_node")
    branch, visited = [], set()
    while isinstance(cursor, str) and cursor in mapping and cursor not in visited and len(branch) < 10000:
        visited.add(cursor)
        node = mapping[cursor]
        if not isinstance(node, dict): break
        message = node.get("message")
        if isinstance(message, dict): branch.append({**message, "_node_id": cursor, "_parent_id": node.get("parent")})
        cursor = node.get("parent")
    pairs, pending = [], None
    for message in reversed(branch):
        content = message.get("content", {})
        if not isinstance(content, dict) or content.get("content_type") != "text": continue
        text = "\n".join(p for p in content.get("parts", []) if isinstance(p, str))
        role = message.get("author", {}).get("role")
        if role == "user":
            pending = {"prompt": text, "created": message.get("create_time"), "message_id": message.get('id') or message.get('_node_id'), "parent_message_id": message.get('_parent_id')}
        elif role == "assistant" and pending and message.get("channel") in (None, "final") and message.get("recipient", "all") in (None, "all") and message.get("status") == "finished_successfully":
            pairs.append({**pending, "response": text, "response_message_id": message.get('id') or message.get('_node_id')})
            pending = None
    return pairs


class WebStream:
    """Incremental SSE parser, accepting arbitrary byte boundaries and CRLF."""
    def __init__(self, provider):
        self.provider = provider
        self.text = ""
        self.pending = b""
        self.data = []
        self.done = False
        self.error = False
        self.truncated = False
        self._assistant = False
        self._path = ""
        self._operation = ""
        self._parts = []
        self.conversation_id = ""
        self.response_message_id = ""

    def feed(self, chunk):
        if self.truncated:
            return
        self.pending += chunk
        if len(self.pending) > MAX_TEXT:
            self.pending = b""
            self.truncated = True
            return
        while b"\n" in self.pending:
            line, self.pending = self.pending.split(b"\n", 1)
            line = line.rstrip(b"\r")
            if line.startswith(b"data:"):
                self.data.append(line[5:].lstrip(b" "))
            elif not line and self.data:
                raw, self.data = b"\n".join(self.data), []
                if raw == b"[DONE]":
                    self.done = True
                else:
                    try:
                        obj = json.loads(raw)
                        if isinstance(obj, dict): self.event(obj)
                    except (ValueError, TypeError, AttributeError):
                        pass
                if len(self.text) > MAX_TEXT:
                    self.text = self.text[:MAX_TEXT]
                    self.truncated = True
                    return
            if sum(map(len, self.data)) > MAX_TEXT:
                self.data = []
                self.truncated = True
                return

    def finish(self):
        self.feed(b"\n\n")

    def event(self, event):
        if event.get("error") or event.get("type") == "error":
            self.error = True
        if self.provider == "claude":
            kind = event.get("type")
            if kind == "content_block_start":
                block = event.get("content_block", {})
                if block.get("type") == "text": self.text += block.get("text", "")
            elif kind == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta": self.text += delta.get("text", "")
            elif isinstance(event.get("completion"), str):
                self.text += event["completion"]
            if kind == "message_stop" or event.get("stop_reason"):
                self.done = True
            return

        # ChatGPT compact frames inherit BOTH operation and path. A common stream
        # sends {p:...,o:'append',v:'first'} followed by {v:' next'} repeatedly.
        value = event.get("v", event)
        if isinstance(event.get("conversation_id"), str): self.conversation_id = event["conversation_id"]
        if "p" in event: self._path = event["p"]
        if "o" in event: self._operation = event["o"]
        self._chatgpt_patch(self._path, self._operation, value)

    def _chatgpt_patch(self, path, operation, value):
        if isinstance(value, dict) and isinstance(value.get("conversation_id"), str):
            self.conversation_id = value["conversation_id"]
        if path in ("/conversation_id", "conversation_id") and isinstance(value, str):
            self.conversation_id = value
        if isinstance(value, dict) and isinstance(value.get("message"), dict):
            message = value["message"]
            self._assistant = message.get("author", {}).get("role") == "assistant"
            if self._assistant and isinstance(message.get("id"), str): self.response_message_id = message["id"]
            content = message.get("content", {})
            if self._assistant and content.get("content_type") == "text":
                self._parts = [p if isinstance(p, str) else "" for p in content.get("parts", [])]
                self.text = "\n".join(self._parts)
                if message.get("status") == "finished_successfully": self.done = True
        if operation == "patch" and isinstance(value, list):
            # Batch entries have their own context: never replace the outer
            # compact stream's inherited 'patch' operation with a child op.
            batch_path, batch_op = "", ""
            for patch in value:
                if isinstance(patch, dict):
                    batch_path = patch.get("p", batch_path)
                    batch_op = patch.get("o", batch_op)
                    self._chatgpt_patch(batch_path, batch_op, patch.get("v"))
            return
        match = re.fullmatch(r"/?message/content/parts/(\d+)", str(path))
        if self._assistant and match and isinstance(value, str):
            index = int(match[1])
            if index > 1024: return
            while len(self._parts) <= index: self._parts.append("")
            if operation == "append": self._parts[index] += value
            elif operation in ("replace", "add"): self._parts[index] = value
            self.text = "\n".join(self._parts)
        elif self._assistant and str(path).strip('/') == "message/content/parts" and isinstance(value, list):
            parts = [p if isinstance(p, str) else "" for p in value]
            if operation == "append": self._parts.extend(parts)
            elif operation in ("replace", "add"): self._parts = parts
            self.text = "\n".join(self._parts)
        if path == "/message/status" and value == "finished_successfully": self.done = True

    @property
    def status(self):
        if self.truncated: return "truncated"
        if self.error: return "error"
        return "complete" if self.done else "interrupted"
