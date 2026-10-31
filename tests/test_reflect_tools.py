import json
import tempfile
import unittest
from unittest.mock import patch

from wirebrain.store import Store
from wirebrain.reflect_tools import analyze,study_guide,category,discover_macros,macros
from wirebrain.workflows import remove_snippet
from wirebrain.personal_memory import save
from wirebrain.diary import export_diary
from wirebrain.importer import import_history


class ReflectToolsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)

    def source(self,prompt,reply='A captured explanation.',project='Study',provider='claude'):
        ident=self.store.add(provider,'web',prompt,project);self.store.update(ident,reply)
        with self.store.connect() as db:db.execute('UPDATE conversations SET created=? WHERE id=?',('2026-10-30T10:00:00+00:00',ident))
        return ident

    def test_recurring_explanations_generate_source_linked_practice_not_diagnosis(self):
        self.source('Explain the event loop in JavaScript')
        self.source('Help me understand the event loop in JavaScript')
        self.source('hi Gemini again')
        self.source('Wirebrain capture test: reply hello')
        result=analyze(self.store,{'project':'Study'})
        self.assertEqual(result['total'],4)
        self.assertEqual(result['analyzed'],2)
        self.assertTrue(result['topics'])
        self.assertTrue(any('event' in topic['topic'] for topic in result['topics']))
        self.assertEqual(sum(bucket['count'] for bucket in result['use_map']),2)
        topic=result['topics'][0]['topic']
        guide=study_guide(self.store,{'project':'Study','topic':topic})
        self.assertIn('not proof of a knowledge gap',guide['body'])
        self.assertIn('Explain the idea in your own words',guide['body'])
        self.assertEqual(len(guide['sources']),2)
        self.assertFalse(guide['generated'])

    def test_request_categories_are_observable_not_independence_scores(self):
        self.assertEqual(category('Convert these rows to JSON'),'routine')
        self.assertEqual(category('Help me reply to my friend after an argument'),'communication')
        self.assertEqual(category('Should I choose option A or option B?'),'decisions')
        self.assertEqual(category('Explain this exception'),'learning')
        self.assertEqual(category('Write a sorting function'),'creation')
        self.source('Choose for me which task to do next')
        result=analyze(self.store,{})
        self.assertIn('not time spent, proficiency, dependency',result['note'])
        self.assertNotIn('dependency_score',result)

    def test_macro_discovery_is_automatic_exact_text_searchable_and_idempotent(self):
        email='Subject: Project update\n\nHi [Name],\nHere is the update for [Company].\n\nBest regards,\n[Name]'
        workflow='1. Gather the source files and check their dates.\n2. Review the required fields and document exceptions.\n3. Export the final checklist for review.'
        prompt='Role: You are an editor who keeps wording clear and concise.\nTask: Rewrite {{text}} for {{audience}}.\nConstraints: Preserve factual claims.\nOutput format: Plain text.'
        self.source('Draft a reusable email template for a project update',email)
        self.source('Create a step-by-step workflow for preparing the report',workflow)
        self.source(prompt,'A sample edited result.')
        first=analyze(self.store,{'project':'Study'})
        self.assertEqual({item['kind'] for item in first['macros']},{'email','workflow','prompt'})
        self.assertIn(email,[item['content'] for item in first['macros']])
        self.assertEqual(len(analyze(self.store,{'project':'Study'})['macros']),3)
        self.assertEqual(len(analyze(self.store,{'project':'Study','query':'Project update'})['macros']),1)

    def test_removed_macros_stay_removed_across_scans_restarts_and_backup(self):
        self.source('Draft an email template','Subject: Test update\nHi [Name],\nThis is an update for [Company].\nRegards,\n[Name]')
        result=analyze(self.store,{})
        self.assertEqual(len(result['macros']),1)
        remove_snippet(self.store,{'id':result['macros'][0]['id']})
        self.assertEqual(analyze(Store(self.tmp.name),{})['macros'],[])
        backup=export_diary(self.store)
        self.assertEqual(len(backup['macro_blocks']),1)
        with tempfile.TemporaryDirectory() as home:
            restored=Store(home);import_history(restored,backup)
            self.assertEqual(analyze(restored,{})['macros'],[])

    def test_source_changes_and_deletion_remove_automatic_templates(self):
        ident=self.source('Draft an email template','Subject: Test update\nHi [Name],\nThis is an update for [Company].\nRegards,\n[Name]')
        analyze(self.store,{})
        with self.store.connect() as db:db.execute('UPDATE conversations SET response=? WHERE id=?',('Corrected ordinary response',ident))
        self.assertEqual(macros(self.store,self.store.list(limit=20)),[])
        self.store.update(ident,'Subject: New update\nHi [Name],\nAnother update for [Company].\nRegards,\n[Name]')
        self.assertEqual(len(analyze(self.store,{})['macros']),1)
        self.store.delete(ident)
        self.assertEqual(analyze(self.store,{})['macros'],[])

    def test_filters_keep_topics_templates_and_suggestions_in_their_scope(self):
        ident=self.source('Explain the event loop',project='Private')
        self.source('Explain the event loop',project='Private')
        self.source('Draft an email template','Subject: Private update\nHi [Name],\nAn update for [Company].\nRegards,\n[Name]',project='Private')
        memory=save(self.store,{'text':'A possible preference','scope':'Private'})['id']
        with self.store.connect() as db:
            db.execute("UPDATE personal_memory SET status='suggested' WHERE id=?",(memory,))
            db.execute('INSERT INTO personal_memory_sources VALUES (?,?,?)',(memory,ident,'Explain the event loop'))
        visible=analyze(self.store,{'project':'Public'})
        self.assertEqual(visible['topics'],[]);self.assertEqual(visible['macros'],[]);self.assertEqual(visible['suggestions'],[])
        visible=analyze(self.store,{'project':'Private'})
        self.assertTrue(visible['topics']);self.assertEqual(len(visible['macros']),1);self.assertEqual(len(visible['suggestions']),1)
        self.assertEqual(analyze(self.store,{'provider':'chatgpt'})['suggestions'],[])

    def test_secrets_demo_data_and_partial_answers_do_not_become_macros(self):
        ident=self.source('Draft an email template','Subject: Private update\nHi [Name],\npassword=abcdef123456\nRegards,\n[Name]')
        partial=self.source('Make a step-by-step workflow','1. Gather the files.\n2. Review the schema.\n3. Export the checklist.')
        with self.store.connect() as db:db.execute("UPDATE conversations SET status='streaming' WHERE id=?",(partial,))
        self.assertEqual(analyze(self.store,{})['macros'],[])

    def test_invalid_backup_markers_are_atomic(self):
        self.source('A harmless source')
        backup=export_diary(self.store);backup['macro_blocks']=['invalid']
        with tempfile.TemporaryDirectory() as home:
            restored=Store(home)
            with self.assertRaises(ValueError):import_history(restored,backup)
            self.assertEqual(restored.list(),[])

    @patch('wirebrain.intelligence.generate')
    def test_optional_ai_study_guide_uses_only_selected_sources(self,generate):
        self.source('Explain closures in JavaScript',project='Study')
        self.source('Explain closures again in JavaScript',project='Study')
        self.source('Private financial note',project='Private')
        generate.return_value='A small practice exercise [1].'
        result=study_guide(self.store,{'project':'Study','generate':True})
        self.assertTrue(result['generated'])
        rows=generate.call_args.args[2]
        self.assertEqual({row['project'] for row in rows},{'Study'})


if __name__=='__main__':unittest.main()
