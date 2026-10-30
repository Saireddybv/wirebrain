"""Passive, text-only adapters for Gemini, Grok and Meta's HTTP chat transport.

These private web protocols are experimental. No authentication or replay code.
"""
import json
import re
from urllib.parse import parse_qs, urlsplit

LIMIT = 2 * 1024 * 1024
GEMINI_PATH = '/_/BardChatUi/data/assistant.lamda.BardFrontendService/StreamGenerate'


def nested(value, *path):
    try:
        for key in path: value = value[key]
        return value
    except (IndexError, KeyError, TypeError): return None


def form(body):
    if isinstance(body, bytes): body = body.decode('utf-8')
    return {k:v[0] for k,v in parse_qs(body, max_num_fields=200).items()}


def submitted(provider, path, body):
    path = urlsplit(path).path
    prompt = conversation = message = parent = ''
    model = 'web · unknown'
    try:
        if provider == 'gemini' and path == GEMINI_PATH:
            envelope = json.loads(form(body).get('f.req','null'))
            inner = json.loads(envelope[1])
            prompt = nested(inner,0,0)
            conversation, parent = nested(inner,2,0), nested(inner,2,1)
        elif provider == 'grok' and re.fullmatch(r'/rest/app-chat/conversations/(?:new|[^/]+/responses)',path):
            data = json.loads(body)
            prompt = data.get('message')
            model = data.get('modelName') or model
            if not path.endswith('/new'): conversation = path.split('/')[-2]
            parent = data.get('parentResponseId')
        elif provider == 'meta' and path in ('/api/graphql/','/api/graphql','/graphql'):
            data = form(body)
            # Never treat other GraphQL mutations, search, or draft changes as chat.
            if data.get('fb_api_req_friendly_name') != 'useAbraSendMessageMutation': return
            variables = json.loads(data.get('variables','null'))
            prompt = nested(variables,'message','sensitive_string_value')
            conversation = variables.get('externalConversationId')
            message = variables.get('offlineThreadingId')
        else: return
        if not isinstance(prompt,str) or not prompt.strip(): return
        return {'provider':provider,'prompt':prompt[:LIMIT], 'model':str(model)[:200],
                'conversation_id':conversation if isinstance(conversation,str) else '',
                'message_id':message if isinstance(message,str) else '',
                'parent_message_id':parent if isinstance(parent,str) else ''}
    except (ValueError,TypeError,IndexError,KeyError,AttributeError,UnicodeError): return


class TextStream:
    """Incremental line framing with bounded buffers; preserves UTF-8 boundaries."""
    def __init__(self, provider):
        self.provider = provider
        self.pending = b''
        self.text = ''
        self.done = self.error = self.truncated = False
        self.conversation_id = self.response_message_id = ''

    def feed(self, chunk):
        if self.truncated: return
        self.pending += chunk
        if len(self.pending)>LIMIT:
            self.pending=b''; self.truncated=True; return
        while b'\n' in self.pending:
            line,self.pending=self.pending.split(b'\n',1)
            line=line.strip()
            if line.startswith(b'data:'): line=line[5:].strip()
            if line == b'[DONE]': self.done=True; continue
            # Gemini's XSSI prefix and numeric frame sizes contain no message text.
            if not line or line.startswith(b")]}'") or line.isdigit(): continue
            try: self.event(json.loads(line))
            except (ValueError,TypeError,KeyError,IndexError,AttributeError,UnicodeError): pass
            if len(self.text)>LIMIT:
                self.text=self.text[:LIMIT];self.truncated=True;return

    def finish(self): self.feed(b'\n')

    def event(self, event):
        if isinstance(event,dict) and (event.get('error') or event.get('errors')): self.error=True
        if self.provider=='gemini': self.gemini(event)
        elif self.provider=='grok': self.grok(event)
        elif self.provider=='meta': self.meta(event)

    def gemini(self, event):
        if not isinstance(event,list): return
        for frame in event:
            if not isinstance(frame,list) or len(frame)<3 or frame[0]!='wrb.fr' or not isinstance(frame[2],str): continue
            try: data=json.loads(frame[2])
            except ValueError: continue
            cid=nested(data,1,0)
            if isinstance(cid,str) and cid.startswith('c_'): self.conversation_id=cid
            candidate=nested(data,4,0)
            text=nested(candidate,1,0)
            if isinstance(text,str): self.text=text  # cumulative snapshot, not a delta
            rid=nested(candidate,0)
            if isinstance(rid,str): self.response_message_id=rid
            if nested(candidate,8,0)==2: self.done=True

    def grok(self, event):
        result=nested(event,'result')
        if not isinstance(result,dict): return
        cid=nested(result,'conversation','conversationId')
        if isinstance(cid,str): self.conversation_id=cid
        response=result.get('response',result)
        if not isinstance(response,dict): return
        final=response.get('modelResponse')
        if isinstance(final,dict):
            if isinstance(final.get('message'),str): self.text=final['message']
            if isinstance(final.get('responseId'),str): self.response_message_id=final['responseId']
            self.done=True
        elif not response.get('isThinking') and isinstance(response.get('token'),str):
            self.text+=response['token']
        if response.get('isFinal') is True: self.done=True

    def meta(self, event):
        message=nested(event,'data','node','bot_response_message')
        if not isinstance(message,dict): return
        parts=nested(message,'composed_text','content')
        if isinstance(parts,list):
            self.text='\n'.join(p['text'] for p in parts if isinstance(p,dict) and isinstance(p.get('text'),str))
        ident=message.get('id')
        if isinstance(ident,str): self.response_message_id=ident
        if message.get('streaming_state')=='OVERALL_DONE': self.done=True

    @property
    def status(self):
        if self.truncated: return 'truncated'
        if self.error: return 'error'
        return 'complete' if self.done else 'interrupted'


def stream_for(provider):
    if provider in ('gemini','grok','meta'): return TextStream(provider)
    from .webcapture import WebStream
    return WebStream(provider)


def stream_content_type(provider, content_type):
    kind=content_type.split(';',1)[0].strip().lower()
    if kind=='text/event-stream': return True
    return provider in ('gemini','grok','meta') and kind in (
        'application/json','application/x-ndjson','application/jsonl','text/plain','text/javascript')
