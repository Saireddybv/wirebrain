import json
import base64
import re
import tempfile
import unittest
from types import SimpleNamespace
from urllib.parse import urlencode

from wirebrain.extra_webcapture import GEMINI_PATH, LIMIT, TextStream
from wirebrain.webcapture import ALLOW_HOSTS, generation_request
from wirebrain.mitm_addon import WebCapture
from wirebrain.store import Store
from wirebrain.meta_transport import diagnostic


def gemini_body(prompt='Explain SQLite', cid='c_existing'):
    return urlencode({'at':'never-store-this-token','f.req':json.dumps([None,json.dumps([[prompt,0,None],['en'],[cid,'r_parent']])])}).encode()


def gemini_frame(text, done=False):
    candidate=['rc_answer',[text],None,None,None,None,None,None,[2 if done else 1]]
    data=[None,['c_example','r_answer'],None,None,[candidate]]
    raw=json.dumps([['wrb.fr',None,json.dumps(data)]]).encode()
    return str(len(raw)).encode()+b'\n'+raw+b'\n'


def meta_body(name='useAbraSendMessageMutation'):
    return urlencode({'fb_dtsg':'never-store-this-token','fb_api_req_friendly_name':name,
        'variables':json.dumps({'message':{'sensitive_string_value':'Explain SQLite'},
        'externalConversationId':'chat-one','offlineThreadingId':'message-one'})}).encode()


def meta_event(text,done=False):
    return {'data':{'node':{'bot_response_message':{'id':'answer-one','streaming_state':'OVERALL_DONE' if done else 'STREAMING',
            'composed_text':{'content':[{'text':text}]}}}}}


