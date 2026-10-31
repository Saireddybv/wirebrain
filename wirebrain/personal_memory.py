"""Source-linked, reviewed personal facts. Extraction only uses local Ollama."""
from .prompting import render_prompt, load_schema
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re
import threading
import uuid

from .store import redact

LOCK = threading.Lock()
KINDS = ('preference', 'fact', 'decision', 'goal', 'topic')
DEFAULT_COLLECTIONS = ('Inbox', 'Web conversations')
SCHEMA = load_schema('memory.extract')


def now():
    return datetime.now(timezone.utc).isoformat()


def eligible_prompt(text):
    plain = re.sub(r'[^\w\s]', ' ', text.casefold()).strip()
    words = plain.split()
    if re.search(r'\bwirebrain\b.*\b(test|verification|check)\b', plain): return False
    if plain in ('who are you','what are you doing','whats you doing there','whats you doinng today'): return False
    if re.fullmatch(r'i am (doramon|doremon|doraemon)',plain): return False
    if len(words)<=12 and re.match(r'^(hi|hello|hey)\b',plain) and not re.search(r'\b(prefer|remember|learning|decided|goal)\b',plain): return False
    return len(plain)>=8


def key(text, scope):
    normalized = re.sub(r'\W+', ' ', text.casefold()).strip()
    return hashlib.sha256((scope + '\0' + normalized).encode()).hexdigest()


def validate(text, kind='fact', scope=''):
    if not isinstance(text, str) or not 3 <= len(text.strip()) <= 600:
        raise ValueError('Write a memory between 3 and 600 characters')
    if kind not in KINDS or not isinstance(scope, str) or len(scope) > 80:
        raise ValueError('Choose a valid memory type and collection')
    clean = redact(text.strip())
    if clean != text.strip() or '[REDACTED]' in clean:
        raise ValueError('Remove secrets from the memory before saving it')
    return clean, kind, redact(scope.strip())


def state(store, changes=None):
    with store.connect() as db:
        row = db.execute('SELECT body FROM personal_memory_state WHERE id=1').fetchone()
        value = {'enabled': False, 'last_run': '', 'error': '', **(json.loads(row[0]) if row else {})}
        if changes is not None:
            value.update(changes)
            db.execute('INSERT OR REPLACE INTO personal_memory_state VALUES (1,?)', (json.dumps(value),))
    return {**value, 'running': LOCK.locked()}


def invalidate_source(db, ident):
    """Remove derived content before a source is deleted, edited, or moved."""
    ids = [row[0] for row in db.execute('SELECT memory_id FROM personal_memory_sources WHERE exchange_id=?', (ident,))]
    # Conservatively remove the whole derived fact, including its old text/history.
    for memory_id in ids:
        db.execute('DELETE FROM personal_memory_sources WHERE memory_id=?', (memory_id,))
        db.execute('DELETE FROM personal_memory_versions WHERE memory_id=?', (memory_id,))
        db.execute('DELETE FROM personal_memory_vectors WHERE memory_id=?', (memory_id,))
        db.execute('DELETE FROM personal_memory WHERE id=?', (memory_id,))
    db.execute('DELETE FROM personal_memory_inputs WHERE exchange_id=?', (ident,))


def save(store, payload):
    text, kind, scope = validate(payload.get('text'), payload.get('kind', 'fact'), payload.get('scope', ''))
    ident = payload.get('id')
    if ident is not None and (not isinstance(ident, str) or len(ident) > 100):
        raise ValueError('Choose a valid memory')
    stamp, digest = now(), key(text, scope)
    with store.connect() as db:
        old = db.execute('SELECT * FROM personal_memory WHERE id=?', (ident,)).fetchone() if ident else None
        if ident and not old:
            raise ValueError('Memory no longer exists')
        duplicate = db.execute('SELECT id FROM personal_memory WHERE fact_key=?', (digest,)).fetchone()
        if duplicate and duplicate['id'] != ident:
            raise ValueError('This memory already exists in that scope')
        if old:
            db.execute('DELETE FROM personal_memory_vectors WHERE memory_id=?', (ident,))
            db.execute('INSERT INTO personal_memory_versions VALUES (?,?,?,?)', (ident, old['text'], old['scope'], old['updated']))
            if old['fact_key'] != digest:
                db.execute('INSERT OR IGNORE INTO personal_memory_blocks VALUES (?)', (old['fact_key'],))
            db.execute('UPDATE personal_memory SET fact_key=?,text=?,kind=?,scope=?,status=?,updated=? WHERE id=?',
                       (digest, text, kind, scope, 'approved', stamp, ident))
        else:
            ident = str(uuid.uuid4())
            db.execute('INSERT INTO personal_memory VALUES (?,?,?,?,?,?,?,?)', (ident, digest, text, kind, scope, 'approved', stamp, stamp))
        # Only an explicit user save can bring back a forgotten fact.
        db.execute('DELETE FROM personal_memory_blocks WHERE fact_key=?', (digest,))
    return {'ok': True, 'id': ident}


