"""Read-only conversation discovery and portable context, shared by UI and MCP."""
from datetime import datetime, timedelta, timezone

from .workflows import scope
from .prompting import render_prompt


def integer(options, key, default, low, high):
    value = options.get(key, default)
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f'{key} must be an integer from {low} to {high}')
    return value


def selected(store, options):
    rows = store.list(limit=10001, **scope(options))
    if len(rows) > 10000:
        raise ValueError('Narrow the date range or collection to fewer than 10,001 moments')
    minutes = integer(options, 'lookback_minutes', 0, 0, 525600)
    if minutes:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        rows = [r for r in rows if datetime.fromisoformat(r['created'].replace('Z', '+00:00')) >= cutoff]
    return rows


def list_conversations(store, options):
    query = options.get('query', '')
    if not isinstance(query, str) or len(query) > 500:
        raise ValueError('Use a search phrase under 501 characters')
    groups = {}
    for row in selected(store, options):
        key = row['thread_id'] or row['id']
        groups.setdefault(key, []).append(row)
    found = []
    for rows in groups.values():
        if query and not any(query.casefold() in (r['prompt']+'\n'+r['response']+'\n'+(r['thread_title'] or '')).casefold() for r in rows):
            continue
        latest = rows[0]
        found.append({'exchange_id':latest['id'], 'thread_id':latest['thread_id'],
                      'title':latest['thread_title'] or rows[-1]['prompt'][:120],
                      'provider':latest['provider'], 'project':latest['project'],
                      'updated':latest['created'], 'source_url':latest['source_url'],
                      'moments':len(rows)})
    cursor = integer(options, 'cursor', 0, 0, 10000)
    limit = integer(options, 'limit', 20, 1, 50)
    return {'conversations':found[cursor:cursor+limit], 'total':len(found),
            'next_cursor':cursor+limit if cursor+limit < len(found) else None,
            'coverage':'Captured moments matching the selected filters; not uncaptured app history.'}


def conversation_rows(store, options):
    ident = options.get('exchange_id')
    if not isinstance(ident, str) or not ident:
        raise ValueError('Choose a conversation exchange_id from list_conversations')
    rows = selected(store, options)
    anchor = next((r for r in rows if r['id'] == ident), None)
    if not anchor:
        raise ValueError('Conversation not found in this scope')
    return sorted([r for r in rows if (r['thread_id'] == anchor['thread_id'] if anchor['thread_id'] else r['id'] == ident)],
                  key=lambda r:(r['created'], r['id']))


def read_conversation(store, options):
    rows = conversation_rows(store, options)
    cursor = integer(options, 'cursor', 0, 0, 10000)
    limit = integer(options, 'limit', 5, 1, 10)
    items = []
    for row in rows[cursor:cursor+limit]:
        items.append({k:row[k] for k in ('id','created','provider','project','status','source_url','message_id','parent_message_id','response_message_id')} | {
            'prompt':row['prompt'][:6000], 'response':row['response'][:12000],
            'prompt_characters':len(row['prompt']), 'response_characters':len(row['response']),
            'excerpted':len(row['prompt'])>6000 or len(row['response'])>12000})
    return {'moments':items, 'total':len(rows),
            'next_cursor':cursor+limit if cursor+limit<len(rows) else None,
            'coverage':'Captured turns in chronological order. Use read_memory to page any excerpted text. Branches are preserved as captured, not inferred as one linear dialogue.'}


def conversation_handoff(store, options):
    rows = conversation_rows(store, options)
    recent = rows[-20:]
    lines = ['# Continue this conversation', '', render_prompt('reports.handoff_recipient'), '',
             f'Included the latest {len(recent)} of {len(rows)} captured moments matching these filters.',
             'Prompts are limited to 1,200 characters and replies to 2,400 characters per moment. This is a source excerpt, not an AI summary.', '']
    for row in recent:
        lines += [f"## {row['created']} · {row['provider']} · {row['project']}",
                  f"Source ID: {row['id']} · Capture status: {row['status']}",
                  f"Message ID: {row['message_id'] or 'unknown'} · Parent message: {row['parent_message_id'] or 'unknown'}"]
        if row['source_url']: lines += ['Original chat: '+row['source_url']]
        for label, key, bound in (('User','prompt',1200), ('Assistant','response',2400)):
            text = row[key]
            lines += ['', '### '+label, '', text[:bound] or '(No text captured)']
            if len(text)>bound: lines += [f'[Excerpt: {bound} of {len(text)} characters; read_memory can retrieve the remainder.]']
        lines += ['']
    return {'body':'\n'.join(lines), 'filename':'wirebrain-context.md', 'included':len(recent),
            'total':len(rows), 'sources':[{'id':r['id'],'provider':r['provider'],'created':r['created']} for r in recent]}