class ExtraProtocols(unittest.TestCase):
    def test_exact_hosts_and_submission_routes_only(self):
        for host in ('gemini.google.com','grok.com','www.grok.com','meta.ai','www.meta.ai','graph.meta.ai','gateway.meta.ai'):
            self.assertTrue(re.fullmatch(ALLOW_HOSTS,host+':443'))
        for host in ('google.com','accounts.google.com','facebook.com','instagram.com','x.com','evil.grok.com','grok.com.attacker.test'):
            self.assertFalse(re.fullmatch(ALLOW_HOSTS,host))
            self.assertIsNone(generation_request(host,'/rest/app-chat/conversations/new',b'{"message":"secret"}'))
        self.assertIsNone(generation_request('gemini.google.com','/_/BardChatUi/data/batchexecute',gemini_body()))
        self.assertIsNone(generation_request('www.meta.ai','/api/graphql/',meta_body('OtherMutation')))

    def test_gemini_request_and_response_byte_boundaries(self):
        row=generation_request('gemini.google.com',GEMINI_PATH+'?secret=not-saved',gemini_body())
        self.assertEqual((row['prompt'],row['conversation_id'],row['parent_message_id']),('Explain SQLite','c_existing','r_parent'))
        self.assertNotIn('never-store',json.dumps(row))
        stream=TextStream('gemini')
        raw=b")]}'\n\n"+gemini_frame('')+gemini_frame('Hello')+gemini_frame('Hello 世界',True)
        for byte in raw: stream.feed(bytes([byte]))
        stream.finish()
        self.assertEqual((stream.text,stream.status,stream.conversation_id),('Hello 世界','complete','c_example'))
        self.assertEqual(stream.response_message_id,'rc_answer')

    def test_grok_initial_and_followup_and_thinking_exclusion(self):
        for path,cid in [('/rest/app-chat/conversations/new',''),('/rest/app-chat/conversations/thread-one/responses','thread-one')]:
            row=generation_request('grok.com',path,json.dumps({'message':'Explain SQLite','modelName':'grok-test','parentResponseId':'parent'}))
            self.assertEqual(row['conversation_id'],cid)
            self.assertEqual(row['model'],'grok-test')
        stream=TextStream('grok')
        events=[{'result':{'conversation':{'conversationId':'thread-one'}}},
            {'result':{'response':{'token':'private reasoning','isThinking':True}}},
            {'result':{'response':{'token':'Hello'}}},
            {'result':{'response':{'token':' 世界'}}},
            {'result':{'response':{'modelResponse':{'message':'Hello 世界!','responseId':'answer'}}}}]
        for event in events:
            for byte in (json.dumps(event,ensure_ascii=False)+'\n').encode(): stream.feed(bytes([byte]))
        self.assertEqual((stream.text,stream.status,stream.conversation_id),('Hello 世界!','complete','thread-one'))
        followup=TextStream('grok');followup.feed(b'{"result":{"modelResponse":{"message":"Followup","responseId":"a"}}}')
        followup.finish();self.assertEqual(followup.text,'Followup')

    def test_meta_http_snapshots_and_no_auth_persistence(self):
        row=generation_request('www.meta.ai','/api/graphql/',meta_body())
        self.assertEqual((row['prompt'],row['conversation_id']),('Explain SQLite','chat-one'))
        self.assertNotIn('never-store',json.dumps(row))
        stream=TextStream('meta')
        for event in [meta_event('Hello'),meta_event('Hello 世界',True)]:
            for byte in (json.dumps(event,ensure_ascii=False)+'\n').encode(): stream.feed(bytes([byte]))
        self.assertEqual((stream.text,stream.status),('Hello 世界','complete'))

    def test_malformed_and_non_submission_inputs_are_ignored(self):
        for host,path in [('gemini.google.com',GEMINI_PATH),('grok.com','/rest/app-chat/conversations/new'),('www.meta.ai','/api/graphql/')]:
            for body in [b'not-json',b'[]',b'{}',b'{"message":42}',b'f.req=123',b'f.req=%5Bnull%2Cnull%5D',b'\xff']:
                self.assertIsNone(generation_request(host,path,body))
        self.assertIsNone(generation_request('grok.com','/rest/app-chat/conversations/search',b'{"message":"draft"}'))

    def test_errors_limits_and_partial_are_honest(self):
        stream=TextStream('grok');stream.feed(b'{"result":{"token":"partial"}}\n')
        self.assertEqual(stream.status,'interrupted')
        stream.feed(b'{"error":{"message":"failed"}}\n');self.assertEqual(stream.status,'error')
        stream=TextStream('gemini');stream.feed(b'x'*(LIMIT+1));self.assertEqual(stream.status,'truncated')

    def test_all_three_stream_through_addon_without_changing_bytes(self):
        cases=[('gemini.google.com',GEMINI_PATH,gemini_body(cid=''),b")]}'\n"+gemini_frame('Hello',True),'text/plain'),
               ('grok.com','/rest/app-chat/conversations/new',b'{"message":"Explain SQLite"}',b'{"result":{"conversation":{"conversationId":"grok-thread"},"response":{"modelResponse":{"message":"Hello","responseId":"a"}}}}\n','application/x-ndjson'),
               ('www.meta.ai','/api/graphql/',meta_body(),(json.dumps(meta_event('Hello',True))+'\n').encode(),'application/json')]
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);addon=WebCapture(store)
            for host,path,body,raw,content_type in cases:
                flow=SimpleNamespace(request=SimpleNamespace(host=host,path=path,method='POST',content=body,headers={'cookie':'secret-cookie'}),
                    response=SimpleNamespace(status_code=200,headers={'content-type':content_type},stream=None),metadata={})
                addon.request(flow);addon.responseheaders(flow)
                for byte in raw: self.assertEqual(flow.response.stream(bytes([byte])),bytes([byte]))
                flow.response.stream(b'');addon.response(flow)
            rows=store.list();self.assertEqual(len(rows),3)
            self.assertTrue(all(r['response']=='Hello' and r['status']=='complete' for r in rows))
            self.assertEqual({r['provider'] for r in rows},{'gemini','grok','meta'})
            self.assertNotIn('secret-cookie',store.export());self.assertNotIn('never-store',store.export())
            self.assertTrue(next(r for r in rows if r['provider']=='gemini')['source_url'].endswith('/example'))

    def test_binary_meta_transport_has_diagnostic_but_no_false_memory(self):
        with tempfile.TemporaryDirectory() as directory:
            store=Store(directory);addon=WebCapture(store)
            flow=SimpleNamespace(request=SimpleNamespace(host='gateway.meta.ai',path='/ws/clippy?Authorization=private'),metadata={})
            addon.websocket_message(flow)
            self.assertEqual(store.list(),[])
            with store.connect() as db: self.assertIsNone(db.execute('select * from capture_routes').fetchone())

    def test_dgw_diagnostic_never_persists_protobuf_text_or_authentication(self):
        secret=b'private-account-secret'
        payload=b'\x0a'+bytes([len(secret)])+secret
        envelope=json.dumps({'payload':base64.b64encode(payload).decode(),'Authorization':'private-auth'}).encode()
        frame=b'\x0d\x00\x01'+len(envelope).to_bytes(3,'little')+b'\x00\x80'+envelope
        info=diagnostic(frame)
        self.assertEqual(info['encoding'],'protobuf')
        self.assertEqual(info['fields'],{'1':'text'})
        self.assertNotIn('private',json.dumps(info))
        self.assertNotIn('private',json.dumps(diagnostic(b'\x0fprivate-auth')))

    def test_dgw_invalid_or_oversized_frame_is_bounded(self):
        self.assertIsNone(diagnostic(b'x'*262145))
        self.assertEqual(diagnostic(b'\x0d\x00\x01\xff\xff\xff\x00\x80{}')['encoding'],'unknown')
        envelope=b'{"payload":"invalid-base64"}'
        frame=b'\x0d\x00\x01'+len(envelope).to_bytes(3,'little')+b'\x00\x80'+envelope
        self.assertEqual(diagnostic(frame)['encoding'],'unrecognized')
