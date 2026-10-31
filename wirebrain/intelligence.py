"""Optional local inference. Only the fixed loopback Ollama service receives text."""
from .prompting import render_prompt
import hashlib
import json
import math
import shutil
import threading
import urllib.request
from collections import Counter

from .gateway import NoRedirect
from .store import redact

INDEX_LOCK = threading.Lock()
NATIVE_LOCK = threading.Lock()
NATIVE_MODELS = {}


def native_model(store, download=False):
    import os
    os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
    os.environ.setdefault('HF_HUB_DISABLE_IMPLICIT_TOKEN', '1')
    try:
        from fastembed import TextEmbedding
    except ImportError as exc:
        raise ValueError('Install the optional local-search package: python -m pip install -e ".[memory]"') from exc
    key = str(store.home.resolve())
    with NATIVE_LOCK:
        if key not in NATIVE_MODELS:
            try:
                NATIVE_MODELS[key] = TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir=store.home/'models',
                                                 threads=2, local_files_only=not download)
            except Exception as exc:
                raise ValueError('The small local search model is not ready. Use Enable local search in Local setup to download it first.') from exc
    return NATIVE_MODELS[key]


def prepare_native(store):
    native_model(store, download=True)
    config = settings(store)
    return settings(store, {**config, 'embedding_model':'builtin:bge'})


def local_request(path, payload=None):
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    if payload and payload.get('model'):
        installed = local_request('tags').get('models', [])
        model = next((m for m in installed if m.get('name') == payload['model'] or m.get('model') == payload['model']), None)
        if not model or model.get('remote_host') or model.get('remote_model') or 'cloud' in payload['model'].lower():
            raise ValueError('Choose a locally downloaded Ollama model. Cloud models are not used by Wirebrain.')
    request = urllib.request.Request('http://127.0.0.1:11434/api/' + path,
                                    None if payload is None else json.dumps(payload).encode(),
                                    {'Content-Type': 'application/json'})
    try:
        with opener.open(request, timeout=90 if payload else 3) as response:
            return json.loads(response.read(16 * 1024 * 1024))
    except (OSError, ValueError) as exc:
        raise ValueError('Local AI is unavailable or this model cannot do that task. Open Ollama and check your installed models. Your diary still works without it.') from exc


def settings(store, value=None):
    with store.connect() as db:
        if value is not None:
            clean = {}
            provider = value.get('writing_provider','ollama')
            if provider not in ('ollama','chatgpt'): raise ValueError('Choose local Ollama or ChatGPT sign-in')
            clean['writing_provider'] = provider
            for key in ('embedding_model', 'chat_model'):
                model = value.get(key, '')
                if not isinstance(model, str) or len(model) > 160:
                    raise ValueError('Choose a valid local model')
                if 'cloud' in model.lower():
                    raise ValueError('Choose a locally installed model, not a cloud model')
                clean[key] = model
            if provider == 'chatgpt': clean['chat_model'] = 'chatgpt-default'
            db.execute('INSERT OR REPLACE INTO intelligence_settings VALUES (1,?)', (json.dumps(clean),))
        row = db.execute('SELECT body FROM intelligence_settings WHERE id=1').fetchone()
    return json.loads(row[0]) if row else {'embedding_model': '', 'chat_model': ''}


def writing_request(store, payload):
    if settings(store).get('writing_provider','ollama') == 'chatgpt':
        from .chatgpt_gateway import chat
        return chat(payload['messages'], payload.get('format'))
    return local_request('chat', payload)


def chunks(row):
    text = 'You: ' + row['prompt'] + '\nReply: ' + row['response']
    return [text[i:i+1800] for i in range(0, len(text), 1500)] or ['']


def fingerprint(text):
    return hashlib.sha256(text.encode()).hexdigest()


def vectors(model, texts, store=None):
    if model == 'builtin:bge':
        return [v.tolist() for v in native_model(store).embed(texts)]
    result = local_request('embed', {'model': model, 'input': texts, 'truncate': True})
    values = result.get('embeddings', [])
    if len(values) != len(texts) or any(not isinstance(v, list) or not v or
       any(not isinstance(n, (int, float)) or not math.isfinite(n) for n in v) or
       not any(v) for v in values) or len({len(v) for v in values}) != 1:
        raise ValueError('The local embedding model returned invalid vectors')
    return values


