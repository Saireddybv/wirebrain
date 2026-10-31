"""Evidence-based personal workflows. Reports never run recorded code or send messages."""
from .prompting import render_prompt
import difflib
import hashlib
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from .diary import validate_day
from .store import redact

REPORTS = {'weekly':'Weekly reflection', 'standup':'Standup notes', 'study':'Study guide',
           'timeline':'Project timeline', 'research':'Research sourcebook', 'handoff':'Context handoff'}
STOP = set('a an the and or of in on to for from with without is are was were be been do does did '
           'i me my we our you your it its this that these those as at by can could would should '
           'will how what why when where which who explain help please tell about give make use '
           'using want need know like just also have has had not now then than more some any all '
           'hello hi hey thanks thank okay yes test testing reply message question today'.split())


def scope(options):
    if not isinstance(options, dict): raise ValueError('Expected workflow options')
    result = {}
    for key in ('provider','project','model'):
        value = options.get(key, '')
        if not isinstance(value,str) or len(value)>200: raise ValueError('Invalid '+key+' filter')
        result[key] = value
    for key in ('date_from','date_to'):
        value = options.get(key) or None
        if value: validate_day(value)
        result[key] = value
    if bool(result['date_from']) != bool(result['date_to']): raise ValueError('Choose both a start and an end date')
    if result['date_from']:
        span = (datetime.fromisoformat(result['date_to'])-datetime.fromisoformat(result['date_from'])).days
        if not 0 <= span <= 365: raise ValueError('Choose a date range between one day and one year')
    offset = options.get('offset',0)
    if isinstance(offset,bool) or not isinstance(offset,(int,str)): raise ValueError('Invalid timezone offset')
    offset = int(offset)
    if not -840 <= offset <= 840: raise ValueError('Invalid timezone offset')
    result['day_offset'] = offset
    return result


def select(store, options, limit=2000):
    rows = store.list(limit=limit+1, **scope(options))
    if len(rows)>limit: raise ValueError('Too many memories for one report. Narrow the date range or collection.')
    return list(reversed(rows))


def notes_for(store, options):
    chosen = scope(options)
    # Notes have no provider/project association; do not mix them into isolated project reports.
    if chosen['project'] or chosen['provider'] or chosen['model']: return []
    with store.connect() as db:
        sql, args = "SELECT day,body FROM diary_notes WHERE body<>''", []
        if chosen['date_from']:
            sql += ' AND day>=? AND day<=?'
            args = [chosen['date_from'],chosen['date_to']]
        return [dict(row) for row in db.execute(sql+' ORDER BY day',args)]


def learning(rows, offset=0):
    topics = defaultdict(list)
    for row in rows:
        prompt = re.sub(r'(?m)^(?:user|assistant|system|instructions):\s*','',row['prompt'])
        words = [w.lower() for w in re.findall(r'[\w][\w.+#-]*',prompt,re.UNICODE)
                 if len(w)>2 and w.lower() not in STOP and not w.isdigit()]
        # Count once per captured prompt. Repetition is evidence of revisiting, not lack of understanding.
        candidates = set(words) | {' '.join(words[i:i+2]) for i in range(len(words)-1)}
        for word in candidates: topics[word].append(row)
    repeated = sorted(((word,items) for word,items in topics.items() if len(items)>=2),
                      key=lambda item:(-len(item[1]),-len(item[0].split()),item[0]))
    result = []
    for word,items in repeated:
        if any(word in topic['topic'].split() and len(items)<=topic['count'] for topic in result): continue
        days = sorted({(datetime.fromisoformat(r['created'].replace('Z','+00:00'))+timedelta(minutes=offset)).date().isoformat() for r in items})
        result.append({'topic':word,'count':len(items),'days':days,'sources':[r['id'] for r in items[:8]],
                       'suggestion':f'You returned to “{word}” in {len(items)} captured prompts. Try explaining one answer in your own words, then check the source.'})
        if len(result)==8: break
    return result


