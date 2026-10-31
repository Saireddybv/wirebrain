import json
import tempfile
import unittest
from unittest.mock import patch

from wirebrain.store import Store
from wirebrain.intelligence import settings, collection, ask
from wirebrain.personal_memory import (extract_batch, list_memories, retrieve, save, action,
    state, index_facts, start_extraction)
from wirebrain.diary import export_diary
from wirebrain.importer import import_history
from wirebrain.mcp import dispatch


class PersonalMemoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.store = Store(self.tmp.name)
        settings(self.store, {'chat_model':'writer','embedding_model':''})

    def source(self, prompt='I prefer simple interfaces without animations.', provider='claude', project='Web conversations'):
        ident = self.store.add(provider, 'web', prompt, project)
        self.store.update(ident, 'This assistant reply must never be extracted.')
        with self.store.connect() as db:
            db.execute('UPDATE conversations SET created=? WHERE id=?', ('2020-01-01T10:00:00+00:00', ident))
        return ident

    def model(self, path, payload=None):
        self.assertEqual(path, 'chat')
        human = json.loads(payload['messages'][1]['content'])['quoted_human_message']
        self.assertNotIn('assistant reply', human)
        return {'message': {'content':json.dumps({'memories':[{'text':'Prefers simple interfaces without animations.', 'quote':human, 'kind':'preference'}]})}}

    @patch('wirebrain.intelligence.local_request')
    def test_suggestions_require_review_have_evidence_and_deduplicate_across_apps(self, model):
        a = self.source()
        self.source(provider='chatgpt')
        model.side_effect = self.model
        result = extract_batch(self.store, force=True)
        self.assertEqual(result['suggested'], 1)
        self.assertEqual(retrieve(self.store, 'interfaces'), [])
        suggested = list_memories(self.store, status='suggested')
        self.assertEqual(len(suggested), 1)
        self.assertEqual(len(suggested[0]['sources']), 2)
        action(self.store, {'id':suggested[0]['id'], 'action':'approve'})
        found = retrieve(self.store, 'interfaces', provider='claude')
        self.assertEqual(len(found), 1)
        self.assertIn(a, [s['exchange_id'] for s in found[0]['sources']])
        self.assertNotIn('history', found[0])
        self.assertEqual(extract_batch(self.store, force=True)['processed'], 0)
        self.assertEqual(model.call_count, 2)

    @patch('wirebrain.intelligence.local_request')
    def test_idle_thread_waits_and_streaming_or_demo_sources_are_ignored(self, model):
        old = self.source()
        self.store.link_exchange(old,'claude','same-chat')
        fresh = self.store.add('claude','web','Still working here', 'Web conversations')
        self.store.link_exchange(fresh,'claude','same-chat')
        demo = self.store.add('claude','web','I like demos',demo=True)
        self.store.update(demo,'Done')
        self.assertEqual(extract_batch(self.store,force=True)['processed'],0)
        model.assert_not_called()

    @patch('wirebrain.intelligence.local_request')
    def test_invalid_evidence_and_secrets_leave_message_unprocessed(self, model):
        ident = self.source()
        for text, quote in [('Invented fact','Not in the message'), ('password=abcdef123456','I prefer simple interfaces without animations.')]:
            model.return_value={'message':{'content':json.dumps({'memories':[{'text':text,'quote':quote,'kind':'fact'}]})}}
            with self.assertRaises(ValueError): extract_batch(self.store,force=True)
            with self.store.connect() as db:
                self.assertEqual(db.execute('SELECT count(*) FROM personal_memory').fetchone()[0],0)
                self.assertIsNone(db.execute('SELECT * FROM personal_memory_inputs WHERE exchange_id=?',(ident,)).fetchone())
            self.assertTrue(state(self.store)['error'])

    @patch('wirebrain.intelligence.local_request')
    def test_forgetting_suppresses_source_reprocessing_and_duplicate_fact(self, model):
        ident = self.source()
        model.side_effect=self.model
        extract_batch(self.store,force=True)
        memory=list_memories(self.store,status='suggested')[0]
        action(self.store,{'id':memory['id'],'action':'forget'})
        with self.store.connect() as db: db.execute('UPDATE conversations SET prompt=? WHERE id=?',('I prefer simple interfaces without animations. Still true.',ident))
        self.source(provider='chatgpt')
        extract_batch(self.store,force=True)
        self.assertEqual(list_memories(self.store,status='suggested'),[])
        self.assertEqual(list_memories(self.store),[])

    @patch('wirebrain.intelligence.local_request')
    def test_deletion_during_extraction_does_not_resurrect_memory(self, model):
        ident = self.source()
        def generate(path,payload):
            self.store.delete(ident)
            return self.model(path,payload)
        model.side_effect=generate
        extract_batch(self.store,force=True)
        self.assertEqual(list_memories(self.store,status='suggested'),[])

    @patch('wirebrain.intelligence.local_request')
    def test_source_edit_and_collection_move_invalidate_derived_memory(self, model):
        ident=self.source(project='Studio')
        model.side_effect=self.model
        extract_batch(self.store,force=True)
        fact=list_memories(self.store,status='suggested')[0]
        action(self.store,{'id':fact['id'],'action':'approve'})
        self.assertEqual(retrieve(self.store,'interfaces'),[])
        self.assertEqual(len(retrieve(self.store,'interfaces',scope='Studio')),1)
        collection(self.store,ident,'Other project')
        self.assertEqual(retrieve(self.store,'interfaces',scope='Studio'),[])
        extract_batch(self.store,force=True)
        self.assertEqual(list_memories(self.store,status='suggested')[0]['scope'],'Other project')
        with self.store.connect() as db: db.execute('UPDATE conversations SET prompt=? WHERE id=?',('A corrected message',ident))
        self.assertEqual(list_memories(self.store,status='suggested'),[])

    def test_manual_edit_history_scope_and_fixed_mcp_scope(self):
        memory=save(self.store,{'text':'Prefers concise interfaces','kind':'preference'})
        save(self.store,{'id':memory['id'],'text':'Prefers readable interfaces','scope':'Studio'})
        self.assertEqual(retrieve(self.store,'interfaces'),[])
        fact=list_memories(self.store,scope='Studio')[0]
        self.assertEqual(len(fact['history']),1)
        self.assertNotIn('history',retrieve(self.store,'interfaces',scope='Studio')[0])
        response=dispatch(self.store,{'id':1,'method':'tools/call','params':{'name':'search_personal_memory','arguments':{'query':'interfaces'}}},project='Studio')
        self.assertEqual(len(json.loads(response['result']['content'][0]['text'])),1)
        denied=dispatch(self.store,{'id':2,'method':'tools/call','params':{'name':'search_personal_memory','arguments':{'query':'interfaces','project':'Other'}}},project='Studio')
        self.assertTrue(denied['result']['isError'])

    @patch('wirebrain.intelligence.local_request')
    def test_semantic_fact_index_is_incremental_and_deleted_facts_disappear(self, model):
        a=save(self.store,{'text':'Prefers quiet interfaces'})['id']
        save(self.store,{'text':'Private project information','scope':'Secret'})
        settings(self.store,{'chat_model':'writer','embedding_model':'embed'})
        model.side_effect=lambda path,payload: {'embeddings':[[1.,0.] for _ in payload['input']]}
        index_facts(self.store);index_facts(self.store)
        self.assertEqual(model.call_count,1)
        found=retrieve(self.store,'calm layouts',mode='semantic')
        self.assertEqual([row['id'] for row in found],[a])
        action(self.store,{'id':a,'action':'forget'})
        self.assertEqual(retrieve(self.store,'calm layouts',mode='semantic'),[])

    @patch('wirebrain.intelligence.local_request')
    def test_backup_roundtrip_evidence_remapping_and_local_forget_wins(self, model):
        ident=self.source()
        model.side_effect=self.model
        extract_batch(self.store,force=True)
        fact=list_memories(self.store,status='suggested')[0]
        action(self.store,{'id':fact['id'],'action':'approve'})
        backup=export_diary(self.store)
        with tempfile.TemporaryDirectory() as home:
            restored=Store(home)
            import_history(restored,backup);import_history(restored,backup)
            facts=list_memories(restored)
            self.assertEqual(len(facts),1)
            self.assertTrue(restored.list(exchange_id=facts[0]['sources'][0]['exchange_id']))
            action(restored,{'id':facts[0]['id'],'action':'forget'})
            import_history(restored,backup)
            self.assertEqual(list_memories(restored),[])
        self.store.delete(ident)
        self.assertEqual(list_memories(self.store),[])

    def test_invalid_memory_backup_is_atomic(self):
        self.source()
        backup=export_diary(self.store)
        backup['personal_memory']['facts']=[{'text':'A useful preference','kind':'fact','scope':'','status':'approved','sources':[{'exchange_id':'missing','quote':'Missing evidence'}]}]
        with tempfile.TemporaryDirectory() as home:
            store=Store(home)
            with self.assertRaises(ValueError):import_history(store,backup)
            self.assertEqual(store.list(),[])

    def test_no_local_model_manual_memory_and_approved_only_ask(self):
        settings(self.store,{'chat_model':'','embedding_model':''})
        save(self.store,{'text':'Prefers simple interfaces'})
        with self.assertRaises(ValueError):start_extraction(self.store)
        result=ask(self.store,{'query':'interfaces','memory_only':True,'use_personal_memory':True})
        self.assertEqual(len(result['memories']),1)
        self.assertFalse(result['generated'])
        self.assertEqual(result['sources'],[])
        self.assertFalse(state(self.store)['enabled'])

    @patch('wirebrain.intelligence.local_request')
    def test_model_reply_is_not_extracted_and_project_facts_are_not_used_globally(self, model):
        self.source(project='Private')
        model.side_effect=self.model
        extract_batch(self.store,force=True)
        fact=list_memories(self.store,status='suggested')[0]
        action(self.store,{'id':fact['id'],'action':'approve'})
        result=ask(self.store,{'query':'interfaces','memory_only':True,'use_personal_memory':True})
        self.assertEqual(result['memories'],[])
        self.assertEqual(result['sources'],[])
        result=ask(self.store,{'query':'interfaces','memory_only':True,'use_personal_memory':True,'project':'Private'})
        self.assertEqual(len(result['memories']),1)
        self.assertEqual(len(result['sources']),1)

    @patch('wirebrain.intelligence.local_request')
    def test_research_topics_appear_automatically_with_evidence(self, model):
        prompt='When is model Carbon going to launch?'
        self.source(prompt)
        model.return_value={'message':{'content':json.dumps({'memories':[{'text':'Asked about the launch timing of model Carbon.','quote':prompt,'kind':'topic'}]})}}
        extract_batch(self.store,force=True)
        memories=list_memories(self.store,status='all')
        self.assertEqual(memories[0]['status'],'automatic')
        self.assertEqual(memories[0]['kind'],'topic')
        self.assertEqual(len(retrieve(self.store,'Carbon')),1)
        self.assertEqual(list_memories(self.store,status='suggested'),[])

    @patch('wirebrain.intelligence.local_request')
    def test_greetings_test_markers_and_obvious_roleplay_do_not_cost_inference(self, model):
        for prompt in ('Wirebrain test: reply hello','hi Gemini again','i am doramon'):
            self.source(prompt)
        extract_batch(self.store,force=True)
        extract_batch(self.store,force=True)
        model.assert_not_called()
        self.assertEqual(extract_batch(self.store,force=True)['processed'],0)

    @patch('wirebrain.intelligence.local_request')
    def test_topic_label_does_not_automatically_approve_an_answer_claim(self, model):
        prompt='When is model Carbon going to launch?'
        self.source(prompt)
        model.return_value={'message':{'content':json.dumps({'memories':[{'text':'Model Carbon launches Friday.','quote':prompt,'kind':'topic'}]})}}
        extract_batch(self.store,force=True)
        self.assertEqual(retrieve(self.store,'Carbon'),[])
        self.assertEqual(len(list_memories(self.store,status='suggested')),1)


if __name__=='__main__': unittest.main()
