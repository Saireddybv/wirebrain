"""Content-free diagnostics for Meta's experimental DGW transport.

Do not guess which arbitrary protobuf string is a user message. Only fixed test
markers are recognized here; actual text, IDs and authorization are never saved.
"""
import base64
import json


def varint(raw, pos):
    result=0
    for shift in range(0,70,7):
        byte=raw[pos];pos+=1
        result |= (byte & 127)<<shift
        if byte<128: return result,pos
    raise ValueError('invalid varint')


def shape(raw, depth=0):
    if depth>8 or len(raw)>262144: return 'bounded'
    result={};pos=0
    while pos<len(raw) and len(result)<80:
        tag,pos=varint(raw,pos);field,kind=tag>>3,tag&7
        if not field: raise ValueError('zero field')
        key=str(field)
        if kind==0: _,pos=varint(raw,pos);value='integer'
        elif kind in (1,5): pos+=8 if kind==1 else 4;value='fixed'
        elif kind==2:
            size,pos=varint(raw,pos)
            if size>len(raw)-pos: raise ValueError('short field')
            data=raw[pos:pos+size];pos+=size
            value='bytes'
            try:
                text=data.decode('utf-8')
                if text=='Wirebrain test: reply hello': value='TEST_PROMPT'
                elif 'hello' in text.lower() and len(text)<100: value='HELLO_REPLY'
                elif text and all(c.isprintable() or c in '\n\r\t' for c in text): value='text'
            except UnicodeError: pass
            if value not in ('TEST_PROMPT','HELLO_REPLY') and data:
                try: value=shape(data,depth+1)
                except (ValueError,IndexError): pass
        else: raise ValueError('unsupported wire type')
        if pos>len(raw): raise ValueError('short frame')
        result[key]=value
    return result


def diagnostic(content):
    if not isinstance(content,bytes) or len(content)>262144: return None
    if len(content)<8: return None
    info={'frame_type':content[0], 'bytes':len(content)}
    offset=content.find(b'{',0,32)
    if offset<0: return {**info,'encoding':'binary'}
    try:
        envelope,_=json.JSONDecoder().raw_decode(content[offset:].decode('utf-8'))
        payload=envelope.get('payload')
        if not isinstance(payload,str): return {**info,'encoding':'unknown'}
        raw=base64.b64decode(payload,validate=True)
        return {**info,'encoding':'protobuf','fields':shape(raw)}
    except (ValueError,IndexError,TypeError,AttributeError,UnicodeError): return {**info,'encoding':'unrecognized'}
