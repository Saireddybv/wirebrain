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

    def test_conversation_tools_and_generated_connection(self):
        with self.opener.open(self.base+'/conversation-tools.js',timeout=5) as response:
            self.assertIn(b'function resetConversationTools',response.read())
        found=self.request('/api/workflows/list-conversations',{'provider':'claude','project':'Business'})
        self.assertEqual(found['total'],1)
        anchor=found['conversations'][0]['exchange_id']
        read=self.request('/api/workflows/read-conversation',{'exchange_id':anchor,'project':'Business'})
        self.assertEqual(read['moments'][0]['response'],'Consider referrals')
        handoff=self.request('/api/workflows/conversation-handoff',{'exchange_id':anchor,'project':'Business'})
        self.assertIn('Client acquisition',handoff['body'])
        self.assertIn('Consider referrals',handoff['body'])
        config=self.request('/api/workflows/mcp-config',{'project':'Business'})
        self.assertEqual(config['mcpServers']['wirebrain']['args'][-2:],['--project','Business'])
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/workflows/read-conversation',{'exchange_id':anchor,'project':'Other'})
        self.assertEqual(error.exception.code,400)
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request('/api/workflows/list-conversations',{},origin='https://untrusted.example')
        self.assertEqual(error.exception.code,403)

    def test_http_mcp_local_controls_issue_and_revoke_collection_token(self):
        import socket
        from wirebrain.mcp_http import stop
        from wirebrain.mcp_access import Access
        with socket.socket() as available:
            available.bind(('127.0.0.1',0)); port=available.getsockname()[1]
        self.addCleanup(lambda:stop(self.store))
        state=self.request('/api/workflows/mcp-http',{'action':'start','port':port})
        self.assertTrue(state['running']); self.assertEqual(state['public_url'],'')
        created=self.request('/api/workflows/mcp-http',{'action':'issue-token','name':'Test coder','project':'Business'})
        entry=created['connection']['mcpServers']['wirebrain']
        token=entry['headers']['Authorization'][7:]
        self.assertEqual(Access(self.store.home).authenticate(token,entry['url'])['project'],'Business')
        state=self.request('/api/workflows/mcp-http',{})
        self.assertNotIn(token,json.dumps(state))
        self.request('/api/workflows/mcp-http',{'action':'revoke','id':created['id']})
        self.assertIsNone(Access(self.store.home).authenticate(token,entry['url']))
        self.assertFalse(self.request('/api/workflows/mcp-http',{'action':'stop'})['running'])
        with self.assertRaises(urllib.error.HTTPError):self.request('/api/workflows/mcp-http',{'action':'issue-token'})

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

    def test_personal_memory_api_manual_save_edit_forget_and_missing_model(self):
        saved=self.request('/api/personal-memory/save',{'text':'I prefer simple interfaces','kind':'preference','scope':'Studio'})
        self.assertEqual(len(self.request('/api/personal-memory?scope=Studio')['memories']),1)
        self.assertEqual(self.request('/api/personal-memory?scope=Other')['memories'],[])
        self.request('/api/personal-memory/save',{'id':saved['id'],'text':'I prefer readable interfaces','scope':'Studio'})
        self.assertEqual(len(self.request('/api/personal-memory?scope=Studio')['memories'][0]['history']),1)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/personal-memory/process',{})
        self.assertEqual(error.exception.code,400)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/personal-memory/settings',{'enabled':True})
        self.assertEqual(error.exception.code,400)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/personal-memory/save',{'text':'Unwanted memory'},'https://other.example')
        self.assertEqual(error.exception.code,403)
        self.request('/api/personal-memory/action',{'id':saved['id'],'action':'forget'})
        self.assertEqual(self.request('/api/personal-memory?scope=Studio')['memories'],[])

    def test_consolidated_summary_views_use_exact_collection(self):
        self.request('/api/personal-memory/save',{'text':'Prefers readable interfaces','scope':'Studio'})
        self.assertEqual(self.request('/api/personal-memory/summary')['total'],0)
        summary=self.request('/api/personal-memory/summary?scope=Studio')
        self.assertEqual(summary['title'],'Wirebrain memory')
        self.assertEqual(summary['total'],1)
        self.assertEqual(self.request('/api/personal-memory/summary?provider=claude&scope=Studio')['total'],0)
        preview=self.request('/api/personal-memory/summary-refresh',{'scope':'Studio'})
        self.assertFalse(preview['building'])

    def test_reflect_analysis_and_study_routes_are_guarded(self):
        result=self.request('/api/reflect/analyze',{'project':'Business'})
        self.assertEqual(result['total'],1)
        self.assertIn('use_map',result)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/reflect/analyze',{},'https://other.example')
        self.assertEqual(error.exception.code,403)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/reflect/study',{'project':'Business'})
        self.assertEqual(error.exception.code,400)

    @patch('wirebrain.intelligence.local_request')
    def test_day_reflection_respects_collection_and_excludes_unscoped_notes(self,model):
        model.return_value={'message':{'content':'A scoped reflection [1].'}}
        self.request('/api/local/settings',{'chat_model':'writer'})
        private=self.store.add('claude','web','Private project detail','Private')
        self.store.update(private,'Private response')
        with self.store.connect() as db:db.execute('UPDATE conversations SET created=?',('2026-10-30T10:00:00+00:00',))
        self.request('/api/diary/note',{'day':'2026-10-30','body':'An unrelated private diary note'})
        result=self.request('/api/memory/reflect',{'day':'2026-10-30','offset':0,'project':'Business'})
        self.assertEqual([row['id'] for row in result['sources']],[self.ident])
        content=json.dumps(model.call_args.args[1]['messages'])
        self.assertNotIn('Private project detail',content)
        self.assertNotIn('unrelated private diary note',content)

    def test_workflow_endpoints_and_mcp_configuration(self):
        with self.store.connect() as db:db.execute('UPDATE conversations SET created=? WHERE id=?',('2026-10-30T10:00:00+00:00',self.ident))
        selection={'date_from':'2026-10-30','date_to':'2026-10-30','project':'Business'}
        result=self.request('/api/workflows/report',{**selection,'kind':'study'})
        self.assertIn('Client acquisition',result['body']);self.assertFalse(result['generated'])
        self.request('/api/workflows/save-snippet',{'exchange_id':self.ident,'title':'Referral idea','content':'Consider referrals','language':'note'})
        self.assertTrue(self.request('/api/workflows/snippets',selection)['snippets'][0]['saved'])
        self.assertEqual(self.request('/api/workflows/usage',selection)['reported'],0)
        config=self.request('/api/workflows/mcp-config',selection)
        self.assertEqual(config['mcpServers']['wirebrain']['args'][-2:],['--project','Business'])
        with self.opener.open(self.base+'/workflows.js') as response:self.assertEqual(response.status,200)
        with self.assertRaises(urllib.error.HTTPError) as error:self.request('/api/workflows/report',{'date_from':'invalid','date_to':'2026-10-30'})
        self.assertEqual(error.exception.code,400)
