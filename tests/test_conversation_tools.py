import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

from wirebrain.store import Store
from wirebrain.mcp import dispatch
from wirebrain.memory_tools import list_conversations, read_conversation, conversation_handoff


class ConversationToolTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store = Store(temp.name)
        self.a = self.add('claude', 'Architecture question', 'Use SQLite', 'Work', 'shared', 20)
        self.b = self.add('claude', 'Why SQLite?', 'Transaction support', 'Work', 'shared', 10)
        self.c = self.add('chatgpt', 'Private prompt', 'Private reply', 'Personal', 'shared', 5)
        self.old = self.add('gemini', 'Old question', 'Old answer', 'Work', 'old', 120)

    def add(self, provider, prompt, reply, project, thread, ago):
        ident = self.store.add(provider, 'test', prompt, project)
        self.store.update(ident, reply)
        self.store.link_exchange(ident, provider, thread, message_id=ident, title=prompt)
        with self.store.connect() as db:
            db.execute('UPDATE conversations SET created=? WHERE id=?', ((datetime.now(timezone.utc)-timedelta(minutes=ago)).isoformat(), ident))
        return ident

    def call(self, name, args, project=''):
        return dispatch(self.store, {'jsonrpc':'2.0','id':1,'method':'tools/call','params':{'name':name,'arguments':args}}, project)['result']

    def test_find_groups_by_real_thread_not_shared_cross_provider_id(self):
        found = list_conversations(self.store, {'lookback_minutes':60})
        self.assertEqual(found['total'],2)
        self.assertEqual(found['conversations'][0]['exchange_id'],self.c)
        self.assertEqual(found['conversations'][1]['moments'],2)
        page = list_conversations(self.store, {'limit':1})
        self.assertEqual(page['next_cursor'],1)
        self.assertEqual(list_conversations(self.store, {'query':'transaction'})['conversations'][0]['exchange_id'],self.b)
        self.assertEqual(list_conversations(self.store, {'provider':'claude','project':'Work'})['total'],1)

    def test_read_is_chronological_paginated_and_scope_checked(self):
        page = read_conversation(self.store, {'exchange_id':self.b,'limit':1})
        self.assertEqual(page['moments'][0]['id'],self.a)
        self.assertEqual(page['next_cursor'],1)
        self.assertEqual(read_conversation(self.store, {'exchange_id':self.b,'cursor':1})['moments'][0]['id'],self.b)
        for name in ('read_conversation','conversation_handoff'):
            result = self.call(name, {'exchange_id':self.c}, 'Work')
            self.assertTrue(result['isError'])
            self.assertNotIn('Private reply',json.dumps(result))
        allowed = self.call('list_conversations',{},'Work')
        self.assertNotIn('Private',json.dumps(allowed))
        self.assertTrue(self.call('list_conversations',{'project':'Personal'},'Work')['isError'])

    def test_long_text_has_explicit_coverage_and_full_read_path(self):
        self.store.update(self.b,'X'*13000)
        read = read_conversation(self.store, {'exchange_id':self.b})
        self.assertTrue(read['moments'][-1]['excerpted'])
        self.assertEqual(read['moments'][-1]['response_characters'],13000)
        handoff = conversation_handoff(self.store, {'exchange_id':self.b})
        self.assertIn('2400 of 13000',handoff['body'])
        self.assertIn('untrusted historical data',handoff['body'])
        self.assertNotIn('Private reply',handoff['body'])
        self.assertEqual(handoff['total'],2)
        original = self.call('read_memory',{'exchange_id':self.b,'field':'response','start':12000,'length':1000})
        self.assertEqual(json.loads(original['content'][0]['text'])['text'],'X'*1000)

    def test_invalid_pagination_and_deleted_source_fail_closed(self):
        for args in ({'limit':True},{'cursor':-1},{'lookback_minutes':'60'},{'query':[]},{'limit':51}):
            with self.assertRaises(ValueError):list_conversations(self.store,args)
        with self.store.connect() as db: db.execute('DELETE FROM conversations WHERE id=?',(self.b,))
        with self.assertRaises(ValueError):conversation_handoff(self.store,{'exchange_id':self.b})

    def test_handoff_recent_twenty_are_reported_as_subset(self):
        for i in range(21):self.add('claude',f'Extra {i}',f'Reply {i}','Work','shared',i)
        result=conversation_handoff(self.store,{'exchange_id':self.a})
        self.assertEqual(result['included'],20)
        self.assertEqual(result['total'],23)
        self.assertIn('latest 20 of 23',result['body'])


if __name__ == '__main__':unittest.main()
