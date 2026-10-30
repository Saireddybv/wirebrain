"""mitmdump entry point. Only generation exchanges from the allowlist are saved."""
import os
import time
import json
import re
from urllib.parse import urlsplit
from pathlib import Path

from wirebrain.store import Store
from wirebrain.webcapture import HOSTS, MAX_TEXT, WebStream, generation_request


class WebCapture:
    def __init__(self, store=None):
        self.store = store

    def load(self, loader):
        if self.store is None:
            self.store = Store(os.environ.get("WIREBRAIN_HOME", str(Path.home() / ".wirebrain")))

    def request(self, flow):
        if flow.request.host.lower() in HOSTS:
            self.store.capture_seen(flow.request.host.lower())
        # A reopened chat supplies canonical text that can repair a previous
        # partial capture. Do not import uncaptured chats or alternative branches.
        if flow.request.method == "GET" and flow.request.host.lower() in ("chatgpt.com", "chat.openai.com") and re.fullmatch(r"/backend-api/conversation/[0-9a-fA-F-]{36}", urlsplit(flow.request.path).path):
            flow.metadata["wirebrain_history"] = urlsplit(flow.request.path).path.rsplit('/',1)[-1]
            return
        if flow.request.method != "POST":
            return
        body = flow.request.content or b""
        if len(body) > 8 * 1024 * 1024:
            return
        if flow.request.host.lower() in HOSTS:
            self.store.capture_route(flow.request.host.lower(), flow.request.method, flow.request.path, body)
            # Protocol diagnostics contain schema names and route structure only,
            # never message values, query strings, cookies, or identifiers.
            pieces = [s if re.fullmatch(r"[a-z][a-z_-]{0,24}", s) else ":id" for s in urlsplit(flow.request.path).path.split('/') if s]
            def schema(value, depth=0):
                if depth > 3: return type(value).__name__
                if isinstance(value, dict):
                    return {k: schema(v, depth+1) for k,v in list(value.items())[:40] if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", k)}
                if isinstance(value, list): return [schema(value[0], depth+1)] if value else []
                return type(value).__name__
            try: shape = schema(json.loads(body))
            except (ValueError, UnicodeError): shape = "non-json"
            info = {"shape": shape, "content_type": flow.request.headers.get("content-type", "unknown"), "bytes": len(body)}
            route = f"{flow.request.host.lower()} {flow.request.method} /{'/'.join(pieces)}"
            with self.store.connect() as db:
                db.execute("INSERT INTO capture_routes VALUES (?,?,1) ON CONFLICT(route) DO UPDATE SET keys=excluded.keys,count=count+1", (route, json.dumps(info)))
        try:
            capture = generation_request(flow.request.host, flow.request.path, body)
        except (TypeError, AttributeError):
            capture = None
        if capture:
            self.store.capture_seen(flow.request.host.lower(), prompt=True)
            ident = self.store.add(capture["provider"], capture["model"], capture["prompt"], "Web conversations")
            self.store.link_exchange(ident, capture["provider"], capture["conversation_id"], capture["message_id"], capture["parent_message_id"])
            flow.metadata["wirebrain"] = {"id": ident, "provider": capture["provider"], "stream": WebStream(capture["provider"]), "saved": 0}
            # Ensure the streamed bytes can be parsed without buffering compressed data.
            # This affects only the three allowlisted services' generation requests.
            flow.request.headers["accept-encoding"] = "identity"

    def responseheaders(self, flow):
        state = flow.metadata.get("wirebrain")
        if not state:
            return
        if "text/event-stream" not in flow.response.headers.get("content-type", ""):
            # Unsupported response formats must not be buffered indefinitely.
            flow.response.stream = True
            return

        def tee(chunk):
            try:
                if chunk:
                    state["streamed"] = True
                    state["stream"].feed(chunk)
                    now = time.monotonic()
                    if now - state["saved"] >= .5:
                        self.store.update(state["id"], state["stream"].text, "streaming")
                        self.store.link_exchange(state['id'], state['provider'], state['stream'].conversation_id, response_message_id=state['stream'].response_message_id)
                        state["saved"] = now
                else:
                    state["stream"].finish()
            except Exception:
                # Persistence failure must not break a user's existing conversation.
                state["failed"] = True
            return chunk  # Preserve every response byte exactly, including binary data.

        flow.response.stream = tee

    def response(self, flow):
        if flow.metadata.get("wirebrain_history") and flow.response.status_code == 200:
            content = getattr(flow.response, "content", None)
            if content and len(content) <= 8 * 1024 * 1024:
                try:
                    history = json.loads(content)
                    if isinstance(history, dict):
                        history['conversation_id'] = flow.metadata['wirebrain_history']
                        self.store.repair_chatgpt_history(history)
                except (ValueError, TypeError, AttributeError): pass
            return
        state = flow.metadata.get("wirebrain")
        if not state:
            return
        stream = state["stream"]
        # Internally generated or already-buffered responses may bypass stream().
        if not state.get("streamed") and "text/event-stream" in flow.response.headers.get("content-type", ""):
            content = getattr(flow.response, "content", None)
            if content and len(content) <= MAX_TEXT:
                stream.feed(content)
        stream.finish()
        status = "error" if flow.response.status_code >= 400 else stream.status
        if "text/event-stream" not in flow.response.headers.get("content-type", "") and status != "error":
            status = "unsupported"
        if state.get("failed"): status = "capture_error"
        self.store.update(state["id"], stream.text, status)
        self.store.link_exchange(state['id'], state['provider'], stream.conversation_id, response_message_id=stream.response_message_id)

    def error(self, flow):
        state = flow.metadata.get("wirebrain")
        if state:
            self.store.update(state["id"], state["stream"].text, "interrupted")


addons = [WebCapture()]