def action(store, payload):
    ident, operation = payload.get('id'), payload.get('action')
    if not isinstance(ident, str) or operation not in ('approve', 'forget'):
        raise ValueError('Choose a memory and approve or forget')
    with store.connect() as db:
        row = db.execute('SELECT * FROM personal_memory WHERE id=?', (ident,)).fetchone()
        if not row:
            raise ValueError('Memory no longer exists')
        if operation == 'approve':
            db.execute('UPDATE personal_memory SET status=?,updated=? WHERE id=?', ('approved', now(), ident))
        else:
            db.execute('INSERT OR IGNORE INTO personal_memory_blocks VALUES (?)', (row['fact_key'],))
            for source in db.execute('SELECT exchange_id FROM personal_memory_sources WHERE memory_id=?', (ident,)).fetchall():
                db.execute('INSERT OR IGNORE INTO personal_memory_exclusions VALUES (?)', (source[0],))
            db.execute('DELETE FROM personal_memory_sources WHERE memory_id=?', (ident,))
            db.execute('DELETE FROM personal_memory_versions WHERE memory_id=?', (ident,))
            db.execute('DELETE FROM personal_memory_vectors WHERE memory_id=?', (ident,))
            db.execute('DELETE FROM personal_memory WHERE id=?', (ident,))
    return {'ok': True}


def list_memories(store, query='', provider='', scope=None, status='approved', limit=200):
    if not isinstance(query, str) or len(query) > 2000 or status not in ('approved', 'suggested','all'):
        raise ValueError('Choose a valid memory query and status')
    if scope is not None and (not isinstance(scope, str) or len(scope) > 80):
        raise ValueError('Choose a valid collection')
    aliases = {'chatgpt': ('chatgpt', 'openai'), 'claude': ('claude', 'anthropic')}.get(provider, (provider,))
    args = [] if status in ('approved','all') else [status]
    sql = ('SELECT m.* FROM personal_memory m WHERE 1=1' if status=='all' else
           "SELECT m.* FROM personal_memory m WHERE status IN ('approved','automatic')" if status=='approved' else
           'SELECT m.* FROM personal_memory m WHERE status=?')
    if scope is not None:
        sql += ' AND scope=?'
        args.append(scope)
    if provider:
        sql += ' AND EXISTS (SELECT 1 FROM personal_memory_sources s JOIN conversations c ON c.id=s.exchange_id WHERE s.memory_id=m.id AND c.provider IN (' + ','.join('?' for _ in aliases) + '))'
        args.extend(aliases)
    with store.connect() as db:
        candidates = [dict(row) for row in db.execute(sql + ' ORDER BY updated DESC,id DESC', args)]
        # FTS-like token matching without allowing a query to alter SQL.
        tokens = re.findall(r'\w+', query.casefold())
        ranked = [(sum(token in row['text'].casefold() for token in tokens), row) for row in candidates]
        if tokens:
            ranked = sorted((item for item in ranked if item[0]), key=lambda item: item[0], reverse=True)
        rows = [row for _, row in ranked[:min(limit, 2000)]]
        for row in rows:
            row.pop('fact_key')
            row['sources'] = [dict(source) for source in db.execute(
                'SELECT s.exchange_id,s.quote,c.provider,c.created,c.project FROM personal_memory_sources s JOIN conversations c ON c.id=s.exchange_id WHERE s.memory_id=?', (row['id'],))]
            row['history'] = [dict(version) for version in db.execute('SELECT text,scope,updated FROM personal_memory_versions WHERE memory_id=? ORDER BY updated DESC LIMIT 10', (row['id'],))]
    return rows


