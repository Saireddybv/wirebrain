"""Observable AI-use patterns and reusable text; never diagnose ability or agency."""
from .prompting import render_prompt
import hashlib
import re
from collections import Counter
from datetime import datetime, timezone

from .personal_memory import eligible_prompt, list_memories
from .store import redact
from .workflows import select, scope, learning

CATEGORIES = {
    'learning': ('Learning and troubleshooting', 'Try explaining one answer in your own words before asking a follow-up.'),
    'routine': ('Formatting and routine tasks', 'Keep a reusable template for a task you repeat.'),
    'creation': ('Writing and building', 'Decide what a good result looks like before requesting a draft.'),
    'decisions': ('Decision support', 'Write down your own options and criteria before comparing the AI response.'),
    'communication': ('Personal communication', 'Check that suggested wording reflects what you actually want to say.'),
    'research': ('Research and questions', 'Verify an important claim against an original source.'),
    'other': ('Other or unclear', 'Open the source if this label does not match your intent.'),
}
LEARNING = re.compile(r'\b(explain|understand|teach|learn|debug|fix|error|why|how (?:does|do|to)|what (?:is|are))\b',re.I)


def recurring(rows, offset):
    cleaned=[{**row,'prompt':re.sub(r'\b(understand|debug|fix|teach|learn|again|please|explanation)\b',' ',row['prompt'],flags=re.I)}
             for row in rows if LEARNING.search(row['prompt'])]
    return learning(cleaned,offset)


def category(prompt):
    text=prompt.casefold()
    if re.search(r'\b(text|message|reply|apology|apologize|argument)\b',text) and re.search(r'\b(friend|partner|wife|husband|family|girlfriend|boyfriend|relationship|argument)\b',text):
        return 'communication'
    if re.search(r'\b(should i|decide for me|make (?:the |this )?decision|which .{0,40} should i|choose for me)\b',text): return 'decisions'
    if LEARNING.search(text): return 'learning'
    if re.search(r'\b(format|convert|sort|extract|reformat|translate|summarize)\b',text): return 'routine'
    if re.search(r'\b(write|draft|build|create|implement|compose|generate|refactor)\b',text): return 'creation'
    if re.search(r'\b(what|when|who|where|find|search|research|compare)\b',text): return 'research'
    return 'other'


def macro_hash(content):
    return hashlib.sha256(re.sub(r'\s+',' ',content).strip().encode()).hexdigest()


def candidates(row):
    """Conservative, exact-text candidates, not a claim that a template is correct."""
    if row['status']!='complete' or row['demo']: return []
    prompt,reply=row['prompt'],row['response']
    found=[]
    reusable=re.compile(r'\{\{[^{}\n]{1,80}\}\}|\[(?:name|topic|context|company|recipient|task|audience|date|goal)[^\]\n]{0,40}\]',re.I)
    if len(prompt)>=100 and (len(reusable.findall(prompt))>=2 or len(re.findall(r'(?im)^(?:role|task|context|constraints|output(?: format)?):',prompt))>=2):
        found.append(('prompt',prompt))
    if re.search(r'\b(email|template|draft)\b',prompt,re.I) and re.search(r'(?im)^subject:\s*\S',reply) and (reusable.search(reply) or re.search(r'(?im)^(?:dear |hi |hello |best regards|regards|sincerely)',reply)):
        found.append(('email',reply))
    if re.search(r'\b(workflow|checklist|process|step.by.step|routine|steps)\b',prompt,re.I) and len(re.findall(r'(?m)^\s*(?:\d+[.)]|- \[[ x]\])\s+\S',reply))>=3:
        found.append(('workflow',reply))
    for language,content in re.findall(r'```([^\n`]*)\n([\s\S]*?)```',reply):
        if language.strip().lower() in ('prompt','template') or (reusable.search(content) and re.search(r'\b(prompt|template)\b',prompt,re.I)):
            found.append(('prompt',content))
    clean=[]
    seen=set()
    for kind,content in found:
        content=content.strip()
        if not 40<=len(content)<=20000 or redact(content)!=content or '[REDACTED]' in content: continue
        if content in seen: continue
        seen.add(content);clean.append((kind,content))
    return clean[:3]


def discover_macros(store, rows):
    added=0
    for row in rows:
        for kind,content in candidates(row):
            ident=hashlib.sha256((row['id']+'\0'+content).encode()).hexdigest()
            title={'prompt':'Reusable prompt','email':'Email template','workflow':'Workflow'}[kind]+': '+re.sub(r'\s+',' ',row['prompt'])[:80]
            with store.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                current=db.execute('SELECT prompt,response,project,status FROM conversations WHERE id=?',(row['id'],)).fetchone()
                if not current or current['status']!='complete' or any(current[field]!=row[field] for field in ('prompt','response','project')): continue
                if db.execute('SELECT 1 FROM reflect_macro_blocks WHERE content_hash=?',(macro_hash(content),)).fetchone(): continue
                if db.execute("SELECT 1 FROM saved_snippets s JOIN conversations c ON c.id=s.exchange_id WHERE s.content=? AND c.project=? AND s.language LIKE 'macro:%'",(content,row['project'])).fetchone(): continue
                result=db.execute('INSERT OR IGNORE INTO saved_snippets VALUES (?,?,?,?,?,?)',
                    (ident,row['id'],redact(title)[:120],content,'macro:'+kind,datetime.now(timezone.utc).isoformat()))
                added+=result.rowcount
    return added


