import json
import tempfile
import unittest
from unittest.mock import patch

from wirebrain.store import Store
from wirebrain.intelligence import settings, index_batch, search, ask, overview, collection
from wirebrain.importer import import_history


class IntelligenceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(self.temp.name)
        self.a = self.store.add('claude','web','Acquiring clients','Studio')
        self.store.update(self.a,'Referral partnerships')
        self.b = self.store.add('chatgpt','web','Baking bread','Kitchen')
        self.store.update(self.b,'Use flour and yeast')
        settings(self.store,{'embedding_model':'test','chat_model':'writer'})

    def fake(self,path,payload=None):
        if path=='embed':
            return {'embeddings': [[1.,0.] if any(w in text.lower() for w in ('clients','customers','referral')) else [0.,1.] for text in payload['input']]}
        return {'message':{'content':'You explored referrals [1].'}}

    def test_overview_reports_free_disk_space_and_handles_unavailable_disk(self):
        from collections import namedtuple
        usage = namedtuple('usage', 'total used free')(10000000, 4000000, 6000000)
        with patch('wirebrain.intelligence.shutil.disk_usage', return_value=usage) as disk:
            result = overview(self.store)
            self.assertEqual(result['free_bytes'], 6000000)
            self.assertGreater(result['bytes'], 0)
            disk.assert_called_once_with(self.store.home)
        with patch('wirebrain.intelligence.shutil.disk_usage', side_effect=OSError('unavailable')):
            result = overview(self.store)
            self.assertIsNone(result['free_bytes'])
            self.assertEqual(result['conversations'], 2)

    @patch('wirebrain.intelligence.local_request')
    def test_meaning_without_keyword_and_index_invalidation(self,request):
        request.side_effect=self.fake
        self.assertEqual(search(self.store,'customers')['rows'],[])
        self.assertEqual(index_batch(self.store)['indexed'],2)
        self.assertEqual(index_batch(self.store)['indexed'],0)
        found=search(self.store,'customers','semantic')
        self.assertEqual(found['rows'][0]['id'],self.a)
        self.assertEqual(found['unindexed'],0)
        self.store.update(self.a,'A changed response')
        self.assertEqual(search(self.store,'customers','semantic')['unindexed'],1)
        index_batch(self.store)
        self.store.delete(self.a)
        self.assertNotIn(self.a,[r['id'] for r in search(self.store,'customers','semantic')['rows']])
        with self.store.connect() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM memory_vectors WHERE exchange_id=?',(self.a,)).fetchone()[0],0)

    @patch('wirebrain.intelligence.local_request')
    def test_provider_and_collection_filter_before_ranking(self,request):
        request.side_effect=self.fake;index_batch(self.store)
        self.assertEqual(search(self.store,'customers','semantic','chatgpt','Studio')['rows'],[])
        result=ask(self.store,{'query':'customers','mode':'semantic','provider':'claude','generate':True})
        self.assertEqual(len(result['sources']),1)
        self.assertIn('[1]',result['answer'])
        self.assertTrue(result['generated'])

    def test_collection_applies_whole_thread_and_exports(self):
        self.store.link_exchange(self.a,'claude','chat-1')
        c=self.store.add('claude','web','Follow up')
        self.store.link_exchange(c,'claude','chat-1')
        collection(self.store,self.a,'Business')
        self.assertEqual({r['project'] for r in self.store.thread(c)},{'Business'})
        self.assertEqual(len(self.store.list('Business')),2)
        self.assertEqual(overview(self.store)['conversations'],2)

    def test_no_model_and_cloud_model_are_explicit(self):
        settings(self.store,{'embedding_model':'','chat_model':''})
        with self.assertRaises(ValueError): search(self.store,'x','semantic')
        with self.assertRaises(ValueError): settings(self.store,{'chat_model':'large-cloud'})

    @patch('wirebrain.intelligence.local_request')
    def test_invalid_vector_does_not_poison_index(self,request):
        request.return_value={'embeddings':[[float('nan')],[1.]]}
        with self.assertRaises(ValueError):index_batch(self.store)
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM memory_vectors').fetchone()[0],0)

    def test_import_is_validated_before_writes_and_idempotent(self):
        row={'provider':'claude','prompt':'Imported secret=abcdefgh123456','response':'A reply','created':'2026-10-30T10:00:00Z','conversation_id':'import-chat','favorite':True}
        with self.assertRaises(ValueError):import_history(self.store,[row,{'bad':'row'}])
        self.assertEqual(overview(self.store)['moments'],2)
        self.assertEqual(import_history(self.store,[row])['imported'],1)
        self.assertEqual(import_history(self.store,[row])['skipped'],1)
        imported=self.store.list('Imported')[0]
        self.assertNotIn('abcdefgh123456',imported['prompt'])
        self.assertTrue(imported['favorite'])
        self.assertTrue(imported['thread_id'])

    def test_claude_import_pairs_and_preserves_dates(self):
        data=[{'uuid':'chat','name':'Imported chat','chat_messages':[
            {'sender':'human','text':'Question','created_at':'2026-10-30T10:00:00+05:30'},
            {'sender':'assistant','text':'Answer'}]}]
        self.assertEqual(import_history(self.store,data)['imported'],1)
        self.assertEqual(self.store.list('Question')[0]['created'],'2026-10-30T04:30:00+00:00')