def index_status(store):
    model = settings(store)['embedding_model']
    with store.connect() as db:
        existing = {(r['exchange_id'], r['part']): r['hash'] for r in db.execute(
            'SELECT exchange_id,part,hash FROM memory_vectors WHERE model=?', (model,))}
    needed = [(row, i, text) for row in store.list(limit=1000000) for i, text in enumerate(chunks(row))
              if existing.get((row['id'], i)) != fingerprint(text)]
    return model, needed


def index_batch(store):
    if not INDEX_LOCK.acquire(blocking=False):
        raise ValueError('Memory indexing is already running')
    try:
        model, needed = index_status(store)
        if not model: raise ValueError('Choose an embedding model in Local setup first')
        batch = needed[:32]
        if batch:
            embedded = vectors(model, [item[2] for item in batch], store)
            with store.connect() as db:
                for (row, part, text), vector in zip(batch, embedded):
                    # A deleted/edited memory must not be resurrected by an in-flight request.
                    current = db.execute('SELECT * FROM conversations WHERE id=?', (row['id'],)).fetchone()
                    if not current or part >= len(chunks(current)) or chunks(current)[part] != text: continue
                    db.execute('INSERT OR REPLACE INTO memory_vectors VALUES (?,?,?,?,?)',
                               (row['id'], model, part, fingerprint(text), json.dumps(vector)))
        return {'indexed': len(batch), 'remaining': max(0, len(needed)-len(batch))}
    finally:
        INDEX_LOCK.release()


def search(store, query, mode='keyword', provider='', project='', favorites=False, limit=50,
           date_from=None, date_to=None, offset=0):
    if not isinstance(query, str) or len(query) > 2000: raise ValueError('Search must be under 2,000 characters')
    if mode not in ('keyword', 'semantic'): raise ValueError('Choose keyword or semantic search')
    from .workflows import scope
    filters = scope({'provider':provider,'project':project,'date_from':date_from,'date_to':date_to,'offset':offset})
    rows = store.list(limit=1000000, favorites=favorites, **filters)
    if not query.strip(): return {'rows': rows[:limit], 'mode': 'keyword', 'unindexed': 0}
    allowed = {r['id']: r for r in rows}
    lexical = [r for r in store.list(query, limit=1000000, favorites=favorites) if r['id'] in allowed]
    if mode == 'keyword': return {'rows': lexical[:limit], 'mode': mode, 'unindexed': 0}
    model = settings(store)['embedding_model']
    if not model: raise ValueError('Enable local semantic search in Local setup first')
    query_vector = vectors(model, [query], store)[0]
    scores, indexed = {}, Counter()
    with store.connect() as db:
        for item in db.execute('SELECT * FROM memory_vectors WHERE model=?', (model,)):
            row = allowed.get(item['exchange_id'])
            if not row: continue
            parts = chunks(row)
            if item['part'] >= len(parts) or fingerprint(parts[item['part']]) != item['hash']: continue
            vector = json.loads(item['vector'])
            if len(vector) != len(query_vector): continue
            similarity = sum(a*b for a,b in zip(vector,query_vector)) / (
                math.sqrt(sum(a*a for a in vector))*math.sqrt(sum(a*a for a in query_vector)))
            if similarity > scores.get(row['id'], -1):
                scores[row['id']] = similarity
                row['retrieval_excerpt'] = parts[item['part']]
            indexed[row['id']] += 1
    # Reciprocal-rank fusion retains exact names and identifiers as well as meaning.
    combined = Counter()
    for ranking in (sorted(scores, key=scores.get, reverse=True), [r['id'] for r in lexical]):
        for rank, ident in enumerate(ranking): combined[ident] += 1/(60+rank)
    return {'rows': [allowed[i] for i,_ in combined.most_common(limit)], 'mode': mode,
            'unindexed': sum(indexed[ident] < len(chunks(row)) for ident,row in allowed.items())}


