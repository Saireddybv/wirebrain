"""Single-owner OAuth grants. Credentials are hashed; approval stays local."""
import base64
import hashlib
import json
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

SCOPE = 'memory:read'


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


def redirect_uri(value):
    if not isinstance(value,str) or len(value)>2000:
        raise ValueError('Invalid redirect URI')
    url=urlsplit(value)
    if url.username or url.password or url.fragment or not url.hostname:
        raise ValueError('Invalid redirect URI')
    if url.scheme!='https' and not (url.scheme=='http' and url.hostname in ('127.0.0.1','localhost','::1')):
        raise ValueError('Redirects require HTTPS or loopback HTTP')
    return value


class Access:
    def __init__(self, home):
        self.path=home/'mcp-access.sqlite3'
        with self.db() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT);
                CREATE TABLE IF NOT EXISTS clients (id TEXT PRIMARY KEY, name TEXT, redirects TEXT, expires REAL);
                CREATE TABLE IF NOT EXISTS requests (id TEXT PRIMARY KEY, client TEXT, redirect TEXT, state TEXT,
                    challenge TEXT, resource TEXT, expires REAL, status TEXT, project TEXT, pairing TEXT);
                CREATE TABLE IF NOT EXISTS codes (hash TEXT PRIMARY KEY, client TEXT, redirect TEXT, challenge TEXT,
                    resource TEXT, expires REAL, grant_id TEXT);
                CREATE TABLE IF NOT EXISTS grants (id TEXT PRIMARY KEY, client TEXT, name TEXT, project TEXT,
                    resource TEXT, created REAL, expires REAL, revoked INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS tokens (hash TEXT PRIMARY KEY, grant_id TEXT, kind TEXT, expires REAL);
            ''')
        if __import__('os').name!='nt': self.path.chmod(0o600)

    @contextmanager
    def db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.row_factory=sqlite3.Row
        try:
            with db: yield db
        finally: db.close()

    def config(self, value=None):
        with self.db() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO config VALUES (?,?)',('http',json.dumps(value)))
            row=db.execute('SELECT value FROM config WHERE key=?',('http',)).fetchone()
        return json.loads(row[0]) if row else {'enabled':False,'port':3334,'public_url':''}

    def register(self, data):
        name=data.get('client_name','MCP assistant')
        urls=data.get('redirect_uris')
        if not isinstance(name,str) or not 1<=len(name)<=120 or not isinstance(urls,list) or not 1<=len(urls)<=10:
            raise ValueError('Provide a client name and one to ten redirect_uris')
        if data.get('token_endpoint_auth_method','none')!='none':
            raise ValueError('Only public clients with PKCE are supported')
        types=data.get('grant_types',['authorization_code','refresh_token'])
        if not isinstance(types,list) or not all(isinstance(t,str) for t in types) or 'authorization_code' not in types or set(types)-{'authorization_code','refresh_token'} or data.get('response_types',['code'])!=['code']:
            raise ValueError('Unsupported grant types')
        urls=[redirect_uri(url) for url in urls]
        ident=secrets.token_urlsafe(24)
        with self.db() as db:
            db.execute('DELETE FROM clients WHERE expires<?',(time.time(),))
            if db.execute('SELECT count(*) FROM clients').fetchone()[0]>=1000:
                raise ValueError('Too many registered clients')
            db.execute('INSERT INTO clients VALUES (?,?,?,?)',(ident,name,json.dumps(urls),time.time()+90*86400))
        return {'client_id':ident,'client_name':name,'redirect_uris':urls,'token_endpoint_auth_method':'none',
                'grant_types':['authorization_code','refresh_token'],'response_types':['code'],'scope':SCOPE}

    def request(self, data, resource):
        client=data.get('client_id'); uri=data.get('redirect_uri'); challenge=data.get('code_challenge','')
        state=data.get('state','')
        if not isinstance(state,str) or len(state)>2000 or data.get('response_type')!='code' or data.get('code_challenge_method')!='S256' or not re.fullmatch(r'[A-Za-z0-9_-]{43}',challenge):
            raise ValueError('Authorization requires code flow and S256 PKCE')
        if data.get('resource')!=resource or data.get('scope',SCOPE)!=SCOPE:
            raise ValueError('Invalid resource or scope')
        with self.db() as db:
            owner=db.execute('SELECT * FROM clients WHERE id=? AND expires>?',(client,time.time())).fetchone()
            if not owner or uri not in json.loads(owner['redirects']): raise ValueError('Unregistered client or redirect URI')
            db.execute('DELETE FROM requests WHERE expires<?',(time.time(),))
            if db.execute('SELECT count(*) FROM requests').fetchone()[0]>=200:
                raise ValueError('Too many pending authorization requests')
            ident=secrets.token_urlsafe(32)
            db.execute('INSERT INTO requests VALUES (?,?,?,?,?,?,?,?,?,?)',
                       (ident,client,uri,state,challenge,resource,time.time()+300,'pending','',secrets.token_hex(3).upper()))
        return ident

    def approve(self, ident, project, approved=True):
        if not isinstance(ident,str) or not isinstance(project,str) or len(project)>200:
            raise ValueError('Choose a valid request and collection')
        with self.db() as db:
            count=db.execute("UPDATE requests SET status=?,project=? WHERE id=? AND status='pending' AND expires>?",
                             ('approved' if approved else 'denied',project,ident,time.time())).rowcount
            if not count: raise ValueError('Request expired or already handled')

    def poll(self, ident):
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT r.*,c.name FROM requests r JOIN clients c ON c.id=r.client WHERE r.id=? AND r.expires>?',(ident,time.time())).fetchone()
            if not row: raise ValueError('Authorization request expired')
            if row['status']=='pending': return dict(row)
            db.execute('DELETE FROM requests WHERE id=?',(ident,))
            if row['status']=='denied': return dict(row)
            grant=secrets.token_urlsafe(24); code=secrets.token_urlsafe(32)
            now=time.time()
            db.execute('INSERT INTO grants VALUES (?,?,?,?,?,?,?,0)',(grant,row['client'],row['name'],row['project'],row['resource'],now,now+30*86400))
            db.execute('INSERT INTO codes VALUES (?,?,?,?,?,?,?)',(digest(code),row['client'],row['redirect'],row['challenge'],row['resource'],now+60,grant))
            return dict(row)|{'code':code}

    def _tokens(self, db, grant):
        now=time.time(); access=secrets.token_urlsafe(32); refresh=secrets.token_urlsafe(32)
        db.execute('INSERT INTO tokens VALUES (?,?,?,?)',(digest(access),grant['id'],'access',min(now+3600,grant['expires'])))
        db.execute('INSERT INTO tokens VALUES (?,?,?,?)',(digest(refresh),grant['id'],'refresh',grant['expires']))
        return {'access_token':access,'refresh_token':refresh,'token_type':'Bearer','expires_in':int(min(3600,grant['expires']-now)),'scope':SCOPE}

    def exchange(self, data, resource):
        now=time.time(); client=data.get('client_id')
        if data.get('resource')!=resource: raise ValueError('Invalid token resource')
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            if data.get('grant_type')=='authorization_code':
                code=data.get('code',''); verifier=data.get('code_verifier','')
                if not isinstance(code,str) or not isinstance(verifier,str) or not re.fullmatch(r'[A-Za-z0-9._~-]{43,128}',verifier):
                    raise ValueError('Invalid authorization code or verifier')
                row=db.execute('SELECT * FROM codes WHERE hash=? AND expires>?',(digest(code),now)).fetchone()
                challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
                if not row or row['client']!=client or row['redirect']!=data.get('redirect_uri') or row['resource']!=resource or not secrets.compare_digest(challenge,row['challenge']):
                    raise ValueError('Invalid authorization code or verifier')
                db.execute('DELETE FROM codes WHERE hash=?',(digest(code),)); grant_id=row['grant_id']
            elif data.get('grant_type')=='refresh_token':
                refresh=data.get('refresh_token','')
                if not isinstance(refresh,str): raise ValueError('Invalid refresh token')
                row=db.execute("SELECT * FROM tokens WHERE hash=? AND kind='refresh' AND expires>?",(digest(refresh),now)).fetchone()
                if not row: raise ValueError('Invalid refresh token')
                grant_id=row['grant_id']
                db.execute('DELETE FROM tokens WHERE hash=?',(digest(refresh),))
            else: raise ValueError('Unsupported grant type')
            grant=db.execute('SELECT * FROM grants WHERE id=? AND client=? AND resource=? AND revoked=0 AND expires>?',(grant_id,client,resource,now)).fetchone()
            if not grant: raise ValueError('Connection expired or revoked')
            return self._tokens(db,grant)

    def authenticate(self, token, resource):
        if not isinstance(token,str) or not 20<=len(token)<=200: return None
        with self.db() as db:
            row=db.execute("SELECT g.* FROM tokens t JOIN grants g ON g.id=t.grant_id WHERE t.hash=? AND t.kind='access' AND t.expires>? AND g.expires>? AND g.resource=? AND g.revoked=0",
                           (digest(token),time.time(),time.time(),resource)).fetchone()
            return dict(row) if row else None

    def issue_local(self, name, project, resource):
        if not isinstance(name,str) or not 1<=len(name)<=120 or not isinstance(project,str) or len(project)>200:
            raise ValueError('Choose a connection name and collection')
        ident=secrets.token_urlsafe(24); now=time.time()
        with self.db() as db:
            db.execute('INSERT INTO grants VALUES (?,?,?,?,?,?,?,0)',(ident,'local',name,project,resource,now,now+30*86400))
            grant=db.execute('SELECT * FROM grants WHERE id=?',(ident,)).fetchone()
            token=secrets.token_urlsafe(32)
            db.execute('INSERT INTO tokens VALUES (?,?,?,?)',(digest(token),ident,'access',now+30*86400))
        return {'id':ident,'token':token,'expires_in':30*86400}

    def revoke(self, ident):
        with self.db() as db:
            db.execute('UPDATE grants SET revoked=1 WHERE id=?',(ident,))
            db.execute('DELETE FROM tokens WHERE grant_id=?',(ident,))

    def status(self):
        with self.db() as db:
            pending=[dict(r) for r in db.execute("SELECT r.id,r.pairing,r.redirect,c.name,r.expires FROM requests r JOIN clients c ON c.id=r.client WHERE r.status='pending' AND r.expires>?",(time.time(),))]
            grants=[dict(r) for r in db.execute('SELECT id,name,project,created,expires FROM grants WHERE revoked=0 AND expires>? ORDER BY created DESC',(time.time(),))]
        return {'pending':pending,'connections':grants}
