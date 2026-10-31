import json
import tempfile
import unittest
from unittest.mock import patch

from wirebrain.store import Store
from wirebrain.intelligence import settings
from wirebrain.personal_memory import save, action, state
from wirebrain.memory_rollups import overview, build, start, ERRORS


class MemoryRollupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        settings(self.store,{'chat_model':'writer','embedding_model':''})
        state(self.store,{'enabled':True})
        ERRORS.clear()

    def memory(self,text,provider='claude',scope=''):
        ident=save(self.store,{'text':text,'scope':scope})['id']
        source=self.store.add(provider,'web',text,scope or 'Web conversations')
        self.store.update(source,'Synthetic reply')
        with self.store.connect() as db:
            db.execute('INSERT INTO personal_memory_sources VALUES (?,?,?)',(ident,source,text))
        return ident,source

    def reply(self,path,payload):
        evidence=json.loads(payload['messages'][1]['content'])['memories']
        return {'message':{'content':json.dumps({'summary':'Consolidated context [1].','sources':[1]})}}

    @patch('wirebrain.intelligence.local_request')
    def test_whole_and_provider_summaries_cache_and_keep_scope(self,model):
        model.side_effect=self.reply
        self.memory('Prefers simple interfaces','claude')
        self.memory('Explored SQLite indexing','chatgpt')
        self.memory('Private Studio decision','claude','Studio')
        self.assertEqual(overview(self.store)['total'],2)
        self.assertEqual(overview(self.store,'claude')['total'],1)
        self.assertEqual(overview(self.store,'grok')['total'],0)
        whole=build(self.store)
        self.assertEqual(whole['title'],'Wirebrain memory')
        self.assertTrue(whole['summary'])
        build(self.store)
        self.assertEqual(model.call_count,1)
        build(self.store,'claude')
        self.assertEqual(model.call_count,2)
        sent=json.loads(model.call_args.args[1]['messages'][1]['content'])
        self.assertEqual(len(sent['memories']),1)
        self.assertNotIn('Private Studio',json.dumps(sent))
        self.assertEqual(overview(self.store,'claude','Studio')['total'],1)

    @patch('wirebrain.intelligence.local_request')
    def test_edit_and_forget_remove_cached_text_immediately(self,model):
        model.side_effect=self.reply
        ident,_=self.memory('Prefers quiet interfaces')
        build(self.store)
        save(self.store,{'id':ident,'text':'Prefers readable interfaces'})
        self.assertEqual(overview(self.store)['summary'],'')
        build(self.store)
        action(self.store,{'id':ident,'action':'forget'})
        self.assertEqual(overview(self.store)['summary'],'')
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM memory_rollups').fetchone()[0],0)

    @patch('wirebrain.intelligence.local_request')
    def test_source_deleted_during_generation_does_not_resurrect_summary(self,model):
        _,source=self.memory('Prefers readable interfaces')
        def run(path,payload):
            self.store.delete(source)
            return self.reply(path,payload)
        model.side_effect=run
        self.assertTrue(build(self.store)['changed'])
        self.assertEqual(overview(self.store)['summary'],'')

    @patch('wirebrain.intelligence.local_request')
    def test_suggestions_are_excluded_and_invalid_citations_rejected(self,model):
        ident,_=self.memory('A possible personal preference')
        with self.store.connect() as db:db.execute("UPDATE personal_memory SET status='suggested' WHERE id=?",(ident,))
        self.assertEqual(overview(self.store)['total'],0)
        self.memory('A reviewed preference')
        model.return_value={'message':{'content':json.dumps({'summary':'Unsupported [99].','sources':[1]})}}
        with self.assertRaises(ValueError):build(self.store)
        self.assertFalse(overview(self.store)['summary'])

    @patch('wirebrain.intelligence.local_request')
    def test_empty_or_paused_memory_does_not_start_inference(self,model):
        self.assertEqual(start(self.store,'gemini')['total'],0)
        self.memory('A reviewed preference')
        state(self.store,{'enabled':False})
        self.assertFalse(start(self.store)['building'])
        model.assert_not_called()

    def test_unknown_provider_is_rejected(self):
        with self.assertRaises(ValueError):overview(self.store,'../../private')

    @patch('wirebrain.intelligence.local_request')
    def test_overview_prompt_revision_invalidates_cached_draft(self,model):
        model.side_effect=self.reply
        self.memory('Prefers readable interfaces')
        build(self.store)
        with patch('wirebrain.memory_rollups.render_prompt',return_value='A changed overview instruction.'):
            self.assertTrue(overview(self.store)['needs_refresh'])
            self.assertEqual(overview(self.store)['summary'],'')
            build(self.store)
        self.assertEqual(model.call_count,2)
