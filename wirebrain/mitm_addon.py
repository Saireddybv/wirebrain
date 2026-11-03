"""mitmdump entry point. Only generation exchanges from the allowlist are saved."""
import os
import time
import json
import re
from urllib.parse import urlsplit, parse_qs
from pathlib import Path

from wirebrain.store import Store
from wirebrain.webcapture import HOSTS, MAX_TEXT, WebStream, generation_request
from wirebrain.extra_webcapture import stream_for, stream_content_type
from wirebrain.claude_rpc import ClaudeTimeline, STREAM_TIMELINE, timeline_conversation


class WebCapture:
    def __init__(self, store=None):
        self.store = store
        self.gemini_sessions = {}
        self.claude_pending = {}
        self.claude_streams = {}

    def load(self, loader):
        if self.store is None:
            self.store = Store(os.environ.get("WIREBRAIN_HOME", str(Path.home() / ".wirebrain")))

    def request(self, flow):
        if flow.request.host.lower() in HOSTS:
            self.store.capture_seen(flow.request.host.lower())
        if flow.request.host.lower()=='geminiweb-pa.clients6.google.com' and urlsplit(flow.request.path).path=='/v1/processSession':
            from wirebrain.gemini_channel import ChannelFrames
            sid=parse_qs(urlsplit(flow.request.path).query).get('SID',[''])[0]
            state=self.gemini_sessions.get(sid) if sid else None
            if state is None:
                state={'rows':{}}
                if sid and len(self.gemini_sessions)<128:self.gemini_sessions[sid]=state
            flow.metadata['wirebrain_channel']=ChannelFrames(self.store,state,self.gemini_sessions)
            flow.request.headers['accept-encoding']='identity'
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
        if flow.request.host.lower()=='geminiweb-pa.clients6.google.com' and urlsplit(flow.request.path).path=='/v1/processSession':
            from wirebrain.extra_webcapture import form
            from wirebrain.binarycapture import fields
            import base64
            def shape(raw,depth=0):
                if depth>10:return 'bounded'
                result={}
                for field,values in fields(raw).items():
                    summaries=[]
                    for item in values[:8]:
                        if isinstance(item,int):summary='integer'
                        else:
                            try:summary=shape(item,depth+1)
                            except (ValueError,IndexError):
                                try:
                                    literal=item.decode('utf-8')
                                    summary='TEST_PROMPT' if literal.startswith('Wirebrain ') else 'HELLO_REPLY' if literal.lower().strip() in ('hello','hello!') else 'text'
                                except UnicodeError:summary='bytes'
                        summaries.append(summary)
                    result[str(field)]=summaries
                return result
            try:
                for key, encoded in form(body).items():
                    if re.fullmatch(r'req\d+___data__',key):
                        raw=base64.b64decode(encoded,validate=True)
                        flow.metadata['wirebrain_channel'].request(raw)
                        from wirebrain.gemini_channel import schema as protobuf_schema
                        info=protobuf_schema(raw)
                        with self.store.connect() as db:
                            route='gemini WebChannel request schema '+','.join(sorted(info)) if isinstance(info,dict) else 'gemini WebChannel request schema bounded'
                            db.execute('INSERT INTO capture_routes VALUES (?,?,1) ON CONFLICT(route) DO UPDATE SET keys=excluded.keys,count=count+1',(route,json.dumps(info)))
            except (ValueError,TypeError,IndexError,UnicodeError):pass
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
        if flow.request.host.lower() == 'claude.ai' and urlsplit(flow.request.path).path == STREAM_TIMELINE:
            # claude.ai answers a PerformAction prompt on a separate StreamTimeline call, and a
            # new chat opens that stream first. Hold it unbound until its prompt arrives.
            conversation = timeline_conversation(body)
            if not conversation: return
            pending = self.claude_pending.get(conversation)
            state = {"id": pending["id"] if pending else None, "provider": "claude", "saved": 0, "conversation": conversation,
                     "stream": ClaudeTimeline(pending["at"] * 1000 if pending else None, pending["message_id"] if pending else '')}
            if len(self.claude_streams) >= 64: self.claude_streams.pop(next(iter(self.claude_streams)))
            self.claude_streams[conversation] = state
            flow.metadata["wirebrain"] = state
            flow.request.headers["accept-encoding"] = "identity"
            return
        try:
            capture = generation_request(flow.request.host, flow.request.path, body)
        except (TypeError, AttributeError):
            capture = None
        if capture and capture.get("reply_on_stream"):
            self.store.capture_seen(flow.request.host.lower(), prompt=True)
            ident = self.store.add(capture["provider"], capture["model"], capture["prompt"], "Web conversations")
            self.store.link_exchange(ident, capture["provider"], capture["conversation_id"], capture["message_id"], capture["parent_message_id"])
            if len(self.claude_pending) >= 64: self.claude_pending.pop(next(iter(self.claude_pending)))
            self.claude_pending[capture["conversation_id"]] = {"id": ident, "at": time.time(), "message_id": capture["message_id"]}
            waiting = self.claude_streams.get(capture["conversation_id"])
            if waiting and waiting["id"] is None and not waiting.get("closed"):
                waiting["id"] = ident
                waiting["stream"].bind(time.time() * 1000, capture["message_id"])
            flow.metadata["wirebrain_prompt_only"] = ident
            return
        if capture:
            self.store.capture_seen(flow.request.host.lower(), prompt=True)
            ident = self.store.add(capture["provider"], capture["model"], capture["prompt"], "Web conversations")
            self.store.link_exchange(ident, capture["provider"], capture["conversation_id"], capture["message_id"], capture["parent_message_id"])
            flow.metadata["wirebrain"] = {"id": ident, "provider": capture["provider"], "stream": stream_for(capture["provider"]), "saved": 0}
            # Ensure the streamed bytes can be parsed without buffering compressed data.
            # This affects only allowlisted services' generation requests.
            flow.request.headers["accept-encoding"] = "identity"

    def responseheaders(self, flow):
        if flow.metadata.get('wirebrain_channel'):
            channel=flow.metadata['wirebrain_channel']
            encoding=flow.response.headers.get('content-encoding','').lower()
            with self.store.connect() as db:
                db.execute('INSERT INTO capture_routes VALUES (?,?,1) ON CONFLICT(route) DO UPDATE SET keys=excluded.keys,count=count+1',('gemini WebChannel response transport',json.dumps({'encoding':encoding if encoding in ('gzip','deflate','br','zstd','') else 'other','status':flow.response.status_code})))
            decoder=None
            if encoding in ('gzip','deflate'):
                import zlib
                decoder=zlib.decompressobj(16+zlib.MAX_WBITS if encoding=='gzip' else zlib.MAX_WBITS)
            def channel_tee(chunk):
                try:
                    decoded=decoder.decompress(chunk) if decoder and chunk else chunk
                    channel.feed(decoded if chunk else b'\n')
                except Exception:pass
                return chunk
            flow.response.stream=channel_tee
            return
        state = flow.metadata.get("wirebrain")
        if not state:
            return
        if not stream_content_type(state['provider'], flow.response.headers.get("content-type", "")):
            # Unsupported response formats must not be buffered indefinitely.
            flow.response.stream = True
            return

        def tee(chunk):
            try:
                if chunk:
                    state["streamed"] = True
                    state["stream"].feed(chunk)
                    now = time.monotonic()
                    if state["id"] is not None and now - state["saved"] >= .5:
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
        if flow.metadata.get('wirebrain_channel'):
            flow.metadata['wirebrain_channel'].feed(b'\n')
            return
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
        if flow.metadata.get("wirebrain_prompt_only"):
            # The reply to the prompt call is empty; the answer follows on StreamTimeline.
            if flow.response.status_code >= 400:
                self.store.update(flow.metadata["wirebrain_prompt_only"], "", "error")
            return
        state = flow.metadata.get("wirebrain")
        if not state:
            return
        stream = state["stream"]
        # Internally generated or already-buffered responses may bypass stream().
        if not state.get("streamed") and stream_content_type(state['provider'], flow.response.headers.get("content-type", "")):
            content = getattr(flow.response, "content", None)
            if content and len(content) <= MAX_TEXT:
                stream.feed(content)
        stream.finish()
        if state.get("conversation"):
            state["closed"] = True
            # A stream that opened after the reply, or before any prompt, has nothing to add.
            if state["id"] is None or not stream.text: return
        status = "error" if flow.response.status_code >= 400 else stream.status
        if not stream_content_type(state['provider'], flow.response.headers.get("content-type", "")) and status != "error":
            status = "unsupported"
        if state.get("failed"): status = "capture_error"
        self.store.update(state["id"], stream.text, status)
        self.store.link_exchange(state['id'], state['provider'], stream.conversation_id, response_message_id=stream.response_message_id)
        if state.get("conversation") and status in ("complete", "error", "truncated"):
            self.claude_pending.pop(state["conversation"], None)

    def websocket_message(self, flow):
        if flow.request.host.lower() in ('grok.com','www.grok.com') and urlsplit(flow.request.path).path=='/ws/mgw/':
            from wirebrain.grok_socket import GrokSocket
            if getattr(flow,'websocket',None):
                capture=flow.metadata.setdefault('wirebrain_grok_socket',GrokSocket(self.store))
                capture.receive(flow.websocket.messages)
            return
        if flow.request.host.lower()!='gateway.meta.ai': return
        from wirebrain.binarycapture import dgw_frames, meta_prompt, MetaReply
        websocket=getattr(flow,'websocket',None)
        if not websocket:return
        streams=flow.metadata.setdefault('wirebrain_meta_streams',{})
        messages=websocket.messages
        start=max(flow.metadata.get('wirebrain_meta_processed',0),len(messages)-100)
        for message in messages[start:]:
            for kind,stream_id,body in dgw_frames(message.content):
                try:
                    if stream_id not in streams and len(streams)>=256:continue
                    state=streams.setdefault(stream_id,{})
                    if kind==15 and message.from_client:
                        header=json.loads(body)
                        cid=header.get('x-dgw-app-x-ecto-conversation-id')
                        if isinstance(cid,str):state['conversation_id']=cid
                    elif kind==13 and len(body)>=2:
                        if message.from_client:
                            prompt=meta_prompt(body[2:])
                            if not prompt:continue
                            if state.get('id') and not state['reply'].done:
                                self.store.update(state['id'],state['reply'].text,'interrupted')
                            cid=prompt['conversation_id'] or state.get('conversation_id','')
                            ident=self.store.add('meta','web · unknown',prompt['prompt'],'Web conversations')
                            self.store.link_exchange(ident,'meta',cid,prompt['message_id'],prompt['parent_message_id'])
                            state.update(id=ident,reply=MetaReply(),conversation_id=cid)
                            self.store.capture_seen('gateway.meta.ai',prompt=True)
                            with self.store.connect() as db:
                                db.execute("DELETE FROM capture_routes WHERE route='meta websocket binary transport'")
                        elif state.get('id'):
                            reply=state['reply'];reply.feed(body[2:])
                            self.store.update(state['id'],reply.text,reply.status if reply.done or reply.error else 'streaming')
                            self.store.link_exchange(state['id'],'meta',state.get('conversation_id',''),response_message_id=reply.response_id)
                except (ValueError,TypeError,KeyError,IndexError,AttributeError,UnicodeError):
                    # Never change or replay website bytes, including unknown frames.
                    if streams.get(stream_id,{}).get('id'):
                        state=streams[stream_id]
                        self.store.update(state['id'],state['reply'].text,'capture_error')
        flow.metadata['wirebrain_meta_processed']=len(messages)

    def websocket_end(self, flow):
        if flow.metadata.get('wirebrain_grok_socket'):
            self.websocket_message(flow)
            flow.metadata['wirebrain_grok_socket'].finish()
            return
        if flow.request.host.lower()!='gateway.meta.ai':return
        self.websocket_message(flow)
        for state in flow.metadata.get('wirebrain_meta_streams',{}).values():
            if state.get('id') and not state['reply'].done:
                self.store.update(state['id'],state['reply'].text,'interrupted')

    def error(self, flow):
        if flow.metadata.get('wirebrain_channel'):
            flow.metadata['wirebrain_channel'].interrupted()
        state = flow.metadata.get("wirebrain")
        if state and state["id"] is not None and (state["stream"].text or not state.get("conversation")):
            self.store.update(state["id"], state["stream"].text, "interrupted")


addons = [WebCapture()]