def extract_batch(store, force=False, limit=2):
    """Use changed, idle, completed user messages; never extract from AI replies."""
    if not LOCK.acquire(blocking=False):
        raise ValueError('Memory extraction is already running')
    try:
        from .intelligence import settings, writing_request, fingerprint
        current_state = state(store)
        if not force:
            if not current_state['enabled']:
                return {'processed': 0, 'suggested': 0}
            if current_state['error'] and current_state['last_run'] and datetime.fromisoformat(current_state['last_run']) > datetime.now(timezone.utc)-timedelta(minutes=10):
                return {'processed': 0, 'suggested': 0}
        model = settings(store)['chat_model']
        if not model:
            raise ValueError('Select a local Ollama writing model in Local setup to extract memory. Manual memories work without a model.')
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        with store.connect() as db:
            rows = [dict(row) for row in db.execute('''SELECT c.*,q.revision queue_revision FROM personal_memory_queue q JOIN conversations c ON c.id=q.exchange_id
                LEFT JOIN personal_memory_exclusions x ON x.exchange_id=c.id
                WHERE x.exchange_id IS NULL AND c.status='complete' AND c.demo=0 AND c.created<?
                AND NOT EXISTS (SELECT 1 FROM exchange_threads mine JOIN exchange_threads other ON other.thread_id=mine.thread_id
                    JOIN conversations newer ON newer.id=other.exchange_id WHERE mine.exchange_id=c.id
                    AND (newer.created>=? OR newer.status='streaming'))
                ORDER BY c.created DESC LIMIT 32''', (cutoff, cutoff))]
            processed = {row['exchange_id']: row['fingerprint'] for row in db.execute('SELECT i.* FROM personal_memory_inputs i JOIN personal_memory_queue q ON q.exchange_id=i.exchange_id')}
        todo = []
        for row in rows:
            digest = fingerprint(row['prompt'] + '\0' + row['project'])
            if processed.get(row['id']) != digest:
                todo.append((row, digest))
                if len(todo) >= limit:
                    break
            else:
                with store.connect() as db:
                    db.execute('DELETE FROM personal_memory_queue WHERE exchange_id=? AND revision=?', (row['id'],row['queue_revision']))
        added = 0
        for source, digest in todo:
            prompt = source['prompt'][:5000]
            if not eligible_prompt(prompt):
                with store.connect() as db:
                    current = db.execute('SELECT prompt,project FROM conversations WHERE id=?',(source['id'],)).fetchone()
                    if current and fingerprint(current['prompt']+'\0'+current['project'])==digest:
                        db.execute('INSERT OR REPLACE INTO personal_memory_inputs VALUES (?,?,?)',(source['id'],digest,model))
                        db.execute('DELETE FROM personal_memory_queue WHERE exchange_id=? AND revision=?',(source['id'],source['queue_revision']))
                continue
            result = writing_request(store, {'model': model, 'stream': False, 'think': False,
                'format': SCHEMA, 'options': {'temperature': 0, 'num_predict': 900},
                'messages': [
                    {'role': 'system', 'content': render_prompt('memory.extract',schema=json.dumps(SCHEMA))},
                    {'role': 'user', 'content': json.dumps({'quoted_human_message': prompt})}]})
            try:
                data = json.loads(result.get('message', {}).get('content', ''))
            except (ValueError, TypeError):
                raise ValueError('The local model returned invalid memory JSON; no extraction progress was saved') from None
            if not isinstance(data, dict) or not isinstance(data.get('memories'), list) or len(data['memories']) > 4:
                raise ValueError('The local model returned an invalid memory list')
            clean = []
            for candidate in data['memories']:
                if not isinstance(candidate, dict):
                    raise ValueError('The local model returned an invalid memory')
                text, kind, scope = validate(candidate.get('text'), candidate.get('kind'),
                    '' if source['project'] in DEFAULT_COLLECTIONS else source['project'])
                quote = candidate.get('quote')
                if not isinstance(quote, str) or not 8 <= len(quote) <= 600 or quote not in prompt or redact(quote) != quote or '[REDACTED]' in quote:
                    raise ValueError('The local model returned a memory without valid evidence')
                clean.append((text, kind, scope, quote))
            with store.connect() as db:
                # Recheck inside the transaction so deletion/exclusion cannot be raced.
                current = db.execute('SELECT * FROM conversations WHERE id=?', (source['id'],)).fetchone()
                if not current or current['status'] != 'complete' or fingerprint(current['prompt'] + '\0' + current['project']) != digest:
                    continue
                if db.execute('SELECT 1 FROM personal_memory_exclusions WHERE exchange_id=?', (source['id'],)).fetchone():
                    continue
                for text, kind, scope, quote in clean:
                    fact_key = key(text, scope)
                    if db.execute('SELECT 1 FROM personal_memory_blocks WHERE fact_key=?', (fact_key,)).fetchone():
                        continue
                    existing = db.execute('SELECT id FROM personal_memory WHERE fact_key=?', (fact_key,)).fetchone()
                    ident = existing['id'] if existing else str(uuid.uuid4())
                    if not existing:
                        stamp = now()
                        automatic = kind=='topic' and bool(re.match(r'^(Asked|Explored|Discussed)\b',text,re.IGNORECASE))
                        db.execute('INSERT INTO personal_memory VALUES (?,?,?,?,?,?,?,?)', (ident, fact_key, text, kind, scope, 'automatic' if automatic else 'suggested', stamp, stamp))
                        added += 1
                    db.execute('INSERT OR IGNORE INTO personal_memory_sources VALUES (?,?,?)', (ident, source['id'], quote))
                db.execute('INSERT OR REPLACE INTO personal_memory_inputs VALUES (?,?,?)', (source['id'], digest, model))
                db.execute('DELETE FROM personal_memory_queue WHERE exchange_id=? AND revision=?', (source['id'],source['queue_revision']))
        state(store, {'error': '', 'last_run': now()})
        return {'processed': len(todo), 'suggested': added}
    except Exception as exc:
        state(store, {'error': str(exc)[:500], 'last_run': now()})
        raise
    finally:
        LOCK.release()


