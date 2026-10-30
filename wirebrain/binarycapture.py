"""Bounded protobuf wire reader for passive website capture (no RPC client)."""
import json
import base64

LIMIT=2*1024*1024


def number(raw, pos):
    value=0
    for shift in range(0,70,7):
        if pos>=len(raw): raise ValueError('short varint')
        byte=raw[pos];pos+=1;value|=(byte&127)<<shift
        if byte<128:return value,pos
    raise ValueError('long varint')


def fields(raw):
    if not isinstance(raw,bytes) or len(raw)>LIMIT:raise ValueError('oversized message')
    result={};pos=0;count=0
    while pos<len(raw):
        count+=1
        if count>20000:raise ValueError('too many fields')
        tag,pos=number(raw,pos);key,kind=tag>>3,tag&7
        if not key:raise ValueError('invalid field')
        if kind==0:value,pos=number(raw,pos)
        elif kind in (1,5):
            size=8 if kind==1 else 4;value=raw[pos:pos+size];pos+=size
        elif kind==2:
            size,pos=number(raw,pos);value=raw[pos:pos+size];pos+=size
            if len(value)!=size:raise ValueError('short field')
        else:raise ValueError('unsupported field')
        if pos>len(raw):raise ValueError('short field')
        result.setdefault(key,[]).append(value)
    return result


def value(raw,*path):
    for key in path:
        raw=fields(raw).get(key,[None])[0]
        if raw is None:return None
    return raw


def text(raw,*path):
    raw=value(raw,*path)
    return raw.decode('utf-8') if isinstance(raw,bytes) else ''


def dgw_frames(raw):
    if not isinstance(raw,bytes) or len(raw)>LIMIT:return
    pos=0
    while pos<len(raw):
        kind=raw[pos]
        if kind in (9,10):pos+=1;continue
        if len(raw)-pos<6:return
        stream=int.from_bytes(raw[pos+1:pos+3],'big')
        size=int.from_bytes(raw[pos+3:pos+6],'little')
        if size>len(raw)-pos-6:return
        yield kind,stream,raw[pos+6:pos+6+size]
        pos+=6+size


def meta_prompt(body):
    envelope=json.loads(body)
    raw=base64.b64decode(envelope['payload'],validate=True)
    prompt=text(raw,2,2)
    if not prompt.strip():return None
    return {'prompt':prompt,'conversation_id':text(raw,2,1,2,1),
            'message_id':text(raw,2,1,1),'parent_message_id':text(raw,2,1,4)}


class MetaReply:
    def __init__(self):
        self.doc={};self.text='';self.response_id='';self.done=False;self.error=False
        self.received=0

    def patch(self, operation):
        path=operation.get('path','')
        if not isinstance(path,str) or not path.startswith('/sections'):return
        keys=[k.replace('~1','/').replace('~0','~') for k in path.split('/')[1:]]
        if len(keys)>20:return
        parent=self.doc
        try:
            for key in keys[:-1]:parent=parent[int(key)] if isinstance(parent,list) else parent[key]
            key=keys[-1];op=operation.get('op');v=operation.get('value')
            if isinstance(parent,list):
                index=len(parent) if key=='-' else int(key)
                if not 0<=index<=len(parent):return
                if op=='add':parent.insert(index,v)
                elif op=='remove':parent.pop(index)
                elif op=='replace':parent[index]=v
                elif op=='delta' and isinstance(v,str):parent[index]+=v
            elif isinstance(parent,dict):
                if op in ('add','replace'):parent[key]=v
                elif op=='remove':parent.pop(key,None)
                elif op=='delta' and isinstance(v,str):parent[key]=parent.get(key,'')+v
        except (KeyError,IndexError,ValueError,TypeError):return

    def feed(self, raw):
        self.received+=len(raw)
        if self.received>16*LIMIT:self.error=True;return
        self.done=value(raw,3)==1 or self.done
        self.response_id=text(raw,4) or self.response_id
        piece=value(raw,1)
        if not isinstance(piece,bytes):return
        if value(piece,10) is not None:self.error=True
        # Only answer and inline UI variants; reasoning/client tool data excluded.
        for variant,field in ((4,10),(8,9)):
            body=value(piece,variant)
            if not isinstance(body,bytes):continue
            content=text(body,field)
            if not content:continue
            update=json.loads(content)
            if not isinstance(update,dict):continue
            if update.get('type')=='full' and isinstance(update.get('response'),dict):self.doc=update['response']
            elif update.get('type')=='patch' and isinstance(update.get('operations'),list):
                for operation in update['operations'][:10000]:
                    if isinstance(operation,dict):self.patch(operation)
            elif isinstance(update.get('sections'),list):self.doc=update
        parts=[]
        for section in self.doc.get('sections',[])[:10000]:
            if not isinstance(section,dict):continue
            primitive=section.get('view_model',{}).get('primitive',{})
            kind=primitive.get('__typename')
            if kind=='GenAIMarkdownTextUXPrimitive' and isinstance(primitive.get('text'),str):parts.append(primitive['text'])
            elif kind=='GenAICodeUXPrimitive':
                code=''.join(b.get('content','') for b in primitive.get('code_blocks',[]) if isinstance(b,dict) and isinstance(b.get('content',''),str))
                parts.append('```'+str(primitive.get('language',''))+'\n'+code+'\n```')
            elif kind=='GenAILatexUXPrimitive' and isinstance(primitive.get('latex_expression'),str):parts.append('$$\n'+primitive['latex_expression']+'\n$$')
        self.text='\n\n'.join(parts)[:LIMIT]

    @property
    def status(self):return 'error' if self.error else 'complete' if self.done else 'interrupted'
