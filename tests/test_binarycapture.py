import base64
import json
import tempfile
import unittest
from types import SimpleNamespace

from wirebrain.binarycapture import fields, meta_prompt, MetaReply, dgw_frames
from wirebrain.mitm_addon import WebCapture
from wirebrain.store import Store


def integer(n):
    out=b''
    while n>127:out+=bytes([(n&127)|128]);n>>=7
    return out+bytes([n])


def wire(*items):
    out=b''
    for key,value in items:
        if isinstance(value,int):out+=integer(key<<3)+integer(value)
        else:
            if isinstance(value,str):value=value.encode()
            out+=integer((key<<3)|2)+integer(len(value))+value
    return out


def frame(kind,body,stream=1):return bytes([kind])+stream.to_bytes(2,'big')+len(body).to_bytes(3,'little')+body


def prompt(message='Wirebrain test: reply hello',cid='meta-chat'):
    return wire((2,wire((1,wire((1,'turn-one'),(2,wire((1,cid))))),(2,message))))


def document(text):return {'sections':[{'view_model':{'primitive':{'__typename':'GenAIMarkdownTextUXPrimitive','text':text}}}], 'embedded_screens':[{'body':'private reasoning'}]}


def response(text='hello',final=True):
    return wire((1,wire((4,wire((10,json.dumps(document(text))))))),(3,int(final)),(4,'meta-answer'))


class BinaryCaptureTests(unittest.TestCase):
    def test_meta_message_fields_not_metadata(self):
        info=meta_prompt(json.dumps({'payload':base64.b64encode(prompt()).decode(),'req-id':'request'}))
        self.assertEqual(info['prompt'],'Wirebrain test: reply hello')
        self.assertEqual(info['conversation_id'],'meta-chat')
        self.assertEqual(info['message_id'],'turn-one')
        with self.assertRaises(ValueError):fields(b'\x0a\xff')

    def test_meta_answer_patch_and_reasoning_exclusion(self):
        reply=MetaReply();reply.feed(response('Hello',False))
        update={'type':'patch','operations':[{'op':'delta','path':'/sections/0/view_model/primitive/text','value':' 世界'}]}
        piece=wire((4,wire((10,json.dumps(update)))))
        reply.feed(wire((1,piece)))
        self.assertEqual(reply.text,'Hello 世界')
        piece=wire((5,wire((4,json.dumps(document('private thought'))))))
        reply.feed(wire((1,piece)))
        self.assertEqual(reply.text,'Hello 世界')
        reply.feed(wire((3,1),(4,'answer')))
        self.assertEqual(reply.status,'complete')
        self.assertEqual(reply.response_id,'answer')

    def test_meta_real_framing_and_multiple_streams_store_exchanges(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);addon=WebCapture(store)
            flow=SimpleNamespace(request=SimpleNamespace(host='gateway.meta.ai',path='/ws/clippy?Authorization=never-store'),
                websocket=SimpleNamespace(messages=[]),metadata={})
            for stream,cid in [(1,'chat-a'),(2,'chat-b')]:
                outgoing=b'\x00\x80'+json.dumps({'payload':base64.b64encode(prompt(cid=cid)).decode(),'req-id':'request'}).encode()
                incoming=b'\x00\x80'+response('hello '+cid)
                flow.websocket.messages.append(SimpleNamespace(from_client=True,content=frame(13,outgoing,stream)))
                addon.websocket_message(flow)
                flow.websocket.messages.append(SimpleNamespace(from_client=False,content=frame(13,incoming,stream)))
                addon.websocket_message(flow)
            addon.websocket_message(flow)
            rows=store.list();self.assertEqual(len(rows),2)
            self.assertTrue(all(r['status']=='complete' for r in rows))
            self.assertEqual(len({r['thread_id'] for r in rows}),2)
            self.assertEqual({r['response'] for r in rows},{'hello chat-a','hello chat-b'})
            self.assertNotIn('never-store',store.export())
            addon.websocket_end(flow)
            self.assertTrue(all(r['status']=='complete' for r in store.list()))

    def test_dgw_bounds_and_disconnection_preserve_partial(self):
        self.assertEqual(list(dgw_frames(b'\x0d\x00\x01\xff\xff\xffbad')),[])
        self.assertEqual(list(dgw_frames(b'\x09\x0a')),[])
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);addon=WebCapture(store)
            outgoing=b'\x00\x80'+json.dumps({'payload':base64.b64encode(prompt()).decode()}).encode()
            flow=SimpleNamespace(request=SimpleNamespace(host='gateway.meta.ai'),metadata={},websocket=SimpleNamespace(messages=[
                SimpleNamespace(from_client=True,content=frame(13,outgoing)),
                SimpleNamespace(from_client=False,content=frame(13,b'\x00\x80'+response('Partial',False)))]))
            addon.websocket_end(flow)
            self.assertEqual(store.list()[0]['response'],'Partial')
            self.assertEqual(store.list()[0]['status'],'interrupted')
