"""Authenticated, loopback-bound Streamable HTTP MCP and OAuth endpoints."""
import html
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlencode, urlsplit, urlunsplit

from .mcp import dispatch
from .mcp_access import Access, SCOPE

VERSION='2025-06-18'
SERVERS={}
LOCK=threading.RLock()


def configuration(port=3334, public_url=''):
    if type(port) is not int or not 1024<=port<=65535:
        raise ValueError('Choose a port from 1024 to 65535')
    if not isinstance(public_url,str) or len(public_url)>2000:
        raise ValueError('Invalid public HTTPS address')
    if public_url:
        url=urlsplit(public_url)
        if url.scheme!='https' or not url.hostname or url.username or url.password or url.path not in ('','/') or url.query or url.fragment:
            raise ValueError('Use an HTTPS origin, for example https://memory.example.com, without a path')
        public_url=urlunsplit(('https',url.netloc,'','',''))
    return {'enabled':True,'port':port,'public_url':public_url}


def handler_factory(store, config):
    access=Access(store.home)
    base=config['public_url'] or f"http://127.0.0.1:{config['port']}"
    resource=base+'/mcp'
    hosts={f"127.0.0.1:{config['port']}",f"localhost:{config['port']}",urlsplit(base).netloc}
    origins={base,f"http://127.0.0.1:{config['port']}",f"http://localhost:{config['port']}"}

    class Handler(BaseHTTPRequestHandler):
        def setup(self):
            super().setup(); self.connection.settimeout(10)

        def log_message(self,*args): pass

        def reply(self, value=None, code=200, headers=None, mime='application/json'):
            body=b'' if value is None else (json.dumps(value,ensure_ascii=False).encode() if mime=='application/json' else value.encode())
            self.send_response(code)
            self.send_header('Content-Type',mime+'; charset=utf-8')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.send_header('Referrer-Policy','no-referrer')
            self.send_header('X-Content-Type-Options','nosniff')
            self.send_header('Content-Security-Policy',"default-src 'none'; frame-ancestors 'none'; base-uri 'none'")
            self.send_header('Connection','close')
            for key,value in (headers or {}).items(): self.send_header(key,value)
            self.end_headers(); self.close_connection=True
            try: self.wfile.write(body)
            except (BrokenPipeError,ConnectionResetError): pass

        def guard(self):
            if self.headers.get('Host','') not in hosts or (self.headers.get('Origin') is not None and self.headers.get('Origin') not in origins):
                self.reply({'error':'Untrusted host or origin'},403); return False
            return True

        def auth(self):
            header=self.headers.get('Authorization','')
            grant=access.authenticate(header[7:] if header.startswith('Bearer ') else '',resource)
            if not grant:
                self.reply({'error':'Authentication required'},401,{'WWW-Authenticate':f'Bearer resource_metadata="{base}/.well-known/oauth-protected-resource/mcp", scope="{SCOPE}"'})
            return grant

        def do_GET(self):
            if not self.guard(): return
            parsed=urlsplit(self.path); path=parsed.path
            if path in ('/.well-known/oauth-protected-resource','/.well-known/oauth-protected-resource/mcp'):
                return self.reply({'resource':resource,'authorization_servers':[base],'scopes_supported':[SCOPE],'bearer_methods_supported':['header'],'resource_name':'Wirebrain memory'})
            if path=='/.well-known/oauth-authorization-server':
                return self.reply({'issuer':base,'authorization_endpoint':base+'/oauth/authorize','token_endpoint':base+'/oauth/token',
                    'registration_endpoint':base+'/oauth/register','response_types_supported':['code'],'grant_types_supported':['authorization_code','refresh_token'],
                    'token_endpoint_auth_methods_supported':['none'],'code_challenge_methods_supported':['S256'],'scopes_supported':[SCOPE]})
            if path=='/oauth/authorize':
                try:
                    params=self.parameters(parsed.query)
                    ident=params.get('request')
                    if not ident: ident=access.request(params,resource)
                    request=access.poll(ident)
                    if request['status']!='pending':
                        uri=urlsplit(request['redirect'])
                        fields={'state':request['state']}
                        if request['status']=='denied': fields['error']='access_denied'
                        else: fields['code']=request['code']
                        query=uri.query+('&' if uri.query else '')+urlencode(fields)
                        return self.reply(None,302,{'Location':urlunsplit((uri.scheme,uri.netloc,uri.path,query,''))})
                    destination=html.escape(request['redirect'])
                    page=f'<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width"><meta http-equiv="refresh" content="3;url=/oauth/authorize?request={ident}"><title>Connect Wirebrain</title></head><body><h1>Approve this connection in Wirebrain</h1><p>On the computer running Wirebrain, open Tools → Remote MCP → Refresh connections.</p><p>Match this code: <strong>{request["pairing"]}</strong></p><p>Requested by {html.escape(request["name"])} (client-supplied name). Redirect: {destination}</p><p>Choose a collection and approve there. This page continues automatically. The request expires after five minutes.</p></body></html>'
                    return self.reply(page,mime='text/html')
                except (ValueError,TypeError): return self.reply({'error':'invalid_request','error_description':'Invalid or expired authorization request'},400)
            if path=='/mcp':
                if not self.auth(): return
                return self.reply(None,405,{'Allow':'POST'})
            return self.reply({'error':'Not found'},404)

        @staticmethod
        def parameters(text):
            values=parse_qs(text,keep_blank_values=True,max_num_fields=30)
            if any(len(v)!=1 for v in values.values()): raise ValueError('Duplicate parameters')
            return {k:v[0] for k,v in values.items()}

        def do_POST(self):
            if not self.guard(): return
            path=urlsplit(self.path).path
            if self.path!=path: return self.reply({'error':'Query parameters are not accepted'},400)
            if path not in ('/mcp','/oauth/register','/oauth/token'): return self.reply({'error':'Not found'},404)
            grant=None
            if path=='/mcp':
                grant=self.auth()
                if not grant: return
            try:
                if self.headers.get('Transfer-Encoding'): raise ValueError('Chunked requests are unsupported')
                length=int(self.headers.get('Content-Length','0'))
                if not 0<length<=1024*1024: return self.reply({'error':'Body must be 1 byte to 1 MB'},413)
                raw=self.rfile.read(length).decode('utf-8')
                if path=='/oauth/token':
                    if self.headers.get_content_type()!='application/x-www-form-urlencoded': return self.reply({'error':'Use form encoding'},415)
                    data=self.parameters(raw)
                else:
                    if self.headers.get_content_type()!='application/json': return self.reply({'error':'Use application/json'},415)
                    data=json.loads(raw)
                if not isinstance(data,dict): raise ValueError('Expected an object')
            except (ValueError,TypeError,UnicodeError,OSError): return self.reply({'error':'Invalid request body'},400)
            if path=='/oauth/register':
                try: return self.reply(access.register(data),201)
                except (ValueError,TypeError): return self.reply({'error':'invalid_client_metadata'},400)
            if path=='/oauth/token':
                try: return self.reply(access.exchange(data,resource))
                except (ValueError,TypeError): return self.reply({'error':'invalid_grant'},400)
            accept=self.headers.get('Accept','')
            if 'application/json' not in accept or 'text/event-stream' not in accept:
                return self.reply({'error':'Accept must include application/json and text/event-stream'},406)
            if self.headers.get('MCP-Protocol-Version',VERSION)!=VERSION:
                return self.reply({'error':'Unsupported MCP protocol version'},400)
            if data.get('jsonrpc')!='2.0' or not isinstance(data.get('method'),str) or not isinstance(data.get('params',{}),dict) or ('id' in data and (type(data['id']) not in (str,int))):
                return self.reply({'jsonrpc':'2.0','id':None,'error':{'code':-32600,'message':'Invalid request'}},400)
            try: result=dispatch(store,data,grant['project'])
            except (ValueError,TypeError,AttributeError):
                return self.reply({'jsonrpc':'2.0','id':data.get('id'),'error':{'code':-32602,'message':'Invalid params'}},400)
            if result is None: return self.reply(None,202)
            return self.reply(result)

        def do_DELETE(self):
            if self.guard() and self.auth(): self.reply(None,405,{'Allow':'POST'})

    return Handler


