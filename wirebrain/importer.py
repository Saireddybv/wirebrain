"""Explicit JSON imports; never read a browser profile or another app's files."""
import hashlib
from datetime import datetime, timezone

from .store import content_text, redact
from .webcapture import history_pairs


def import_history(store, data):
    notes = data.get('notes', []) if isinstance(data, dict) and data.get('format') == 'wirebrain-diary-v1' else []
    items = data.get('memories') if isinstance(data, dict) else data
    if not isinstance(items, list): raise ValueError('Choose a Wirebrain export, ChatGPT conversations.json, or Claude conversations.json file')
    prepared = []
    exported_snippets = data.get('snippets',[]) if isinstance(data,dict) and data.get('format')=='wirebrain-diary-v1' else []
    for item in items:
        if not isinstance(item, dict): raise ValueError('Invalid conversation in JSON file')
        if 'mapping' in item:
            provider, pairs = 'chatgpt', history_pairs(item)
            chat = item.get('id', item.get('conversation_id', ''))
        elif isinstance(item.get('chat_messages'), list):
            provider, pairs, pending = 'claude', [], None
            chat = item.get('uuid', '')
            for message in item['chat_messages']:
                text = content_text(message.get('text') or message.get('content', []))
                if message.get('sender') == 'human': pending = {'prompt':text,'created':message.get('created_at'),'message_id':message.get('uuid','')}
                elif message.get('sender') == 'assistant' and pending:
                    pairs.append({**pending,'response':text}); pending = None
        elif isinstance(item.get('prompt'), str) and isinstance(item.get('response'), str):
            provider, pairs = str(item.get('provider','imported')), [item]
            chat = item.get('conversation_id', '')
        else: raise ValueError('Unrecognized conversation format; no memories were imported')
        for pair in pairs:
            created = pair.get('created')
            if isinstance(created, (float,int)): created = datetime.fromtimestamp(created, timezone.utc).isoformat()
            try:
                parsed = datetime.fromisoformat(created.replace('Z','+00:00'))
                created = (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc).isoformat()
            except (ValueError,TypeError,AttributeError):
                raise ValueError('A conversation has an invalid date; no memories were imported')
            prompt, response = redact(pair['prompt']), redact(pair['response'])
            ident = 'import-' + hashlib.sha256((provider+'\0'+str(chat)+'\0'+created+'\0'+prompt+'\0'+response).encode()).hexdigest()
            prepared.append((ident,created,provider,prompt,response,redact(str(pair.get('project','Inbox')))[:80],str(chat),str(item.get('thread_title') or item.get('title') or item.get('name') or prompt)[:120],bool(pair.get('favorite')),str(pair.get('id','')),pair))
    validated_notes = []
    from .diary import validate_day
    for note in notes:
        day, body = validate_day(note['day']), note['body']
        if not isinstance(body,str) or len(body)>20000: raise ValueError('Invalid imported note')
        validated_notes.append((day,redact(body),datetime.now(timezone.utc).isoformat()))
    from .workflows import validate_snippet
    original_ids = {row[9] for row in prepared if row[9]}
    validated_snippets = []
    for snippet in exported_snippets:
        values = validate_snippet(snippet)
        if snippet.get('exchange_id') not in original_ids: raise ValueError('An imported snippet has no source memory')
        validated_snippets.append((snippet['exchange_id'],values))
    for row in prepared:
        pair = row[10]
        for key in ('input_tokens','output_tokens'):
            value = pair.get(key,0)
            if isinstance(value,bool) or not isinstance(value,int) or value<0: raise ValueError('Invalid imported token usage')
        if pair.get('status','complete') not in ('complete','streaming','interrupted','error','partial'): raise ValueError('Invalid imported capture status')
    added, links, identifiers = 0, [], {}
    with store.connect() as db:
        for ident,created,provider,prompt,response,project,chat,title,favorite,original_id,pair in prepared:
            existing = db.execute('SELECT id FROM conversations WHERE id=? OR (provider=? AND created=? AND prompt=? AND response=?)',(ident,provider,created,prompt,response)).fetchone()
            identifiers[original_id] = existing['id'] if existing else ident
            if existing: continue
            db.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                       (ident,created,provider,redact(str(pair.get('model','imported'))),project,prompt,response,pair.get('status','complete'),pair.get('input_tokens',0),pair.get('output_tokens',0),int(bool(pair.get('demo')))))
            db.execute('INSERT INTO memory_fts VALUES (?,?,?,?)',(ident,prompt,response,project))
            db.execute('INSERT INTO entry_flags VALUES (?,?)',(ident,int(favorite)))
            if pair.get('usage_reported',pair.get('input_tokens',0)>0 or pair.get('output_tokens',0)>0):
                db.execute('INSERT INTO usage_metadata VALUES (?,1,?,?)',
                           (ident,int(bool(pair.get('input_reported',pair.get('input_tokens',0)>0))),int(bool(pair.get('output_reported',pair.get('output_tokens',0)>0)))))
            links.append((ident,provider,chat,title)); added += 1
        for original_id,values in validated_snippets:
            source = identifiers[original_id]
            key = hashlib.sha256((source+'\0'+values['content']).encode()).hexdigest()
            db.execute('INSERT OR IGNORE INTO saved_snippets VALUES (?,?,?,?,?,?)',
                       (key,source,values['title'],values['content'],values['language'],datetime.now(timezone.utc).isoformat()))
        for note in validated_notes:
            # Preserve a newer personal note on this device.
            db.execute('INSERT OR IGNORE INTO diary_notes VALUES (?,?,?)',note)
    for ident,provider,chat,title in links:
        if chat: store.link_exchange(ident,provider,chat,title=title)
    return {'imported':added,'skipped':len(prepared)-added,'notes':len(validated_notes),'snippets':len(validated_snippets)}
