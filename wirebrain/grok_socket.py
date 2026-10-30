"""Passive text capture for Grok's JSON message gateway; never sends frames."""
import json
import re

LIMIT=2*1024*1024


class GrokSocket:
    def __init__(self,store):self.store=store;self.sessions={};self.aliases={};self.seen=0

    def receive(self,messages):
        for message in messages[max(self.seen,len(messages)-100):]:
            if len(message.content)>LIMIT:continue
            try:
                env=json.loads(message.content)
                def shape(v,depth=0):
                    if depth>6:return type(v).__name__
                    if isinstance(v,dict):return {k:shape(x,depth+1) for k,x in list(v.items())[:50] if re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}',k)}
                    if isinstance(v,list):return [shape(x,depth+1) for x in v[:4]]
                    if isinstance(v,str) and v.startswith('Wirebrain '):return 'TEST_PROMPT'
                    return type(v).__name__
                kind=env.get('event',{}).get('type','unrecognized') if isinstance(env,dict) and isinstance(env.get('event',{}),dict) else 'unrecognized'
                if not isinstance(kind,str) or not re.fullmatch(r'[a-z_.]{1,80}',kind):kind='unrecognized'
                route='grok gateway schema '+('outgoing ' if message.from_client else 'incoming ')+kind
                with self.store.connect() as db:
                    db.execute('INSERT INTO capture_routes VALUES (?,?,1) ON CONFLICT(route) DO UPDATE SET keys=excluded.keys,count=count+1',(route,json.dumps(shape(env))))
                if isinstance(env,dict):self.event(env,message.from_client)
            except (ValueError,TypeError,AttributeError,KeyError):pass
        self.seen=len(messages)

    def event(self,env,outgoing):
        event=env.get('event',{})
        if not isinstance(event,dict):return
        kind=event.get('type');cid=env.get('session_id','')
        if kind in ('session.create','session.created'):
            session=event.get('session',{})
            canonical=session.get('x_grok',{}).get('conversation_id')
            if isinstance(canonical,str) and canonical:
                self.aliases[cid]=canonical;cid=canonical
        elif kind=='conversation.attached':
            canonical=event.get('conversation',{}).get('id')
            if isinstance(canonical,str) and canonical:self.aliases[cid]=canonical;cid=canonical
        cid=self.aliases.get(cid,cid)
        if not isinstance(cid,str):return
        if cid not in self.sessions and len(self.sessions)>=128:return
        state=self.sessions.setdefault(cid,{'text':'','model':'web · unknown'})
        if not outgoing and kind=='conversation.history.item':
            item=event.get('item',{})
            if item.get('role')=='assistant' and item.get('status')=='completed':
                final=''.join(p.get('text','') for p in item.get('content',[]) if isinstance(p,dict) and p.get('type') in ('output_text','text') and isinstance(p.get('text'),str))
                if not final:
                    final=''.join(c['text']['text'] for c in item.get('x_grok',{}).get('output_chunks',[]) if isinstance(c,dict) and isinstance(c.get('text'),dict) and isinstance(c['text'].get('text'),str) and not any(k in str(c['text'].get('channel','')).upper() for k in ('THINKING','NOTETAKER')))
                if final:
                    with self.store.connect() as db:
                        rows=db.execute("SELECT c.id,c.response FROM conversations c JOIN exchange_threads e ON e.exchange_id=c.id JOIN threads t ON t.id=e.thread_id WHERE c.provider='grok' AND c.demo=0 AND t.conversation_id=? AND e.response_message_id=?",(cid,item.get('id',''))).fetchall()
                    for row in rows:
                        if len(final)>=len(row['response']) and final.startswith(row['response']):self.store.update(row['id'],final[:LIMIT],'complete')
            return
        if kind in ('session.create','session.created'):
            model=event.get('session',{}).get('model')
            if isinstance(model,str):state['model']=model[:200]
        if outgoing:
            if kind=='conversation.item.create' or (kind=='response.create' and isinstance(event.get('item'),dict)):
                item=event.get('item',{})
                if item.get('role')!='user':return
                info=item.get('x_grok',{})
                chunks=info.get('input_chunks',[])
                prompt=''.join(c.get('text',{}).get('text','') for c in chunks if isinstance(c,dict) and isinstance(c.get('text'),dict) and isinstance(c['text'].get('text'),str))
                if prompt.strip():state['pending']=(prompt[:LIMIT],info.get('client_message_id',''),event.get('parent_response_id',''))
            if kind=='response.create' and state.get('pending'):
                event_id=event.get('event_id')
                if event_id and state.get('last_create')==event_id:return
                if state.get('id') and not state.get('done'):self.store.update(state['id'],state['text'],'interrupted')
                prompt,message_id,parent=state.pop('pending')
                ident=self.store.add('grok',state['model'],prompt,'Web conversations')
                state.update(id=ident,text='',done=False,error=False,response_id='',mode='',last_create=event_id)
                self.store.link_exchange(ident,'grok',cid,message_id,parent)
                self.store.capture_seen('grok.com',prompt=True)
            return
        if not state.get('id'):return
        if kind=='response.output_item.added' and event.get('item',{}).get('role')=='assistant':
            state['response_id']=event['item'].get('id','')
        text='';mode=''
        if kind=='response.chunk':
            info=event.get('chunk',{}).get('text',{})
            if isinstance(info,dict) and not any(label in str(info.get('channel','')).upper() for label in ('THINKING','NOTETAKER')):
                text=info.get('text','');mode='chunk'
        elif kind=='response.output_text.delta':text=event.get('delta','');mode='delta'
        elif kind=='response.output_text.done' and isinstance(event.get('text'),str) and event['text']:
            state['text']=event['text'][:LIMIT];state['mode']='final'
        if text and isinstance(text,str) and (not state['mode'] or state['mode']==mode):
            state['mode']=mode;state['text']=(state['text']+text)[:LIMIT]
        if kind=='error' or event.get('output',{}).get('stream_error'):state['error']=True
        if kind=='response.done':
            response=event.get('response',{})
            state['done']=True
            state['response_id']=response.get('id') or state['response_id']
            state['status']=('complete' if state['text'] else 'unsupported') if response.get('status','completed')=='completed' else 'interrupted'
        self.store.update(state['id'],state['text'],'error' if state.get('error') else state.get('status','complete') if state.get('done') else 'streaming')
        self.store.link_exchange(state['id'],'grok',cid,response_message_id=state.get('response_id',''))

    def finish(self):
        for state in self.sessions.values():
            if state.get('id') and not state.get('done'):self.store.update(state['id'],state['text'],'interrupted')
