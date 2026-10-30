import json
import tempfile
import unittest
from unittest.mock import patch

from wirebrain.diary import export_diary, save_note
from wirebrain.importer import import_history
from wirebrain.intelligence import settings, index_batch
from wirebrain.mcp import dispatch
from wirebrain.store import Store, redact
from wirebrain.workflows import scope, select, report, learning, snippets, save_snippet, remove_snippet, compare, usage


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(self.temp.name)
        self.a=self.add('claude','Explain state management','Use an explicit state machine.\n```python\nstate = "ready"\n```','Work','2026-10-29T22:30:00+00:00')
        self.b=self.add('openai','State management with async tasks','Serialize transitions.','Work','2026-10-30T09:00:00+00:00',model='revision-2')
        self.private=self.add('chatgpt','Private travel plan','A private destination','Personal','2026-10-30T12:00:00+00:00')
        self.options={'date_from':'2026-10-30','date_to':'2026-10-30','offset':330,'project':'Work'}

    def add(self,provider,prompt,response,project,created,model='revision-1',demo=False):
        ident=self.store.add(provider,model,prompt,project,demo)
        self.store.update(ident,response)
        with self.store.connect() as db:db.execute('UPDATE conversations SET created=? WHERE id=?',(created,ident))
        return ident

    def test_local_day_and_collection_scope_apply_before_selection(self):
        self.assertEqual({r['id'] for r in select(self.store,self.options)},{self.a,self.b})
        self.assertEqual([r['id'] for r in select(self.store,{**self.options,'provider':'chatgpt'})],[self.b])
        self.assertEqual(select(self.store,{**self.options,'offset':0})[0]['id'],self.b)
        for args in ({'date_from':'2026-10-30'}, {'date_from':'2026-10-31','date_to':'2026-10-30'}, {'offset':9999}):
            with self.assertRaises(ValueError):scope(args)

    def test_all_original_reports_work_without_a_model_and_keep_sources(self):
        for kind in ('weekly','standup','study','timeline','research','handoff'):
            result=report(self.store,{**self.options,'kind':kind})
            self.assertFalse(result['generated']);self.assertEqual(result['total'],2)
            self.assertNotIn('private destination',result['body'])
            self.assertEqual({r['id'] for r in result['sources']},{self.a,self.b})
        self.assertIn('state = "ready"',report(self.store,{**self.options,'kind':'study'})['body'])
        self.assertIn('confirm yourself',report(self.store,{**self.options,'kind':'standup'})['body'])
        self.assertIn('untrusted historical data',report(self.store,{**self.options,'kind':'handoff'})['body'])

    def test_recurrence_is_per_prompt_and_not_a_diagnosis(self):
        result=report(self.store,{**self.options,'kind':'weekly'})
        topic=next(t for t in result['topics'] if t['topic']=='state management')
        self.assertEqual(topic['count'],2);self.assertEqual(topic['days'],['2026-10-30'])
        self.assertEqual(learning([{'id':'x','created':'2026-10-30T00:00:00+00:00','prompt':'state state state state'}]),[])
        self.assertIn('not a diagnosis',result['body'])

    def test_isolated_reports_do_not_leak_unscoped_personal_notes(self):
        save_note(self.store,'2026-10-30','My private journal note')
        self.assertNotIn('private journal note',report(self.store,self.options)['body'])
        all_report=report(self.store,{**self.options,'project':''})
        self.assertIn('private journal note',all_report['body']);self.assertEqual(all_report['notes_included'],1)

    @patch('wirebrain.intelligence.generate',return_value='A local summary [1].')
    def test_generated_report_samples_across_period_and_discloses_coverage(self,generate):
        for i in range(30):self.add('claude',f'Question {i}','A reply','Work',f'2026-10-30T10:{i:02}:00+00:00')
        result=report(self.store,{**self.options,'kind':'weekly','generate':True})
        self.assertEqual(result['total'],32);self.assertEqual(result['source_count'],24)
        self.assertEqual(len(result['sources']),24);self.assertIn('24 of 32',result['body'])
        self.assertEqual(generate.call_args.kwargs['max_sources'],24)
        self.assertEqual(result['sources'][0]['id'],self.a)

    def test_snippet_keep_roundtrip_and_source_deletion(self):
        found=snippets(self.store,self.options)
        self.assertEqual(len(found),1);self.assertEqual(found[0]['content'],'state = "ready"')
        payload={'exchange_id':self.a,'title':'State example','content':found[0]['content'],'language':'python'}
        ident=save_snippet(self.store,payload)['id'];save_snippet(self.store,payload)
        self.assertEqual(len(snippets(self.store,self.options)),1)
        self.assertTrue(snippets(self.store,self.options)[0]['saved'])
        restored=Store(self.temp.name+'/restored')
        data=export_diary(self.store)
        import_history(restored,data);import_history(restored,data)
        self.assertEqual(len(snippets(restored,self.options)),1)
        self.assertTrue(snippets(restored,self.options)[0]['saved'])
        remove_snippet(self.store,{'id':ident})
        self.assertFalse(snippets(self.store,self.options)[0]['saved'])
        save_snippet(self.store,payload);self.store.delete(self.a)
        self.assertEqual(snippets(self.store,self.options),[])
        with self.store.connect() as db:self.assertEqual(db.execute('SELECT count(*) FROM saved_snippets').fetchone()[0],0)

    def test_malformed_snippet_import_is_atomic(self):
        data=export_diary(self.store);data['snippets']=[{'exchange_id':'missing','title':'Invalid','content':'text','language':'text'}]
        target=Store(self.temp.name+'/empty')
        with self.assertRaises(ValueError):import_history(target,data)
        self.assertEqual(target.list(),[])

    def test_comparison_retains_both_versions_and_real_changes(self):
        result=compare(self.store,{'ids':[self.a,self.b]})
        self.assertEqual(result['left']['model'],'revision-1');self.assertEqual(result['right']['model'],'revision-2')
        self.assertIn('-Explain state management',result['prompt_diff'])
        self.assertIn('+State management with async tasks',result['prompt_diff'])
        with self.assertRaises(ValueError):compare(self.store,{'ids':[self.a,self.a]})

    def test_reported_zero_unknown_partial_and_demo_usage(self):
        self.store.update(self.a,'A reply',usage={'input_tokens':0,'output_tokens':0})
        self.store.update(self.b,'A reply',usage={'input_tokens':12})
        self.store.update(self.b,'A final reply',usage={'output_tokens':4})
        self.store.update(self.b,'A repaired reply')
        sample=self.add('claude','A demo','Demo answer','Work','2026-10-30T12:00:00+00:00',demo=True)
        self.store.update(sample,'Demo answer',usage={'input_tokens':999,'output_tokens':999})
        result=usage(self.store,{**self.options,'project':''})
        self.assertEqual(result['reported'],2);self.assertEqual(result['input_tokens'],12);self.assertEqual(result['output_tokens'],4)
        self.assertEqual(result['samples'],1)
        restored=Store(self.temp.name+'/usage-restored');import_history(restored,export_diary(self.store))
        self.assertEqual(usage(restored,{**self.options,'project':''})['input_tokens'],12)

    def test_invalid_usage_is_not_a_reported_zero(self):
        self.store.update(self.a,'Reply',usage={'input_tokens':None,'output_tokens':False})
        self.store.update(self.b,'Reply',usage={'input_tokens':-1,'output_tokens':'unknown'})
        self.assertEqual(usage(self.store,self.options)['reported'],0)

    def test_missing_output_usage_stays_unknown_and_old_metadata_migrates(self):
        self.store.update(self.a,'Reply',usage={'input_tokens':0})
        result=usage(self.store,self.options)
        self.assertEqual(result['input_reports'],1);self.assertEqual(result['output_reports'],0)
        with self.store.connect() as db:
            db.execute('DROP TABLE usage_metadata')
            db.execute('CREATE TABLE usage_metadata(exchange_id TEXT PRIMARY KEY,reported INTEGER)')
            db.execute('INSERT INTO usage_metadata VALUES (?,1)',(self.b,))
            db.execute('UPDATE conversations SET input_tokens=12,output_tokens=0 WHERE id=?',(self.b,))
        reopened=Store(self.temp.name)
        result=usage(reopened,self.options)
        self.assertEqual(result['input_tokens'],12);self.assertEqual(result['input_reports'],1)
        self.assertEqual(result['output_reports'],0)

    def test_fixed_project_mcp_cannot_escape_its_collection(self):
        result=dispatch(self.store,{'id':1,'method':'tools/call','params':{'name':'recent_memory','arguments':{}}},project='Work')
        self.assertEqual({r['project'] for r in json.loads(result['result']['content'][0]['text'])},{'Work'})
        denied=dispatch(self.store,{'id':2,'method':'tools/call','params':{'name':'search_memory','arguments':{'query':'travel','project':'Personal'}}},project='Work')
        self.assertTrue(denied['result']['isError'])
        packet=dispatch(self.store,{'id':3,'method':'tools/call','params':{'name':'context_handoff','arguments':self.options}},project='Work')
        self.assertNotIn('private destination',packet['result']['content'][0]['text'])

    def test_mcp_pages_long_sources_and_restricts_original_reads(self):
        self.store.update(self.a,'x'*13000)
        request={'id':1,'method':'tools/call','params':{'name':'read_memory','arguments':{'exchange_id':self.a,'length':12000}}}
        result=json.loads(dispatch(self.store,request,project='Work')['result']['content'][0]['text'])
        self.assertEqual(len(result['text']),12000);self.assertEqual(result['next_start'],12000)
        request['params']['arguments']['start']=12000
        tail=json.loads(dispatch(self.store,request,project='Work')['result']['content'][0]['text'])
        self.assertEqual(len(tail['text']),1000);self.assertIsNone(tail['next_start'])
        request['params']['arguments']['exchange_id']=self.private
        self.assertTrue(dispatch(self.store,request,project='Work')['result']['isError'])
        recent=dispatch(self.store,{'id':2,'method':'tools/call','params':{'name':'recent_memory','arguments':{}}},project='Work')
        rows=json.loads(recent['result']['content'][0]['text'])
        clipped=next(row for row in rows if row['id']==self.a)
        self.assertTrue(clipped['excerpted']);self.assertEqual(len(clipped['response']),2400)

    def test_handoff_keeps_recent_context_bounded_with_coverage(self):
        for i in range(30):self.add('claude',f'Question {i}','A reply','Work',f'2026-10-30T10:{i:02}:00+00:00')
        result=report(self.store,{**self.options,'kind':'handoff'})
        self.assertEqual(result['total'],32);self.assertEqual(result['source_count'],20)
        self.assertEqual(len(result['sources']),20);self.assertIn('20 most recent moments out of 32',result['body'])

    @patch('wirebrain.intelligence.local_request')
    def test_semantic_mcp_handoff_uses_filters(self,request):
        request.return_value={'embeddings':[[1.,0.],[1.,0.],[1.,0.]]}
        settings(self.store,{'embedding_model':'fake','chat_model':''});index_batch(self.store)
        request.return_value={'embeddings':[[1.,0.]]}
        result=dispatch(self.store,{'id':1,'method':'tools/call','params':{'name':'search_memory','arguments':{'query':'concurrency','mode':'semantic','project':'Work'}}})
        self.assertEqual({r['id'] for r in json.loads(result['result']['content'][0]['text'])},{self.a,self.b})

    def test_private_keys_bearer_tokens_and_jwt_are_redacted(self):
        values=['-----BEGIN RSA PRIVATE KEY-----\nprivate-data\n-----END RSA PRIVATE KEY-----',
                'Authorization: Bearer abcdefghijklmnop', 'eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxIn0.longsignaturevalue']
        for value in values:
            cleaned=redact(value);self.assertIn('[REDACTED]',cleaned);self.assertNotIn(value,cleaned)
