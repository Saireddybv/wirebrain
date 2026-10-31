"""Cached combined and per-app views of reusable, evidence-backed memory."""
from .prompting import render_prompt, load_schema
import hashlib
import json
import re
import threading
import time

from .personal_memory import list_memories, now, state

LOCK = threading.Lock()
ERRORS = {}
PROVIDERS = ('', 'chatgpt', 'claude', 'gemini', 'grok', 'meta')
NAMES = {'':'Wirebrain memory','chatgpt':'ChatGPT memory','claude':'Claude memory',
         'gemini':'Gemini memory','grok':'Grok memory','meta':'Meta AI memory'}
SCHEMA = load_schema('memory.overview')


def snapshot(store, provider='', scope=''):
    if provider not in PROVIDERS or not isinstance(scope,str) or len(scope)>80:
        raise ValueError('Choose an AI app and a valid collection')
    memories = list_memories(store,provider=provider,scope=scope,limit=2000)
    compact = [{k:memory[k] for k in ('id','text','kind','status','updated')} | {
        'sources': sorted(source['exchange_id'] for source in memory['sources'])} for memory in memories]
    from .intelligence import settings
    config=settings(store)
    prompt_revision=hashlib.sha256(render_prompt('memory.overview').encode()).hexdigest()
    fingerprint=hashlib.sha256(json.dumps([provider,scope,compact,config.get('writing_provider','ollama'),config['chat_model'],prompt_revision],sort_keys=True).encode()).hexdigest()
    return memories, fingerprint


def overview(store, provider='', scope=''):
    memories, fingerprint=snapshot(store,provider,scope)
    selected=memories[:32]
    with store.connect() as db:
        cached=db.execute('SELECT body,updated FROM memory_rollups WHERE provider=? AND scope=? AND fingerprint=?',
                          (provider,scope,fingerprint)).fetchone()
    data=json.loads(cached['body']) if cached else {'summary':'','sources':[]}
    # No stale text is returned while a newer snapshot is waiting for synthesis.
    failed=ERRORS.get((provider,scope))
    error=failed[1] if failed and failed[0]==fingerprint and time.monotonic()-failed[2]<300 else ''
    return {'title':NAMES[provider], 'provider':provider, 'scope':scope,'error':error,
            'summary':data['summary'],'updated':cached['updated'] if cached else '',
            'total':len(memories),'included':len(selected),'needs_refresh':bool(memories and not cached),
            'building':LOCK.locked(),'sources':[{**memory,'citation':i} for i,memory in enumerate(selected,1) if memory['id'] in data['sources']],
            'preview':[{'id':memory['id'],'text':memory['text']} for memory in selected[:5]]}


def build(store, provider='', scope=''):
    from .intelligence import settings, writing_request
    if not LOCK.acquire(blocking=False): return {'building':True}
    try:
        memories, fingerprint=snapshot(store,provider,scope)
        if not memories or not overview(store,provider,scope)['needs_refresh']:
            return overview(store,provider,scope)
        config=settings(store)
        if not config['chat_model']: raise ValueError('Choose a writing backend to build a consolidated memory')
        selected=memories[:32]
        evidence=[{'source':i,'kind':memory['kind'],'text':memory['text']} for i,memory in enumerate(selected,1)]
        result=writing_request(store,{'model':config['chat_model'],'stream':False,'think':False,'format':SCHEMA,
            'messages':[{'role':'system','content':render_prompt('memory.overview')},
                {'role':'user','content':json.dumps({'view':NAMES[provider],'collection':scope or 'Personal','memories':evidence})}]})
        try: data=json.loads(result.get('message',{}).get('content',''))
        except (ValueError,TypeError): raise ValueError('The memory overview returned invalid JSON') from None
        if not isinstance(data,dict) or not isinstance(data.get('summary'),str) or not 1<=len(data['summary'])<=2500:
            raise ValueError('The memory overview returned invalid text')
        citations=data.get('sources')
        if not isinstance(citations,list) or not citations or any(type(i) is not int or not 1<=i<=len(selected) for i in citations):
            raise ValueError('The memory overview returned invalid source references')
        mentioned={int(value) for value in re.findall(r'\[(\d+)\]',data['summary'])}
        if not mentioned or mentioned!=set(citations):
            raise ValueError('The memory overview citations did not match its source references')
        from .store import redact
        body={'summary':redact(data['summary']), 'sources':[selected[i-1]['id'] for i in dict.fromkeys(citations)]}
        # Recompute while holding a SQLite write reservation; a concurrent forget,
        # source correction, or scope change must win over this in-flight draft.
        with store.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if snapshot(store,provider,scope)[1]!=fingerprint:
                return {'changed':True}
            db.execute('INSERT OR REPLACE INTO memory_rollups VALUES (?,?,?,?,?)',
                       (provider,scope,fingerprint,json.dumps(body),now()))
        return overview(store,provider,scope)
    finally: LOCK.release()


def start(store, provider='', scope=''):
    data=overview(store,provider,scope)
    from .intelligence import settings
    if not data['needs_refresh'] or data['error'] or LOCK.locked() or not settings(store)['chat_model'] or not state(store)['enabled']:
        return data
    if settings(store).get('writing_provider')=='chatgpt':
        from .chatgpt_gateway import LOCK as gateway_lock
        if gateway_lock.locked(): return data
    def run():
        try:
            build(store,provider,scope)
            ERRORS.pop((provider,scope),None)
        except (ValueError,OSError) as exc:
            ERRORS[(provider,scope)]=(snapshot(store,provider,scope)[1],str(exc)[:300],time.monotonic())
    threading.Thread(target=run,daemon=True).start()
    return {**data,'building':True}