def macros(store, rows, query=''):
    if not isinstance(query,str) or len(query)>1000: raise ValueError('Search macros with a shorter phrase')
    allowed={row['id']:row for row in rows}
    result=[]
    with store.connect() as db:
        for item in db.execute("SELECT * FROM saved_snippets WHERE language LIKE 'macro:%' ORDER BY created DESC"):
            if item['exchange_id'] not in allowed: continue
            if query.strip() and query.casefold() not in (item['title']+' '+item['content']).casefold(): continue
            source=allowed[item['exchange_id']]
            result.append({**dict(item),'kind':item['language'].split(':',1)[1],
                'source':{key:source[key] for key in ('id','provider','project','created','thread_id','thread_title','source_url')}})
            if len(result)>=500: break
    return result


def analyze(store, options):
    selected=select(store,options)
    rows=[row for row in selected if not row['demo'] and eligible_prompt(row['prompt'])]
    chosen=scope(options)
    repeat=recurring(rows,chosen['day_offset'])
    counts=Counter(category(row['prompt']) for row in rows)
    mapping=[]
    for key,(title,checkin) in CATEGORIES.items():
        matches=[row for row in rows if category(row['prompt'])==key]
        mapping.append({'id':key,'title':title,'count':counts[key],
            'percent':round(100*counts[key]/len(rows),1) if rows else 0,'checkin':checkin,
            'sources':[{'id':row['id'],'provider':row['provider'],'project':row['project'],'prompt':row['prompt'][:220]} for row in matches[:8]]})
    discover_macros(store,selected)
    identifiers={row['id'] for row in selected}
    suggestions=[memory for memory in list_memories(store,provider=chosen['provider'],scope=chosen['project'] or None,status='suggested')
                 if any(source['exchange_id'] in identifiers for source in memory['sources'])]
    return {'total':len(selected),'analyzed':len(rows),'topics':repeat,'use_map':mapping,
        'macros':macros(store,selected,options.get('query','')),'suggestions':suggestions,
        'note':'Based on captured prompt wording, not time spent, proficiency, dependency, or loss of independence. Categories can be wrong.',
        'scope':chosen}


def study_guide(store, options):
    if not isinstance(options.get('generate',False),bool): raise ValueError('Choose whether to draft with AI')
    rows=[row for row in select(store,options) if not row['demo'] and eligible_prompt(row['prompt'])]
    chosen=scope(options)
    topics=recurring(rows,chosen['day_offset'])
    requested=options.get('topic','')
    if not isinstance(requested,str) or len(requested)>200: raise ValueError('Choose a valid recurring topic')
    if requested:
        topics=[topic for topic in topics if topic['topic']==requested]
        if not topics: raise ValueError('That recurring topic is not in the selected conversations')
    if not topics: raise ValueError('No repeated explanation or troubleshooting topics were found in this selection')
    ids={ident for topic in topics for ident in topic['sources']}
    by_id={row['id']:row for row in rows}
    source_ids=[]
    for topic in topics[:6]:
        first=next((ident for ident in topic['sources'] if ident in by_id),None)
        if first and first not in source_ids: source_ids.append(first)
    source_ids.extend(row['id'] for row in rows if row['id'] in ids and row['id'] not in source_ids)
    sources=[by_id[ident] for ident in source_ids[:8]]
    lines=['# A small study guide','','Repeated questions show a topic you revisited, not proof of a knowledge gap.','']
    for topic in topics[:6]:
        lines += ['## '+topic['topic'],f"Revisited in {topic['count']} captured prompts.",'',
                  '1. Explain the idea in your own words without looking at an AI answer.',
                  '2. Try one small example, predict its result, and check it yourself.',
                  '3. Compare your explanation with the original sources and note one uncertainty.','']
    if options.get('generate'):
        from .intelligence import generate,settings
        instruction=render_prompt('reflect.study',topics=', '.join(topic['topic'] for topic in topics[:6]))
        lines += [generate(store,instruction,sources),'']
        backend='ChatGPT testing mode' if settings(store).get('writing_provider')=='chatgpt' else 'local AI'
        lines += ['Drafted with '+backend+'. Check the source answers; they may contain errors.','']
    lines += ['## Original sources','']
    for i,row in enumerate(sources,1):
        lines += [f"### [{i}] {row['provider']} · {row['created']}",row['prompt'][:500],row['response'][:700],'']
    return {'body':'\n'.join(lines),'sources':sources,'topics':topics,'generated':options.get('generate',False)}
