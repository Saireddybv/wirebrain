import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from wirebrain.gateway import handler_factory
from wirebrain.store import Store


class MemoryApiTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.store=Store(self.tmp.name)
        self.ident=self.store.add('claude','web','Client acquisition','Business')
        self.store.update(self.ident,'Consider referrals')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),handler_factory(self.store,{'dashboard_port':3333,'redact_on_wire':False},True))
        self.addCleanup(self.server.server_close);self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def request(self,path,data=None,origin=None):
        headers={'Content-Type':'application/json'}
        if origin:headers['Origin']=origin
        req=urllib.request.Request(self.base+path,None if data is None else json.dumps(data).encode(),headers)
        with self.opener.open(req,timeout=5) as response:return json.load(response)

    @patch('wirebrain.intelligence.local_request')
    def test_settings_index_search_answer_and_local_day_reflection(self,model):
        def local(path,payload=None):
            if path=='embed':return {'embeddings':[[1.,0.] for _ in payload['input']]}
            if path=='chat':return {'message':{'content':'You explored referrals [1].'}}
            return {'models':[{'name':'embed'},{'name':'writer'}]}
        model.side_effect=local
        self.request('/api/local/settings',{'embedding_model':'embed','chat_model':'writer'})
        self.assertEqual(self.request('/api/local/index',{})['remaining'],0)
        self.assertEqual(self.request('/api/memory/search?q=customers&mode=semantic&provider=claude')['rows'][0]['id'],self.ident)
        answer=self.request('/api/ask',{'query':'customers','mode':'semantic','generate':True})
        self.assertTrue(answer['generated']);self.assertEqual(answer['sources'][0]['id'],self.ident)
        with self.store.connect() as db:db.execute('UPDATE conversations SET created=? WHERE id=?',('2026-10-29T22:00:00+00:00',self.ident))
        reflection=self.request('/api/memory/reflect',{'day':'2026-10-30','offset':330})
        self.assertEqual(len(reflection['sources']),1)
        self.request('/api/memory/collection',{'id':self.ident,'name':'Studio'})
        self.assertEqual(self.request('/api/memory/overview')['projects'][0]['name'],'Studio')

    def test_unconfigured_ai_and_cross_origin_fail_without_breaking_diary(self):
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/memory/search?q=x&mode=semantic')
        self.assertEqual(error.exception.code,400)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/local/settings',{},'https://other.example')
        self.assertEqual(error.exception.code,403)
        self.assertEqual(self.request('/api/memory/overview')['moments'],1)
