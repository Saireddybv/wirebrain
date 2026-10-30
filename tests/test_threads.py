import json
import tempfile
import unittest
from datetime import datetime, timezone

from wirebrain.store import Store
from wirebrain.webcapture import generation_request, WebStream
from wirebrain.mitm_addon import WebCapture
from types import SimpleNamespace


class ThreadTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)

    def test_same_chat_groups_followups_different_chats_stay_separate(self):
        a = self.store.add('chatgpt', 'auto', 'First question')
        b = self.store.add('chatgpt', 'auto', 'Follow-up')
        c = self.store.add('chatgpt', 'auto', 'Separate chat')
        self.store.link_exchange(a, 'chatgpt', 'chat-a', 'user-a')
        self.store.link_exchange(b, 'chatgpt', 'chat-a', 'user-b', 'assistant-a')
        self.store.link_exchange(c, 'chatgpt', 'chat-b', 'user-c')
        self.assertEqual([r['id'] for r in self.store.thread(a)], [a,b])
        self.assertEqual([r['id'] for r in self.store.thread(c)], [c])
        self.assertEqual(self.store.thread(b)[1]['parent_message_id'], 'assistant-a')
        self.assertEqual(self.store.thread(a)[0]['source_url'], 'https://chatgpt.com/c/chat-a')

    def test_namespace_and_unknown_identity_never_merge(self):
        a = self.store.add('chatgpt', 'auto', 'Same question')
        b = self.store.add('claude', 'auto', 'Same question')
        c = self.store.add('chatgpt', 'auto', 'Same question')
        self.store.link_exchange(a, 'chatgpt', 'same-id')
        self.store.link_exchange(b, 'claude', 'same-id')
        self.assertEqual(len(self.store.thread(a)),1)
        self.assertEqual(len(self.store.thread(b)),1)
        self.assertEqual([r['id'] for r in self.store.thread(c)],[c])
        self.assertIsNone(self.store.thread(c)[0]['thread_id'])

    def test_new_chat_response_binds_request_without_losing_message_ids(self):
        a = self.store.add('chatgpt', 'auto', 'New chat')
        self.store.link_exchange(a, 'chatgpt', None, 'user-1', 'parent-0')
        self.store.link_exchange(a, 'chatgpt', 'created-id', response_message_id='assistant-1')
        row = self.store.thread(a)[0]
        self.assertEqual(row['conversation_id'], 'created-id')
        self.assertEqual(row['message_id'], 'user-1')
        self.assertEqual(row['parent_message_id'], 'parent-0')
        self.assertEqual(row['response_message_id'], 'assistant-1')
        self.store.link_exchange(a, 'chatgpt', 'different-id')
        self.assertEqual(self.store.thread(a)[0]['conversation_id'], 'created-id')

    def test_provider_adapters_extract_source_ids(self):
        data = {'conversation_id':'chat-a','parent_message_id':'parent-a','messages':[{'id':'message-a','author':{'role':'user'},'content':{'parts':['Hi']}}]}
        req = generation_request('chatgpt.com','/backend-api/f/conversation',json.dumps(data))
        self.assertEqual(req['conversation_id'], 'chat-a')
        self.assertEqual(req['message_id'], 'message-a')
        claude = generation_request('claude.ai','/api/organizations/org-a/chat_conversations/chat-a/completion', json.dumps({'prompt':'Hi','turn_message_uuids':{'human_message_uuid':'human-a'},'parent_message_uuid':'parent-a'}))
        self.assertEqual(claude['conversation_id'], 'org-a/chat-a')
        self.assertEqual(claude['message_id'], 'human-a')
        stream = WebStream('chatgpt')
        stream.event({'v':{'conversation_id':'new-chat','message':{'id':'assistant-a','author':{'role':'assistant'},'content':{'content_type':'text','parts':['Hi']}}}})
        self.assertEqual(stream.conversation_id, 'new-chat')
        self.assertEqual(stream.response_message_id, 'assistant-a')

    def test_history_attaches_legacy_completed_exchange_to_known_chat(self):
        a = self.store.add('chatgpt','auto','Hello')
        self.store.update(a,'Full response')
        data = {'conversation_id':'known-chat','title':'My chat','current_node':'assistant','mapping':{
            'user':{'parent':None,'message':{'author':{'role':'user'},'create_time':datetime.now(timezone.utc).timestamp(),'content':{'content_type':'text','parts':['Hello']}}},
            'assistant':{'parent':'user','message':{'author':{'role':'assistant'},'status':'finished_successfully','content':{'content_type':'text','parts':['Full response']}}}
        }}
        self.assertEqual(self.store.repair_chatgpt_history(data),0)
        row = self.store.thread(a)[0]
        self.assertEqual(row['conversation_id'],'known-chat')
        self.assertEqual(row['thread_title'],'My chat')
        self.assertEqual(row['message_id'],'user')

    def test_addon_links_new_chat_from_streamed_server_id(self):
        body = {'messages':[{'id':'user-1','author':{'role':'user'},'content':{'parts':['Hello']}}]}
        flow = SimpleNamespace(request=SimpleNamespace(method='POST',host='chatgpt.com',path='/backend-api/f/conversation',content=json.dumps(body).encode(),headers={}),
            response=SimpleNamespace(status_code=200,headers={'content-type':'text/event-stream'},stream=None),metadata={})
        addon = WebCapture(self.store)
        addon.request(flow)
        addon.responseheaders(flow)
        event = {'conversation_id':'new-chat','message':{'id':'assistant-1','author':{'role':'assistant'},'content':{'content_type':'text','parts':['Hello there']}}}
        flow.response.stream(('data: '+json.dumps(event)+'\n\ndata: [DONE]\n\n').encode())
        flow.response.stream(b'')
        addon.response(flow)
        row=self.store.list()[0]
        self.assertEqual(row['conversation_id'],'new-chat')
        self.assertEqual(row['response_message_id'],'assistant-1')
        self.assertEqual(row['message_id'],'user-1')
