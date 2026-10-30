import base64
import json
import tempfile
import unittest
from types import SimpleNamespace
from urllib.parse import urlencode
from wirebrain.gemini_channel import ChannelFrames
from wirebrain.mitm_addon import WebCapture

from wirebrain.store import Store


def vint(n):
    out=b''
    while n>127:out+=bytes([(n&127)|128]);n>>=7
    return out+bytes([n])


def proto(*pairs):
    out=b''
    for key,v in pairs:
        if isinstance(v,int):out+=vint(key<<3)+vint(v)
        else:
            if isinstance(v,str):v=v.encode()
            out+=vint((key<<3)|2)+vint(len(v))+v
    return out


def submitted(prompt='Explain SQLite',rid=1):return proto((2,proto((1,rid),(9,proto((1,prompt))))))


def reply(answer='hello',rid=1,cid='c_example',done=False):
    document=proto((2,proto((1,cid),(2,'r_answer'))))
    if answer is not None:document+=proto((5,proto((1,'rc_candidate'),(2,proto((1,answer))))))
    if done:document+=proto((52,b''))
    wrapped=proto((2,proto((1,rid),(7,proto((1,proto((4,proto((4,document))))))))))
    frame=json.dumps([[1,[base64.b64encode(wrapped).decode()]]]).encode()
    return str(len(frame)).encode()+b'\n'+frame


class GeminiFramingTests(unittest.TestCase):
    def test_current_protocol_captures_full_snapshots_and_terminal_metadata(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);state={'rows':{}}
            outgoing=ChannelFrames(store,state);incoming=ChannelFrames(store,state)
            outgoing.request(submitted())
            for frame in (reply('Hello',rid=25),reply('Hello 世界',rid=26),reply(None,rid=30,done=True)):
                for byte in frame:incoming.feed(bytes([byte]))
            rows=store.list();self.assertEqual(len(rows),1)
            self.assertEqual((rows[0]['prompt'],rows[0]['response'],rows[0]['status']),('Explain SQLite','Hello 世界','complete'))
            self.assertEqual(rows[0]['source_url'],'https://gemini.google.com/app/example')
            self.assertEqual(rows[0]['response_message_id'],'r_answer')
            outgoing.request(submitted());self.assertEqual(len(store.list()),1)

    def test_separate_channels_and_unmatched_replies_never_import_history(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);one=ChannelFrames(store,{'rows':{}});two=ChannelFrames(store,{'rows':{}})
            one.feed(reply('Uncaptured',done=True));self.assertEqual(store.list(),[])
            for channel,cid in ((one,'c_first'),(two,'c_second')):
                channel.request(submitted(cid))
                channel.feed(reply(cid,cid=cid,done=True))
            self.assertEqual(len({r['thread_id'] for r in store.list()}),2)
            self.assertEqual({r['response'] for r in store.list()},{'c_first','c_second'})

    def test_http_handshake_binds_forward_and_back_channels_without_replaying(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);addon=WebCapture(store)
            def flow(body=b'',sid=''):
                return SimpleNamespace(request=SimpleNamespace(host='geminiweb-pa.clients6.google.com',path='/v1/processSession'+('?SID='+sid if sid else ''),method='POST' if body else 'GET',content=body,headers={}),
                    response=SimpleNamespace(headers={'content-type':'text/plain'},status_code=200,stream=None),metadata={})
            opening=flow(b'count=0');addon.request(opening);addon.responseheaders(opening)
            raw=json.dumps([[0,['c','private-sid','host',8,1,1]]]).encode()
            raw=str(len(raw)).encode()+b'\n'+raw
            self.assertEqual(opening.response.stream(raw),raw)
            body=urlencode({'req0___data__':base64.b64encode(submitted()).decode()}).encode()
            forward=flow(body,'private-sid');addon.request(forward)
            backward=flow(sid='private-sid');addon.request(backward);addon.responseheaders(backward)
            raw=reply('Hello',done=True)
            self.assertEqual(backward.response.stream(raw),raw)
            row=store.list()[0];self.assertEqual((row['response'],row['status']),('Hello','complete'))
            self.assertNotIn('private-sid',store.export())

    def test_length_framing_handles_multiline_and_arbitrary_byte_boundaries(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);channel=ChannelFrames(store)
            # A protobuf field containing the fixed test reply, wrapped as a
            # pretty-printed WebChannel frame. It is a fixture, not a live format claim.
            payload=base64.b64encode(b'\x0a\x05hello').decode()
            raw=json.dumps([[1,[payload]]],indent=2).encode()
            framed=b")]}'\n"+str(len(raw)).encode()+b'\n'+raw+b'\n'
            for byte in framed:channel.feed(bytes([byte]))
            with store.connect() as db:
                row=db.execute("select keys from capture_routes where route='gemini WebChannel response schema 1'").fetchone()
            self.assertIn('HELLO_REPLY',row['keys'])
            self.assertEqual(store.list(),[])

    def test_diagnostics_never_log_arbitrary_string_values(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);channel=ChannelFrames(store)
            raw=json.dumps([[0,['secret-session-value','private-authentication']]]).encode()
            channel.feed(str(len(raw)).encode()+b'\n'+raw)
            with store.connect() as db:data=''.join(r['keys'] for r in db.execute('select keys from capture_routes'))
            self.assertNotIn('secret-session-value',data);self.assertNotIn('private-authentication',data)
            channel.feed(b'999999999\n')
            self.assertEqual(channel.pending,b'')