class Server(ThreadingHTTPServer):
    daemon_threads=True
    def __init__(self, address, handler):
        self.slots=threading.BoundedSemaphore(24)
        super().__init__(address,handler)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request); return
        try: super().process_request(request,address)
        except BaseException: self.slots.release(); raise

    def process_request_thread(self, request, address):
        try: super().process_request_thread(request,address)
        finally: self.slots.release()


def stop(store, persist=True):
    with LOCK:
        key=str(store.home.resolve()); server=SERVERS.pop(key,None)
        if server: server.shutdown(); server.server_close()
        if persist:
            access=Access(store.home); config=access.config(); config['enabled']=False; access.config(config)


def start(store, port=3334, public_url=''):
    config=configuration(port,public_url)
    with LOCK:
        key=str(store.home.resolve()); current=SERVERS.get(key)
        if current and current.config==config: return
        # Bind before stopping the old listener when changing ports.
        if current and current.config['port']==port: stop(store,False)
        server=Server(('127.0.0.1',port),handler_factory(store,config))
        if current and key in SERVERS: stop(store,False)
        server.config=config; SERVERS[key]=server
        Access(store.home).config(config)
        threading.Thread(target=server.serve_forever,daemon=True).start()


def control(store, payload):
    access=Access(store.home); action=payload.get('action','status')
    if action=='start': start(store,payload.get('port',3334),payload.get('public_url',''))
    elif action=='stop': stop(store)
    elif action in ('approve','reject'): access.approve(payload.get('id'),payload.get('project',''),action=='approve')
    elif action=='revoke':
        if not isinstance(payload.get('id'),str): raise ValueError('Choose a connection')
        access.revoke(payload['id'])
    elif action=='issue-token':
        config=access.config()
        if str(store.home.resolve()) not in SERVERS: raise ValueError('Start the MCP server first')
        resource=(config['public_url'] or f"http://127.0.0.1:{config['port']}")+'/mcp'
        token=access.issue_local(payload.get('name','Coding assistant'),payload.get('project',''),resource)
        return {'connection':{'mcpServers':{'wirebrain':{'url':resource,'headers':{'Authorization':'Bearer '+token['token']}}}},'id':token['id'],'expires_in':token['expires_in']}
    elif action!='status': raise ValueError('Unknown connection action')
    config=access.config(); running=str(store.home.resolve()) in SERVERS
    return {**config,'running':running,'endpoint':(config['public_url'] or f"http://127.0.0.1:{config['port']}")+'/mcp',**access.status()}
