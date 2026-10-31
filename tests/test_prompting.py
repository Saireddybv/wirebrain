import json
from importlib.resources import files
import unittest

from wirebrain.prompting import render_prompt, prompt_info, load_schema


class PromptCatalogTests(unittest.TestCase):
    def catalog(self):
        return json.loads(files('wirebrain').joinpath('prompts','catalog.json').read_text(encoding='utf-8'))['prompts']

    def test_every_registered_prompt_and_schema_can_be_loaded(self):
        for name,info in self.catalog().items():
            with self.subTest(prompt=name):
                self.assertIsInstance(info['version'],int)
                self.assertGreater(info['version'],0)
                self.assertIn(info['role'],('system','user','instruction','tool','context'))
                self.assertEqual(len(info['variables']),len(set(info['variables'])))
                rendered=render_prompt(name,**{key:'Synthetic value' for key in info['variables']})
                self.assertTrue(rendered.strip())
                if 'schema' in info:
                    schema=load_schema(name)
                    self.assertEqual(schema['type'],'object')
                    self.assertFalse(schema['additionalProperties'])

    def test_inserted_chat_text_is_not_evaluated_or_retemplated(self):
        text='Literal $HOME, ${schema}, {{braces}}, and `$(example)`.'
        rendered=render_prompt('gateway.text_only',messages=text)
        self.assertIn(text,rendered)
        context=render_prompt('recall.context',instruction=text,excerpts=text,memories=text,note=text)
        self.assertEqual(context.count(text),4)

    def test_missing_extra_and_non_string_variables_fail_clearly(self):
        with self.assertRaises(ValueError):render_prompt('reflect.study')
        with self.assertRaises(ValueError):render_prompt('reflect.study',topics='SQLite',extra='unexpected')
        with self.assertRaises(ValueError):render_prompt('reflect.study',topics=['SQLite'])

    def test_arbitrary_names_and_paths_are_not_loaded(self):
        for name in ('../../auth.json','/etc/passwd','memory.missing',None):
            with self.subTest(name=name):
                with self.assertRaises(ValueError):render_prompt(name)

    def test_metadata_cannot_mutate_registry_and_schema_kinds_match_validation(self):
        info=prompt_info('reflect.study');info['variables'].append('unexpected')
        self.assertEqual(prompt_info('reflect.study')['variables'],['topics'])
        from wirebrain.personal_memory import KINDS
        schema=load_schema('memory.extract')
        self.assertEqual(set(schema['properties']['memories']['items']['properties']['kind']['enum']),set(KINDS))

    def test_only_prompts_with_output_schemas_allow_schema_loading(self):
        with self.assertRaises(ValueError):load_schema('reflect.daily')


if __name__=='__main__':unittest.main()