def report(store, options):
    kind = options.get('kind','weekly')
    if kind not in REPORTS: raise ValueError('Choose a supported report type')
    generated = options.get('generate',False)
    if not isinstance(generated,bool): raise ValueError('Local writing must be true or false')
    rows, notes = select(store,options), notes_for(store,options)
    selection_total = len(rows)
    if kind == 'handoff': rows = rows[-20:]
    chosen = scope(options)
    period = f"{chosen['date_from']} → {chosen['date_to']}" if chosen['date_from'] else 'All recorded days'
    title = 'Research synthesis' if generated and kind=='research' else REPORTS[kind]
    lines = [f'# {title}', '', period, '',
             'Based on captured conversations only. Questions do not prove completed work or a knowledge gap.', '',
             f"{len(rows)} moments · {len({r['thread_id'] or r['id'] for r in rows})} conversations", '']
    if kind == 'handoff':
        lines += [f'Context packet: {len(rows)} most recent moments out of {selection_total} in this selection. Each question/reply is excerpted to keep the packet manageable. Read the originals for full text.','']
    if chosen['project']: lines += ['Collection: '+chosen['project'],'']
    topics = learning(rows,chosen['day_offset'])
    if kind == 'weekly':
        lines += ['## Topics you returned to','']
        lines += [f"- {t['topic']}: {t['count']} captured prompts over {len(t['days'])} day(s)." for t in topics] or ['No repeated topics found in this selection.']
        lines += ['', 'These are recurring topics, not a diagnosis of what you do or do not know.', '']
    if kind == 'standup':
        lines += ['## Explored in recorded conversations','']
        lines += [f"- [{i}] {r['prompt'][:300].replace(chr(10),' ')}" for i,r in enumerate(rows,1)]
        lines += ['', '## Add your own update', '', '- Completed: [confirm yourself]',
                  '- Blocked by: [confirm yourself]', '- Next step: [choose yourself]', '']
    if kind == 'handoff':
        lines += ['## Instructions for the receiving assistant','',
                  render_prompt('reports.handoff_recipient'), '']
    if kind == 'weekly':
        by_day = Counter((datetime.fromisoformat(row['created'].replace('Z','+00:00'))+timedelta(minutes=chosen['day_offset'])).date().isoformat() for row in rows)
        lines += ['## Activity by day','']
        lines += [f'- {day}: {count} captured moments' for day,count in sorted(by_day.items())]
        lines += ['', '## Questions explored','']
        lines += [f"- [{i}] {row['prompt'][:240].replace(chr(10),' ')} ({row['provider']})" for i,row in enumerate(rows,1)]
    elif kind != 'standup':
        lines += ['## Recorded sources in time order','']
        for i,row in enumerate(rows,1):
            local = datetime.fromisoformat(row['created'].replace('Z','+00:00'))+timedelta(minutes=chosen['day_offset'])
            lines += [f"### [{i}] {local:%Y-%m-%d %H:%M} · {row['provider']} · {row['project']}", '',
                      'Capture status: '+row['status'], '']
            if row['source_url']: lines += ['Original chat: '+row['source_url'],'']
            question = row['prompt'][:1200] if kind=='handoff' else row['prompt']
            reply = row['response'][:2400] if kind=='handoff' else row['response']
            lines += ['#### Question', '', question, '', '#### Recorded reply', '', reply or '(No reply captured)', '']
    else:
        lines += ['## Sources','']
        lines += [f"- [{i}] {r['created']} · {r['provider']} · {r['id']}" for i,r in enumerate(rows,1)]
    if notes:
        lines += ['', '## Personal notes','']
        for note in notes: lines += ['### '+note['day'],note['body'],'']
    body = '\n'.join(lines)
    if len(body.encode()) > 8*1024*1024: raise ValueError('This export is too large. Narrow the date range or collection.')
    # Evenly sample the full period; do not quietly claim the model read every turn.
    evidence = rows if len(rows)<=24 else [rows[round(i*(len(rows)-1)/23)] for i in range(24)]
    if generated:
        if not rows: raise ValueError('No recorded conversations match these filters')
        from .intelligence import generate, settings
        instruction = render_prompt('reports.'+kind)
        note_text = '\n'.join(n['day']+': '+n['body'] for n in notes)
        answer = generate(store,instruction,evidence,note_text,max_sources=24)
        origin = 'with ChatGPT sign-in (testing)' if settings(store).get('writing_provider')=='chatgpt' else 'locally'
        coverage = f'Generated {origin} from selected excerpts of {len(evidence)} of {selection_total} captured moments. Verify claims against the numbered original sources.'
        if len(note_text)>2000: coverage += ' Personal notes were limited to the first 2,000 characters.'
        body = f'# {title}\n\n{period}\n\n{coverage}\n\n{answer}'
    return {'title':title,'body':body,'generated':generated,'sources':evidence if generated else rows[:100],
            'total':selection_total,'source_count':len(evidence) if generated else len(rows),'topics':topics,
            'notes_included':len(notes),'scope':chosen,'filename':'wirebrain-'+kind+'.md'}


