"""Portable text-only conversational datasets, without invented system prompts."""
import itertools
import json


def records(store, provider='', project=''):
    # Iterate the archive without the UI's pagination limit. Only hold one thread.
    with store.connect() as db:
        sql = """SELECT c.*, e.thread_id,e.message_id,e.parent_message_id,e.response_message_id
                 FROM conversations c LEFT JOIN exchange_threads e ON e.exchange_id=c.id
                 WHERE c.demo=0 AND c.status='complete' AND trim(c.prompt)<>'' AND trim(c.response)<>''"""
        args = []
        if provider:
            aliases = {'chatgpt': ('chatgpt','openai'), 'claude': ('claude','anthropic')}
            sources = aliases.get(provider, (provider,))
            sql += ' AND c.provider IN (' + ','.join('?' for _ in sources) + ')'
            args.extend(sources)
        if project:
            sql += ' AND c.project=?'
            args.append(project)
        sql += ' ORDER BY coalesce(e.thread_id,c.id), c.created,c.rowid'
        rows = (dict(row) for row in db.execute(sql, args))
        for _, group in itertools.groupby(rows, key=lambda r: r['thread_id'] or r['id']):
            turns = list(group)
            paths, responses, used = [], {}, set()
            for row in turns:
                parent = row['parent_message_id']
                predecessor = responses.get(parent)
                # Without parent IDs use recorded chronology. An unknown explicit
                # parent starts a separate fragment instead of guessing its history.
                if not parent and paths:
                    predecessor = len(paths)-1
                if predecessor is not None:
                    used.add(predecessor)
                paths.append(predecessor)
                if row['response_message_id']:
                    responses[row['response_message_id']] = len(paths)-1
            for index in range(len(paths)):
                if index not in used:
                    chain = []
                    while index is not None:
                        chain.append(turns[index])
                        index = paths[index]
                    messages = []
                    for row in reversed(chain):
                        messages.extend([{'role':'user','content':row['prompt']},
                                         {'role':'assistant','content':row['response']}])
                    yield {'messages': messages}


def jsonl(store, provider='', project=''):
    for record in records(store, provider, project):
        yield (json.dumps(record, ensure_ascii=False, separators=(',', ':'))+'\n').encode('utf-8')
