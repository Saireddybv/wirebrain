import json
import tempfile
import unittest
from wirebrain.store import Store
from wirebrain.dataset_export import jsonl

class DatasetExportTests(unittest.TestCase):
    def test_thread_order_branches_filters_and_exclusions(self):
        with tempfile.TemporaryDirectory() as home:
            s=Store(home)
            def turn(prompt,reply,thread='',message='',parent='',response='',provider='chatgpt',project='Work',status='complete',demo=False):
                ident=s.add(provider,'test',prompt,project,demo=demo)
                s.update(ident,reply,status)
                if thread:s.link_exchange(ident,provider,thread,message,parent,response)
                return ident
            turn('First\n你好','One','thread','u1','root','a1')
            turn('Second','Two','thread','u2','a1','a2')
            turn('Alternative','Other','thread','u3','a1','a3')
            turn('Separate','Reply',provider='claude',project='Personal')
            turn('Partial','Not done',status='partial')
            turn('Demo','Sample',demo=True)
            turn('Empty','')
            lines=list(jsonl(s))
            rows=[json.loads(line) for line in lines]
            self.assertEqual(len(rows),3)
            self.assertTrue(all(line.endswith(b'\n') and line.count(b'\n')==1 for line in lines))
            paths=[r['messages'] for r in rows if r['messages'][0]['content']=='First\n你好']
            self.assertEqual(len(paths),2)
            self.assertEqual({p[-1]['content'] for p in paths},{'Two','Other'})
            self.assertTrue(all([m['role'] for m in p]==['user','assistant','user','assistant'] for p in paths))
            self.assertEqual(len(list(jsonl(s,provider='claude',project='Personal'))),1)
            self.assertEqual(list(jsonl(s,provider='claude',project='Work')),[])
            self.assertTrue(all(set(r)=={'messages'} for r in rows))
    def test_unknown_parent_is_separate_fragment_and_unlinked_chats_stay_separate(self):
        with tempfile.TemporaryDirectory() as home:
            s=Store(home)
            for i in range(3):
                ident=s.add('gemini','test',str(i),'')
                s.update(ident,'reply')
                if i<2:s.link_exchange(ident,'gemini','thread',str(i),'unknown-'+str(i),'r'+str(i))
            self.assertEqual(len(list(jsonl(s))),3)
    def test_no_parent_ids_use_recorded_order_without_ui_limit(self):
        with tempfile.TemporaryDirectory() as home:
            s=Store(home)
            for i in range(105):
                ident=s.add('meta','test',str(i),'')
                s.update(ident,'reply')
                s.link_exchange(ident,'meta','thread')
            row=json.loads(next(jsonl(s)))
            self.assertEqual(len(row['messages']),210)
            self.assertEqual(row['messages'][0]['content'],'0')
            self.assertEqual(row['messages'][-2]['content'],'104')