def start_extraction(store):
    from .intelligence import settings
    if not settings(store)['chat_model']:
        raise ValueError('Choose a local Ollama writing model in Local setup first')
    if LOCK.locked():
        return state(store)
    def run():
        try:
            extract_batch(store, force=True)
        except Exception:
            pass  # Error is persisted and shown in Memory, not silently discarded.
    threading.Thread(target=run, daemon=True).start()
    return state(store)


def index_facts(store):
    from .intelligence import settings, vectors, fingerprint
    model = settings(store)['embedding_model']
    if not model:
        return
    with store.connect() as db:
        cached = {row['memory_id']: row for row in db.execute('SELECT * FROM personal_memory_vectors')}
        rows = [dict(row) for row in db.execute("SELECT * FROM personal_memory WHERE status IN ('approved','automatic')")]
    changed = [row for row in rows if row['id'] not in cached or cached[row['id']]['model'] != model or cached[row['id']]['hash'] != fingerprint(row['text'])][:32]
    if not changed:
        return
    embedded = vectors(model, [row['text'] for row in changed], store)
    with store.connect() as db:
        for row, vector in zip(changed, embedded):
            current = db.execute("SELECT text FROM personal_memory WHERE id=? AND status IN ('approved','automatic')", (row['id'],)).fetchone()
            if current and current['text'] == row['text']:
                db.execute('INSERT OR REPLACE INTO personal_memory_vectors VALUES (?,?,?,?)',
                    (row['id'], model, fingerprint(row['text']), json.dumps(vector)))


def retrieve(store, query, provider='', scope='', mode='keyword'):
    """Only reviewed facts in the exact requested scope enter an LLM or MCP context."""
    from .intelligence import settings, vectors, fingerprint
    if mode not in ('keyword', 'semantic'): raise ValueError('Choose keyword or semantic recall')
    lexical = list_memories(store, query, provider, scope, limit=200)
    ranking = {row['id']: 1 / (60 + i) for i, row in enumerate(lexical)}
    candidates = {row['id']: row for row in list_memories(store, '', provider, scope, limit=2000)}
    candidates.update({row['id']: row for row in lexical})
    model = settings(store)['embedding_model']
    if mode == 'semantic' and model and candidates:
        import math
        query_vector = vectors(model, [query], store)[0]
        scores = []
        with store.connect() as db:
            for cached in db.execute('SELECT * FROM personal_memory_vectors WHERE model=?', (model,)):
                row = candidates.get(cached['memory_id'])
                if not row or cached['hash'] != fingerprint(row['text']):
                    continue
                vector = json.loads(cached['vector'])
                if len(vector) != len(query_vector):
                    continue
                score = sum(a*b for a,b in zip(vector, query_vector)) / (math.sqrt(sum(a*a for a in vector))*math.sqrt(sum(b*b for b in query_vector)))
                if score >= .3:
                    scores.append((score, row['id']))
        for rank, (_, ident) in enumerate(sorted(scores, reverse=True)):
            ranking[ident] = ranking.get(ident, 0) + 1 / (60 + rank)
    return [{k: v for k,v in candidates[ident].items() if k != 'history'}
            for ident in sorted(ranking, key=ranking.get, reverse=True)[:8] if ident in candidates]