def generate(store, instruction, rows, note='', max_sources=8, memories=None):
    model = settings(store)['chat_model']
    if not model: raise ValueError('Choose a local writing model in Local setup first')
    question_limit, reply_limit = (400,800) if max_sources>8 else (1200,1800)
    excerpts = '\n\n'.join(f'[{i}] {r["created"]} {r["provider"]}\n' + r.get('retrieval_excerpt', 'You: '+r['prompt'][:question_limit]+'\nReply: '+r['response'][:reply_limit])
                             for i,r in enumerate(rows[:max_sources], 1))
    memory_text = '\n'.join(f'[M{i}] {m["text"]}' for i,m in enumerate((memories or [])[:8],1))
    result = writing_request(store, {'model': model, 'stream': False, 'think': False, 'options': {'temperature': .2, 'num_predict': 600},
        'messages': [{'role':'system', 'content': render_prompt('recall.system')},
            {'role':'user','content': render_prompt('recall.context',instruction=instruction,excerpts=excerpts,memories=memory_text,note=note[:2000])}]})
    answer = result.get('message', {}).get('content', '')
    if not isinstance(answer, str) or not answer.strip(): raise ValueError('The local model returned no answer')
    return redact(answer)


def ask(store, payload):
    query = payload.get('query', '')
    if not isinstance(query, str) or not query.strip(): raise ValueError('Ask a question about your memories')
    found = ({'rows':[],'unindexed':0} if payload.get('memory_only') else
             search(store, query, payload.get('mode', 'keyword'), payload.get('provider',''), payload.get('project',''), limit=8))
    rows = found['rows']
    memories = []
    if payload.get('use_personal_memory'):
        from .personal_memory import retrieve
        memories = retrieve(store, query, payload.get('provider',''), payload.get('project',''), payload.get('mode','keyword'))
    if payload.get('memory_only'):
        allowed_sources = {source['exchange_id'] for memory in memories for source in memory['sources']}
        rows = [row for ident in sorted(allowed_sources)[:8] for row in store.list(exchange_id=ident,limit=1)]
    answer = 'No matching memories were found. Try a different phrase or semantic search.'
    if rows or memories:
        answer = (generate(store, render_prompt('recall.question',query=query), rows, memories=memories)
                  if payload.get('generate') else 'These are the matching original conversations. Enable a local writing model to get a source-linked answer.')
    return {'answer':answer, 'sources':rows, 'memories':memories, 'writing_provider':settings(store).get('writing_provider','ollama'), 'generated':bool((rows or memories) and payload.get('generate')), 'unindexed':found['unindexed']}


def overview(store):
    with store.connect() as db:
        count = db.execute('SELECT count(*) FROM conversations').fetchone()[0]
        chats = db.execute('SELECT count(DISTINCT coalesce(e.thread_id,c.id)) FROM conversations c LEFT JOIN exchange_threads e ON e.exchange_id=c.id').fetchone()[0]
        favorites = db.execute('SELECT count(*) FROM entry_flags WHERE favorite=1').fetchone()[0]
        providers = [dict(r) for r in db.execute('SELECT provider,count(*) count FROM conversations GROUP BY provider')]
        projects = [dict(r) for r in db.execute('SELECT project name,count(*) count FROM conversations GROUP BY project ORDER BY project')]
        known = {project['name'] for project in projects}
        for row in db.execute("SELECT DISTINCT scope FROM personal_memory WHERE scope<>'' ORDER BY scope"):
            if row['scope'] not in known:
                projects.append({'name':row['scope'],'count':0})
    size = 0
    for path in store.home.glob('memory.sqlite3*'):
        try: size += path.stat().st_size
        except FileNotFoundError: pass  # SQLite can checkpoint/remove WAL files during this read.
    try:
        free_bytes = shutil.disk_usage(store.home).free
    except OSError:
        free_bytes = None
    return {'moments':count,'conversations':chats,'favorites':favorites,'providers':providers,'projects':projects,'bytes':size,'free_bytes':free_bytes}


def collection(store, ident, name):
    if not isinstance(name,str) or not name.strip() or len(name)>80: raise ValueError('Choose a collection name under 80 characters')
    rows = store.thread(ident)
    if not rows: raise ValueError('Conversation not found')
    name = redact(name.strip())
    with store.connect() as db:
        for row in rows:
            from .personal_memory import invalidate_source
            invalidate_source(db, row['id'])
            db.execute('UPDATE conversations SET project=? WHERE id=?',(name,row['id']))
            db.execute('UPDATE memory_fts SET project=? WHERE id=?',(name,row['id']))
        db.execute('DELETE FROM reflections')
    return {'ok':True,'name':name}