def snippets(store, options):
    rows = select(store,options)
    by_id = {r['id']:r for r in rows}
    found = []
    with store.connect() as db:
        for item in db.execute('SELECT * FROM saved_snippets ORDER BY created DESC'):
            if item['exchange_id'] in by_id: found.append({**dict(item),'saved':True})
    saved = {(item['exchange_id'],item['content']) for item in found}
    for row in reversed(rows):
        for language,content in re.findall(r'```([^\n`]*)\n([\s\S]*?)```',row['response']):
            content = redact(content.strip())
            if not content or len(content)>20000 or (row['id'],content) in saved: continue
            found.append({'id':hashlib.sha256((row['id']+content).encode()).hexdigest(),
                          'exchange_id':row['id'],'title':row['thread_title'] or row['prompt'][:100],
                          'content':content,'language':language.strip()[:40],'created':row['created'],'saved':False})
            if len(found)>=500: break
        if len(found)>=500: break
    return [{**item,'provider':by_id[item['exchange_id']]['provider'],'project':by_id[item['exchange_id']]['project'],'source':{**{key:by_id[item['exchange_id']][key] for key in ('id','created','provider','project','thread_id','thread_title','source_url')},'prompt':by_id[item['exchange_id']]['prompt'][:400]}} for item in found[:500]]


def validate_snippet(payload):
    values = {}
    for key,limit in (('title',120),('content',20000),('language',40)):
        value = payload.get(key,'')
        if not isinstance(value,str) or len(value)>limit or (key in ('title','content') and not value.strip()):
            raise ValueError('Choose a title and snippet text under 20,000 characters')
        values[key] = redact(value.strip())
    return values


def save_snippet(store, payload):
    values = validate_snippet(payload)
    ident = payload.get('exchange_id','')
    if not isinstance(ident,str): raise ValueError('Choose a source conversation')
    key = hashlib.sha256((ident+'\0'+values['content']).encode()).hexdigest()
    with store.connect() as db:
        if not db.execute('SELECT 1 FROM conversations WHERE id=?',(ident,)).fetchone(): raise ValueError('Source conversation no longer exists')
        db.execute('INSERT INTO saved_snippets VALUES (?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET title=excluded.title,language=excluded.language',
                   (key,ident,values['title'],values['content'],values['language'],datetime.now(timezone.utc).isoformat()))
    return {'ok':True,'id':key}


def remove_snippet(store, payload):
    ident = payload.get('id')
    if not isinstance(ident,str): raise ValueError('Choose a kept snippet')
    with store.connect() as db:
        row=db.execute('SELECT language,content FROM saved_snippets WHERE id=?',(ident,)).fetchone()
        if row and row['language'].startswith('macro:'):
            from .reflect_tools import macro_hash
            db.execute('INSERT OR IGNORE INTO reflect_macro_blocks VALUES (?)',(macro_hash(row['content']),))
        db.execute('DELETE FROM saved_snippets WHERE id=?',(ident,))
    return {'ok':True}


def compare(store, payload):
    ids = payload.get('ids')
    if not isinstance(ids,list) or len(ids)!=2 or any(not isinstance(i,str) for i in ids) or ids[0]==ids[1]:
        raise ValueError('Choose two different captured moments to compare')
    rows = [store.list(exchange_id=ident,limit=1) for ident in ids]
    if not all(rows): raise ValueError('A selected memory no longer exists')
    a,b = rows[0][0],rows[1][0]
    if sum(len(r[field]) for r in (a,b) for field in ('prompt','response'))>200000:
        raise ValueError('These conversations are too large for an inline comparison. Export their original text instead.')
    result = {'left':a,'right':b}
    for field in ('prompt','response'):
        result[field+'_diff'] = '\n'.join(difflib.unified_diff(a[field].splitlines(),b[field].splitlines(),fromfile='First selection',tofile='Second selection',lineterm=''))
    return result


def usage(store, options):
    rows = select(store,options)
    groups = {}
    for row in rows:
        key = (row['provider'],row['model'],row['project'])
        item = groups.setdefault(key,{'provider':key[0],'model':key[1],'project':key[2],
                                     'moments':0,'reported':0,'input_reports':0,'output_reports':0,'input_tokens':0,'output_tokens':0,'samples':0})
        item['moments'] += 1
        if row['demo']: item['samples'] += 1; continue
        if row['usage_reported']:
            item['reported'] += 1
        if row['input_reported']:
            item['input_reports'] += 1; item['input_tokens'] += row['input_tokens']
        if row['output_reported']:
            item['output_reports'] += 1; item['output_tokens'] += row['output_tokens']
    return {'groups':list(groups.values()),'moments':len(rows),
            'reported':sum(g['reported'] for g in groups.values()),'samples':sum(g['samples'] for g in groups.values()),
            'input_tokens':sum(g['input_tokens'] for g in groups.values()),'output_tokens':sum(g['output_tokens'] for g in groups.values()),
            'input_reports':sum(g['input_reports'] for g in groups.values()),'output_reports':sum(g['output_reports'] for g in groups.values()),
            'notice':'Provider-reported fields only. Missing usage is unknown, not zero. Sample usage is excluded. Web capture usually has no token usage. These are not subscription costs or bills.'}