def export_memories(store):
    with store.connect() as db:
        facts = [dict(row) for row in db.execute('SELECT * FROM personal_memory')]
        for fact in facts:
            fact.pop('fact_key')
            fact['sources'] = [dict(row) for row in db.execute('SELECT exchange_id,quote FROM personal_memory_sources WHERE memory_id=?', (fact['id'],))]
            fact['history'] = [dict(row) for row in db.execute('SELECT text,scope,updated FROM personal_memory_versions WHERE memory_id=?', (fact['id'],))]
        return {'facts':facts,'blocks':[row[0] for row in db.execute('SELECT fact_key FROM personal_memory_blocks')],
                'exclusions':[row[0] for row in db.execute('SELECT x.exchange_id FROM personal_memory_exclusions x JOIN conversations c ON c.id=x.exchange_id')]}


def validate_import(data, originals):
    """Validate the complete memory backup before any imported conversations are written."""
    if not isinstance(data, dict) or any(not isinstance(data.get(k, []), list) for k in ('facts','blocks','exclusions')):
        raise ValueError('Invalid personal memory backup')
    prepared = []
    for item in data.get('facts', []):
        if not isinstance(item, dict): raise ValueError('Invalid imported memory')
        text, kind, scope = validate(item.get('text'), item.get('kind'), item.get('scope'))
        if item.get('status') not in ('approved', 'suggested','automatic'): raise ValueError('Invalid imported memory status')
        sources, history = item.get('sources', []), item.get('history', [])
        if not isinstance(sources, list) or not isinstance(history, list): raise ValueError('Invalid imported memory evidence')
        for source in sources:
            if not isinstance(source, dict) or source.get('exchange_id') not in originals:
                raise ValueError('An imported personal memory has no source conversation')
            quote = source.get('quote')
            if not isinstance(quote, str) or not 8 <= len(quote) <= 600 or quote not in originals[source['exchange_id']]:
                raise ValueError('Invalid imported memory source quote')
            if redact(quote) != quote or '[REDACTED]' in quote: raise ValueError('Remove secrets from memory evidence')
        for version in history:
            if not isinstance(version, dict): raise ValueError('Invalid memory edit history')
            validate(version.get('text'), 'fact', version.get('scope'))
            if not isinstance(version.get('updated'),str) or len(version['updated'])>60: raise ValueError('Invalid memory history date')
        prepared.append({'text':text,'kind':kind,'scope':scope,'status':item['status'],'sources':sources,'history':history})
    for digest in data.get('blocks', []):
        if not isinstance(digest, str) or not re.fullmatch('[0-9a-f]{64}', digest): raise ValueError('Invalid forgotten-memory marker')
    if any(not isinstance(ident,str) or ident not in originals for ident in data.get('exclusions', [])):
        raise ValueError('Invalid memory exclusion')
    return {**data, 'facts':prepared}


def restore_memories(db, data, identifiers):
    for digest in data.get('blocks', []): db.execute('INSERT OR IGNORE INTO personal_memory_blocks VALUES (?)', (digest,))
    for original in data.get('exclusions', []):
        db.execute('INSERT OR IGNORE INTO personal_memory_exclusions VALUES (?)', (identifiers[original],))
    for fact in data.get('facts', []):
        digest = key(fact['text'], fact['scope'])
        # A local decision to forget or edit wins over an older imported backup.
        if db.execute('SELECT 1 FROM personal_memory_blocks WHERE fact_key=?', (digest,)).fetchone(): continue
        existing = db.execute('SELECT id FROM personal_memory WHERE fact_key=?', (digest,)).fetchone()
        if existing: continue
        ident, stamp = str(uuid.uuid4()), now()
        db.execute('INSERT INTO personal_memory VALUES (?,?,?,?,?,?,?,?)',
            (ident,digest,fact['text'],fact['kind'],fact['scope'],fact['status'],stamp,stamp))
        for source in fact['sources']:
            db.execute('INSERT OR IGNORE INTO personal_memory_sources VALUES (?,?,?)', (ident,identifiers[source['exchange_id']],source['quote']))
        for version in fact['history']:
            db.execute('INSERT INTO personal_memory_versions VALUES (?,?,?,?)', (ident,version['text'],version['scope'],version['updated']))
