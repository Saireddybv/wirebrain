"""Bounded text capture for Gemini WebChannel protobuf framing."""
import base64
import json
import re
import hashlib
from .binarycapture import fields, value, text, LIMIT


def schema(raw, depth=0):
    if depth>10:return 'bounded'
    result={}
    for field,values in fields(raw).items():
        summaries=[]
        for item in values[:8]:
            if isinstance(item,int):summary='integer'
            else:
                try:summary=schema(item,depth+1)
                except (ValueError,IndexError):
                    try:
                        literal=item.decode('utf-8')
                        summary='TEST_PROMPT' if literal.startswith('Wirebrain ') else 'HELLO_REPLY' if literal.lower().strip() in ('hello','hello!') else 'CONVERSATION_ID' if re.fullmatch(r'c_[0-9a-f]+',literal) else 'REPLY_ID' if re.fullmatch(r'r_[0-9a-f]+',literal) else 'CANDIDATE_ID' if re.fullmatch(r'rc_[0-9a-f]+',literal) else 'text'
                    except UnicodeError:summary='bytes'
            summaries.append(summary)
        result[str(field)]=summaries
    return result


class ChannelFrames:
    def __init__(self,store,state=None,pool=None):
        self.pending=b'';self.store=store;self.expected=None
        self.state=state;self.pool=pool

    def request(self,raw):
        if self.state is None:return
        cid=text(raw,1,8,5,72,1)
        if cid.startswith('c_'):self.state['cid']=cid
        prompt=text(raw,2,9,1)
        if not prompt.strip():return
        request_id=value(raw,2,1)
        if not isinstance(request_id,int):return
        rows=self.state.setdefault('rows',{})
        if request_id in rows:return
        for old in rows.values():
            if not old.get('done'):self.store.update(old['id'],old['text'],'interrupted');old['done']=True
        if len(rows)>=128:
            rows.pop(next(iter(rows)))
        ident=self.store.add('gemini','web · unknown',prompt[:LIMIT],'Web conversations')
        rows[request_id]={'id':ident,'text':'','done':False,'cid':self.state.get('cid','')}
        self.store.link_exchange(ident,'gemini',self.state.get('cid',''))
        self.store.capture_seen('geminiweb-pa.clients6.google.com',prompt=True)

    def response(self,raw):
        if self.state is None:return
        document=value(raw,2,7,1,4,4)
        if not isinstance(document,bytes):return
        cid=text(document,2,1)
        reply_id=text(document,2,2)
        rows=self.state.get('rows',{})
        matches=[r for r in rows.values() if reply_id and r.get('reply_id')==reply_id]
        if len(matches)==1:row=matches[0]
        else:
            # The outer integer is a frame sequence, not a request identifier.
            # Bind a reply ID only to the sole active turn on this channel.
            pending=[r for r in rows.values() if not r.get('done') and not r.get('reply_id') and (not cid or not r.get('cid') or r['cid']==cid)]
            if len(pending)!=1:return
            row=pending[0]
        if reply_id:row['reply_id']=reply_id
        if cid.startswith('c_'):
            self.state['cid']=cid;row['cid']=cid
        candidates=fields(document).get(5,[])
        if candidates and isinstance(candidates[0],bytes):
            content=value(candidates[0],2)
            answer='\n'.join(p.decode('utf-8') for p in fields(content).get(1,[]) if isinstance(p,bytes)) if isinstance(content,bytes) else ''
            if answer:row['text']=answer[:LIMIT];row['truncated']=len(answer)>LIMIT
        if value(document,52) is not None:row['done']=True
        status='truncated' if row.get('truncated') else ('complete' if row['text'] else 'unsupported') if row['done'] else 'streaming'
        self.store.update(row['id'],row['text'],status)
        self.store.link_exchange(row['id'],'gemini',row.get('cid',''),response_message_id=reply_id)

    def interrupted(self):
        if self.state is not None:
            for row in self.state.get('rows',{}).values():
                if not row.get('done'):self.store.update(row['id'],row['text'],'interrupted')

    def record(self,route,info):
        with self.store.connect() as db:
            db.execute('INSERT INTO capture_routes VALUES (?,?,1) ON CONFLICT(route) DO UPDATE SET keys=excluded.keys,count=count+1',(route,json.dumps(info)))

    def feed(self,chunk):
        self.pending+=chunk
        if len(self.pending)>2*1024*1024:self.pending=b'';self.expected=None;return
        while self.pending:
            if self.expected is not None:
                if len(self.pending)<self.expected:return
                raw,self.pending=self.pending[:self.expected],self.pending[self.expected:]
                self.expected=None;self.frame(raw);continue
            if b'\n' not in self.pending:return
            line,self.pending=self.pending.split(b'\n',1)
            if line.strip().isdigit():
                length=int(line.strip())
                if length>2*1024*1024:self.pending=b'';return
                self.expected=length
            elif line.strip().startswith((b'[',b'{')):self.frame(line)

    def frame(self,raw):
        try:
            obj=json.loads(raw)
            def outline(v,depth=0):
                if depth>10:return type(v).__name__
                if isinstance(v,list):return [outline(x,depth+1) for x in v[:8]]
                if isinstance(v,dict):return {'object_values':[outline(x,depth+1) for x in list(v.values())[:4]]}
                if isinstance(v,str):
                    if v.lower().strip() in ('hello','hello!'):return 'HELLO_REPLY'
                    if v.startswith('Wirebrain '):return 'TEST_PROMPT'
                return type(v).__name__
            structure=outline(obj)
            self.record('gemini WebChannel JSON framing '+hashlib.sha256(json.dumps(structure).encode()).hexdigest()[:12],structure)
            self.inspect(obj)
        except (ValueError,TypeError,IndexError,UnicodeError):
            # Classify framing bytes only; never save response/session values.
            prefix=''.join('A' if chr(b).isalnum() else chr(b) if 32<=b<127 else '.' for b in raw[:24])
            self.record('gemini WebChannel binary framing',{'bytes':len(raw),'prefix_shape':prefix})
            try:
                info=schema(raw)
                self.record('gemini WebChannel raw protobuf '+','.join(sorted(info)),info)
            except (ValueError,TypeError,IndexError,UnicodeError):pass

    def inspect(self,obj,depth=0):
        if depth>12:return
        if isinstance(obj,list):
            if self.pool is not None and len(obj)>1 and isinstance(obj[1],list) and len(obj[1])>1 and obj[1][0]=='c' and isinstance(obj[1][1],str):
                sid=obj[1][1]
                if len(sid)<=512 and len(self.pool)<128:self.pool[sid]=self.state
            for item in obj[:1000]:self.inspect(item,depth+1)
        elif isinstance(obj,dict):
            for item in list(obj.values())[:100]:self.inspect(item,depth+1)
        elif isinstance(obj,str) and len(obj)>8:
            if obj.lstrip().startswith(('[','{')):
                try:self.inspect(json.loads(obj),depth+1)
                except ValueError:pass
                return
            try:
                raw=base64.b64decode(obj+'='*((-len(obj))%4),altchars=b'-_',validate=True)
                self.response(raw)
                info=schema(raw)
                route='gemini WebChannel response schema '+','.join(sorted(info))
                with self.store.connect() as db:
                    db.execute('INSERT INTO capture_routes VALUES (?,?,1) ON CONFLICT(route) DO UPDATE SET keys=excluded.keys,count=count+1',(route,json.dumps(info)))
                    variant=route+' variant '+hashlib.sha256(json.dumps(info,sort_keys=True).encode()).hexdigest()[:12]
                    db.execute('INSERT INTO capture_routes VALUES (?,?,1) ON CONFLICT(route) DO UPDATE SET count=count+1',(variant,json.dumps(info)))
            except (ValueError,TypeError,IndexError,UnicodeError):pass
