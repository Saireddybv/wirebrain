import json
import tempfile
import unittest
from types import SimpleNamespace
from wirebrain.grok_socket import GrokSocket
from wirebrain.store import Store


class GrokSocketTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name);self.capture=GrokSocket(self.store);self.messages=[]

    def send(self,kind,outgoing=False,cid='chat-a',**extra):
        self.messages.append(SimpleNamespace(from_client=outgoing,content=json.dumps({'session_id':cid,'event':{'type':kind,**extra}}).encode()))
        self.capture.receive(self.messages)

    def prompt(self,cid='chat-a'):
        self.send('conversation.item.create',True,cid,item={'role':'user','x_grok':{'client_message_id':'m','input_chunks':[{'text':{'text':'Hello'}}]}},parent_response_id='parent')
        self.send('response.create',True,cid,event_id='create')

    def test_only_submitted_user_turns_saved_and_linked(self):
        self.send('conversation.item.create',True,item={'role':'assistant','x_grok':{'input_chunks':[{'text':{'text':'not a user'}}]}})
        self.send('response.create',True,event_id='ignored')
        self.assertEqual(self.store.list(),[])
        self.prompt()
        self.send('response.output_item.added',item={'role':'assistant','id':'answer'})
        self.send('response.chunk',chunk={'text':{'text':'private','channel':'THINKING'}})
        self.send('response.chunk',chunk={'text':{'text':'Hello 世界','channel':'FINAL'}})
        self.send('response.done',response={'id':'answer','status':'completed'})
        row=self.store.list()[0]
        self.assertEqual((row['prompt'],row['response'],row['status']),('Hello','Hello 世界','complete'))
        self.assertEqual(row['conversation_id'],'chat-a');self.assertEqual(row['response_message_id'],'answer')
        self.assertEqual(row['source_url'],'https://grok.com/c/chat-a')
        self.capture.receive(self.messages);self.assertEqual(len(self.store.list()),1)

    def test_distinct_chats_and_text_modes_do_not_merge_or_duplicate(self):
        for cid in ('chat-a','chat-b'):
            self.prompt(cid)
            self.send('response.output_text.delta',False,cid,delta='hello')
            self.send('response.chunk',False,cid,chunk={'text':{'text':'hello','channel':'FINAL'}})
            self.send('response.done',False,cid,response={'status':'completed'})
        rows=self.store.list();self.assertEqual(len({r['thread_id'] for r in rows}),2)
        self.assertTrue(all(r['response']=='hello' for r in rows))

    def test_stream_failure_and_disconnect_preserve_partial(self):
        self.prompt();self.send('response.output_text.delta',delta='Partial')
        self.send('response.grok.output',output={'stream_error':{'kind':'usage_limit'}})
        self.assertEqual(self.store.list()[0]['status'],'error')
        self.capture.finish()
        self.assertEqual(self.store.list()[0]['response'],'Partial')

    def test_no_authentication_or_unsupported_event_values_are_saved(self):
        self.send('session.create',True,session={'model':'fast','x_grok':{'conversation_id':'chat-a'},'authorization':'secret-auth'})
        self.send('unrelated.analytics',data={'text':'do-not-save'})
        self.prompt();self.send('response.output_text.delta',delta='answer')
        self.send('response.done',response={'status':'completed'})
        self.assertNotIn('secret-auth',self.store.export());self.assertNotIn('do-not-save',self.store.export())

    def test_current_browser_combines_user_item_with_response_create(self):
        self.send('session.create',True,'socket-session',session={'model':'fast','x_grok':{'conversation_id':'real-conversation'}})
        self.send('response.create',True,'socket-session',event_id='create-inline',item={'role':'user','x_grok':{
            'client_message_id':'user-inline','input_chunks':[{'text':{'text':'Inline prompt'}}]}})
        self.send('response.chunk',False,'socket-session',chunk={'text':{'text':'hel','channel':'FINAL'}})
        self.send('response.output_text.done',False,'socket-session',text='hello')
        self.send('response.done',False,'socket-session',response={'id':'answer-inline','status':'completed'})
        row=self.store.list()[0]
        self.assertEqual((row['prompt'],row['response'],row['status']),('Inline prompt','hello','complete'))
        self.assertEqual(row['conversation_id'],'real-conversation')
        self.assertEqual(row['source_url'],'https://grok.com/c/real-conversation')

    def test_history_repairs_only_an_already_recorded_reply(self):
        self.prompt();self.send('response.done',response={'id':'answer-repair','status':'completed'})
        self.assertEqual(self.store.list()[0]['status'],'unsupported')
        item={'id':'unrelated','role':'assistant','status':'completed','content':[{'type':'output_text','text':'Other chat'}]}
        self.send('conversation.history.item',item=item)
        self.assertEqual(self.store.list()[0]['response'],'')
        item.update(id='answer-repair',content=[{'type':'output_text','text':'hello'}])
        self.send('conversation.history.item',item=item)
        self.assertEqual(len(self.store.list()),1)
        self.assertEqual((self.store.list()[0]['response'],self.store.list()[0]['status']),('hello','complete'))
