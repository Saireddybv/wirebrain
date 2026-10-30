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
            prepared.append((ident,created,provider,prompt,response,redact(str(pair.get('project','Inbox')))[:80],str(chat),str(item.get('title') or item.get('name') or prompt)[:120],bool(pair.get('favorite'))))
    validated_notes = []
    from .diary import validate_day
    for note in notes:
        day, body = validate_day(note['day']), note['body']
        if not isinstance(body,str) or len(body)>20000: raise ValueError('Invalid imported note')
        validated_notes.append((day,redact(body),datetime.now(timezone.utc).isoformat()))
    added, links = 0, []
    with store.connect() as db:
        for ident,created,provider,prompt,response,project,chat,title,favorite in prepared:
            if db.execute('SELECT 1 FROM conversations WHERE id=? OR (provider=? AND created=? AND prompt=? AND response=?)',(ident,provider,created,prompt,response)).fetchone(): continue
            db.execute('INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?,?)',(ident,created,provider,'imported',project,prompt,response,'complete',0,0,0))
            db.execute('INSERT INTO memory_fts VALUES (?,?,?,?)',(ident,prompt,response,project))
            db.execute('INSERT INTO entry_flags VALUES (?,?)',(ident,int(favorite)))
            links.append((ident,provider,chat,title)); added += 1
        for note in validated_notes:
            # Preserve a newer personal note on this device.
            db.execute('INSERT OR IGNORE INTO diary_notes VALUES (?,?,?)',note)
    for ident,provider,chat,title in links:
        if chat: store.link_exchange(ident,provider,chat,title=title)
    return {'imported':added,'skipped':len(prepared)-added,'notes':len(validated_notes)}
