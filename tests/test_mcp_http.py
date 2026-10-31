import base64
import hashlib
import json
import secrets
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs

from wirebrain.store import Store
from wirebrain.mcp_access import Access
from wirebrain.mcp_http import Server, handler_factory, configuration


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args): return None


class HttpMcpTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.store=Store(temp.name); self.access=Access(self.store.home)
        self.work=self.store.add('claude','test','Architecture discussion','Work'); self.store.update(self.work,'Use SQLite')
        self.private=self.store.add('chatgpt','test','Private prompt','Personal'); self.store.update(self.private,'Private response')
        self.server=Server(('127.0.0.1',0),handler_factory(self.store,{'port':3334,'public_url':'https://memory.example.com'}))
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        threading.Thread(target=self.server.serve_forever,daemon=True).start()
        self.base='http://127.0.0.1:'+str(self.server.server_port)
        self.resource='https://memory.example.com/mcp'
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}),NoRedirect())
        self.token=self.access.issue_local('Test client','Work',self.resource)['token']

    def request(self,path,data=None,method=None,token=None,headers=None,form=False):
        fields={'Host':'memory.example.com','Accept':'application/json, text/event-stream'}
        if token: fields['Authorization']='Bearer '+token
        body=None
        if data is not None:
            fields['Content-Type']='application/x-www-form-urlencoded' if form else 'application/json'
            body=(urlencode(data) if form else json.dumps(data)).encode()
        fields.update(headers or {})
        req=urllib.request.Request(self.base+path,body,fields,method=method)
        try: response=self.opener.open(req,timeout=5)
        except urllib.error.HTTPError as error: response=error
        raw=response.read(); code=response.status; response_headers=response.headers
        response.close()
        return code,response_headers,raw

    def rpc(self,method,arguments=None,token=None):
        packet={'jsonrpc':'2.0','id':1,'method':method}
        if arguments is not None: packet['params']=arguments
        code,headers,raw=self.request('/mcp',packet,token=token or self.token)
        return code,json.loads(raw)

    def oauth_request(self):
        code,_,raw=self.request('/oauth/register',{'client_name':'Test OAuth client','redirect_uris':['https://client.example/callback']})
        self.assertEqual(code,201); client=json.loads(raw)['client_id']
        verifier=secrets.token_urlsafe(48)
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        query={'client_id':client,'redirect_uri':'https://client.example/callback','response_type':'code','code_challenge_method':'S256','code_challenge':challenge,'resource':self.resource,'scope':'memory:read','state':'original state'}
        code,_,page=self.request('/oauth/authorize?'+urlencode(query))
        self.assertEqual(code,200); self.assertIn(b'Approve this connection',page)
        pending=self.access.status()['pending'][0]
        return client,verifier,pending

    def test_auth_metadata_host_origin_and_transport_rules(self):
        code,headers,_=self.request('/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/list'})
        self.assertEqual(code,401); self.assertIn('resource_metadata',headers['WWW-Authenticate'])
        code,_,raw=self.request('/.well-known/oauth-protected-resource/mcp')
        self.assertEqual(json.loads(raw)['resource'],self.resource)
        self.assertEqual(self.request('/mcp',token=self.token)[0],405)
        for headers in ({'Host':'attacker.example'},{'Origin':'https://attacker.example'},{'Origin':'null'}):
            self.assertEqual(self.request('/mcp',{'jsonrpc':'2.0','id':1,'method':'tools/list'},token=self.token,headers=headers)[0],403)
        self.assertEqual(self.request('/api/workflows/mcp-http',{},token=self.token)[0],404)
        self.assertEqual(self.request('/mcp',{},token=self.token,headers={'Accept':'application/json'})[0],406)
        self.assertEqual(self.request('/mcp',{},token=self.token,headers={'MCP-Protocol-Version':'bogus'})[0],400)
        self.assertEqual(self.request('/mcp',[{}],token=self.token)[0],400)
        code,_,body=self.request('/mcp',{'jsonrpc':'2.0','method':'notifications/initialized'},token=self.token)
        self.assertEqual((code,body),(202,b''))

    def test_rpc_scope_is_enforced_for_discovery_reads_and_handoff(self):
        code,init=self.rpc('initialize',{'protocolVersion':'2025-06-18'})
        self.assertEqual(code,200); self.assertEqual(init['result']['protocolVersion'],'2025-06-18')
        self.assertEqual(len(self.rpc('tools/list')[1]['result']['tools']),8)
        found=self.rpc('tools/call',{'name':'list_conversations','arguments':{}})[1]
        self.assertIn('Architecture discussion',json.dumps(found)); self.assertNotIn('Private prompt',json.dumps(found))
        for tool,args in [('read_memory',{'exchange_id':self.private}),('read_conversation',{'exchange_id':self.private}),('conversation_handoff',{'exchange_id':self.private}),('recent_memory',{'project':'Personal'})]:
            result=self.rpc('tools/call',{'name':tool,'arguments':args})[1]['result']
            self.assertTrue(result['isError']); self.assertNotIn('Private response',json.dumps(result))
        self.access.revoke(self.access.authenticate(self.token,self.resource)['id'])
        self.assertEqual(self.request('/mcp',{},token=self.token)[0],401)

    def test_complete_oauth_flow_pkce_rotation_audience_and_revocation(self):
        client,verifier,pending=self.oauth_request()
        self.access.approve(pending['id'],'Work')
        code,headers,_=self.request('/oauth/authorize?'+urlencode({'request':pending['id']}))
        self.assertEqual(code,302)
        callback=parse_qs(urlsplit(headers['Location']).query)
        self.assertEqual(callback['state'],['original state'])
        form={'grant_type':'authorization_code','client_id':client,'code':callback['code'][0],'code_verifier':verifier,'redirect_uri':'https://client.example/callback','resource':self.resource}
        self.assertEqual(self.request('/oauth/token',{**form,'code_verifier':'x'*43},form=True)[0],400)
        self.assertEqual(self.request('/oauth/token',{**form,'resource':'https://wrong.example/mcp'},form=True)[0],400)
        status,_,raw=self.request('/oauth/token',form,form=True)
        self.assertEqual(status,200); tokens=json.loads(raw)
        self.assertEqual(self.request('/oauth/token',form,form=True)[0],400)
        grant=self.access.authenticate(tokens['access_token'],self.resource)
        self.assertEqual(grant['project'],'Work')
        with self.access.db() as db:
            persisted=' '.join(str(tuple(row)) for row in db.execute('SELECT * FROM tokens'))
        self.assertNotIn(tokens['access_token'],persisted)
        self.assertNotIn(tokens['refresh_token'],persisted)
        self.assertIsNone(self.access.authenticate(tokens['access_token'],'https://wrong.example/mcp'))
        refresh={'grant_type':'refresh_token','client_id':client,'refresh_token':tokens['refresh_token'],'resource':self.resource}
        self.assertEqual(self.request('/oauth/token',{**refresh,'client_id':'wrong'},form=True)[0],400)
        status,_,raw=self.request('/oauth/token',refresh,form=True)
        self.assertEqual(status,200); renewed=json.loads(raw)
        self.assertNotEqual(renewed['refresh_token'],tokens['refresh_token'])
        self.assertEqual(self.request('/oauth/token',refresh,form=True)[0],400)
        self.access.revoke(grant['id'])
        self.assertIsNone(self.access.authenticate(renewed['access_token'],self.resource))
        with self.access.db() as db:
            saved=' '.join(str(tuple(row)) for row in db.execute('SELECT * FROM tokens'))
        self.assertNotIn(tokens['access_token'],saved)

    def test_oauth_cannot_skip_approval_redirect_validation_or_expiry(self):
        self.assertEqual(self.request('/oauth/register',{'redirect_uris':['http://remote.example/callback']})[0],400)
        client,verifier,pending=self.oauth_request()
        self.assertEqual(self.request('/oauth/authorize?request='+pending['id'])[0],200)
        self.access.approve(pending['id'],'',False)
        code,headers,_=self.request('/oauth/authorize?request='+pending['id'])
        self.assertEqual(code,302); self.assertIn('error=access_denied',headers['Location'])
        client,verifier,pending=self.oauth_request()
        with self.access.db() as db: db.execute('UPDATE requests SET expires=0 WHERE id=?',(pending['id'],))
        self.assertEqual(self.request('/oauth/authorize?request='+pending['id'])[0],400)
        with self.assertRaises(ValueError): self.access.approve(pending['id'],'Work')
        for config in ('http://remote.example','https://user:secret@example.com','https://example.com/mcp','https://example.com?token=x'):
            with self.assertRaises(ValueError): configuration(3334,config)

    def test_expired_credentials_and_invalid_redirects_are_rejected(self):
        from wirebrain.mcp_access import digest
        with self.access.db() as db: db.execute('UPDATE tokens SET expires=0 WHERE hash=?',(digest(self.token),))
        self.assertEqual(self.request('/mcp',{},token=self.token)[0],401)
        for uri in ('https://user:pass@client.example/callback','javascript:alert(1)','https://client.example/callback#fragment'):
            self.assertEqual(self.request('/oauth/register',{'redirect_uris':[uri]})[0],400)
        self.assertEqual(self.request('/oauth/authorize?client_id=x&redirect_uri=https://evil.example&response_type=code')[0],400)


if __name__=='__main__': unittest.main()
