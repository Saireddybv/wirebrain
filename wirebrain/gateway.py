"""Explicit, loopback-only API gateway; no TLS interception or credential storage."""
import json
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from .store import content_text, redact

PROVIDERS = {"openai": "https://api.openai.com", "anthropic": "https://api.anthropic.com",
             "groq": "https://api.groq.com/openai"}
ROUTES = {"/v1/chat/completions", "/v1/responses", "/v1/messages"}
MAX_BODY = 8 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never let a redirect take the caller's credentials to another host.
        return None


class Capture:
    def __init__(self):
        self.text = ""
        self.usage = {}

    def event(self, obj):
        if not isinstance(obj, dict):
            return
        for choice in obj.get("choices", []):
            self.text += content_text(choice.get("delta", choice.get("message", {})).get("content", ""))
        kind = obj.get("type", "")
        if kind == "content_block_delta":
            self.text += obj.get("delta", {}).get("text", "")
        elif kind == "response.output_text.delta":
            self.text += obj.get("delta", "")
        elif kind == "message_start":
            self.usage.update(obj.get("message", {}).get("usage", {}))
        if "content" in obj and isinstance(obj["content"], list):
            self.text += content_text(obj["content"])
        if kind == "response.completed" or "output" in obj:
            response = obj.get("response", obj)
            if not self.text:
                self.text = "\n".join(content_text(o.get("content", [])) for o in response.get("output", []))
            self.usage.update(response.get("usage", {}))
        self.usage.update(obj.get("usage", {}) or {})


def handler_factory(store, config, dashboard=False, upstreams=None):
    upstreams = upstreams or PROVIDERS

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_):
            pass  # Never log URLs, bodies, or credentials.

        def reject_local(self, message):
            # Closing a Windows socket with a small unread POST body can reset it
            # before the client receives the denial. Discard bounded bytes only;
            # never parse, store, or act on a rejected request.
            if self.command == 'POST':
                previous = self.connection.gettimeout()
                try:
                    length = int(self.headers.get('Content-Length','0'))
                    if 0 < length <= MAX_BODY:
                        self.connection.settimeout(.5)
                        while length:
                            chunk = self.rfile.read(min(length,65536))
                            if not chunk: break
                            length -= len(chunk)
                except (OSError,ValueError): pass
                finally: self.connection.settimeout(previous)
            self.reply({'error':message},403)
            return False

        def guard(self):
            host = self.headers.get("Host", "").split(":")[0]
            origin = self.headers.get("Origin")
            allowed = {"127.0.0.1", "localhost"}
            if host not in allowed:
                return self.reject_local('Invalid local host')
            if origin and origin not in {f"http://{h}:{config['dashboard_port']}" for h in allowed}:
                return self.reject_local('Cross-origin request denied')
            return True

        def reply(self, value, status=200, mime="application/json"):
            body = (json.dumps(value, ensure_ascii=False).encode() if mime == "application/json"
                    else value.encode() if isinstance(value, str) else value)
            self.send_response(status)
            self.send_header("Content-Type", mime + "; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def read_json(self):
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > MAX_BODY:
                raise ValueError("JSON body must be between 1 byte and 8 MB")
            return json.loads(self.rfile.read(length))

        def do_GET(self):
            if not self.guard():
                return
            path = urlsplit(self.path)
            params = parse_qs(path.query)
            if path.path == "/health":
                return self.reply({"ok": True, "version": "0.1.0"})
            if not dashboard:
                return self.reply({"error": "Use /openai/v1/chat/completions, /openai/v1/responses, /anthropic/v1/messages or /groq/v1/chat/completions"}, 404)
            if path.path == '/api/local/status':
                from .intelligence import settings, local_request, overview
                import platform
                try:
                    models = [m['name'] for m in local_request('tags').get('models',[]) if 'cloud' not in m.get('name','').lower() and not m.get('remote_host')]
                    available = True
                except ValueError:
                    models, available = [], False
                return self.reply({'settings':settings(store),'models':models,'available':available,'native_available':__import__('importlib.util',fromlist=['find_spec']).find_spec('fastembed') is not None,'platform':platform.system(), 'home':str(store.home.resolve()),'overview':overview(store)})
            if path.path == '/api/memory/search':
                from .intelligence import search
                try:
                    return self.reply(search(store,params.get('q',[''])[0],params.get('mode',['keyword'])[0],params.get('provider',[''])[0],params.get('project',[''])[0],params.get('saved',['0'])[0]=='1',limit=50 if params.get('q',[''])[0] else 1000))
                except (ValueError,TypeError) as exc: return self.reply({'error':str(exc)},400)
            if path.path == '/api/memory/overview':
                from .intelligence import overview
                return self.reply(overview(store))
            if path.path == "/api/feed":
                return self.reply(store.list(params.get("q", [""])[0],limit=1000,favorites=params.get('saved',['0'])[0]=='1'))
            if path.path == "/api/journal":
                from .diary import journal
                try:
                    return self.reply(journal(store,params.get('day',[''])[0],params.get('offset',['0'])[0]))
                except (ValueError,TypeError):
                    return self.reply({'error':'Choose a valid date and timezone'},400)
            if path.path == "/api/thread":
                return self.reply(store.thread(params.get("exchange", [""])[0]))
            if path.path == "/api/stats":
                with store.connect() as db:
                    stats = dict(db.execute("SELECT count(*) exchanges, count(distinct project) projects, coalesce(sum(input_tokens),0) input_tokens, coalesce(sum(output_tokens),0) output_tokens FROM conversations").fetchone())
                with store.connect() as db:
                    meta_binary = db.execute("SELECT count FROM capture_routes WHERE route='meta websocket binary transport'").fetchone()
                notices = ['Meta AI binary WebSocket traffic was detected. That transport is not supported yet; messages on that transport are not recorded.'] if meta_binary else []
                return self.reply({**stats, "redact_on_wire": config["redact_on_wire"], "search": "SQLite full-text", "version": "0.1.0", "capture": store.capture_state(), "capture_diagnostics": store.capture_diagnostics(), "capture_notices": notices})
            if path.path == "/api/projects":
                return self.reply(store.projects())
            if path.path == "/api/reflection":
                day = params.get("day", [datetime.now(timezone.utc).date().isoformat()])[0]
                try:
                    datetime.strptime(day, "%Y-%m-%d")
                except ValueError:
                    return self.reply({"error": "Expected YYYY-MM-DD"}, 400)
                return self.reply({"body": store.reflection(day)})
            if path.path == "/api/export":
                return self.reply(store.export(), mime="application/octet-stream")
            if path.path == '/api/diary/export':
                from .diary import export_diary
                return self.reply(json.dumps(export_diary(store),ensure_ascii=False),mime='application/octet-stream')
            assets = {"/": "index.html", "/app.js": "app.js", "/style.css": "style.css", "/workflows.js": "workflows.js"}
            if path.path in assets:
                asset = assets[path.path]
                mime = {"html": "text/html", "js": "application/javascript", "css": "text/css"}[asset.split(".")[-1]]
                return self.reply((Path(__file__).parent / "static" / asset).read_bytes(), mime=mime)
            self.reply({"error": "Not found"}, 404)

        def do_DELETE(self):
            if not self.guard():
                return
            if dashboard and self.path.startswith("/api/conversations/"):
                store.delete(self.path.rsplit("/", 1)[-1])
                return self.reply({"ok": True})
            self.reply({"error": "Not found"}, 404)

        def do_POST(self):
            if not self.guard():
                return
            try:
                payload = self.read_json()
                if not isinstance(payload, dict):
                    raise ValueError("Expected a JSON object")
            except (ValueError, UnicodeDecodeError):
                return self.reply({"error": "Invalid JSON body (maximum 8 MB)"}, 400)
            if dashboard:
                if self.path.startswith('/api/workflows/'):
                    from .workflows import report, snippets, save_snippet, remove_snippet, compare, usage, select, scope
                    action = self.path.rsplit('/',1)[-1]
                    try:
                        if action == 'report': return self.reply(report(store,payload))
                        if action == 'snippets': return self.reply({'snippets':snippets(store,payload)})
                        if action == 'save-snippet': return self.reply(save_snippet(store,payload))
                        if action == 'remove-snippet': return self.reply(remove_snippet(store,payload))
                        if action == 'mcp-config':
                            import sys
                            project = scope(payload)['project']
                            args = ['-m','wirebrain','--home',str(store.home.resolve()),'mcp']
                            if project: args += ['--project',project]
                            return self.reply({'mcpServers':{'wirebrain':{'command':sys.executable,'args':args}}})
                        if action == 'compare': return self.reply(compare(store,payload))
                        if action == 'usage': return self.reply(usage(store,payload))
                        if action == 'candidates':
                            rows = select(store,payload)
                            return self.reply({'rows':[{**{key:r[key] for key in ('id','created','provider','model','project')},'prompt':r['prompt'][:300]} for r in rows]})
                        return self.reply({'error':'Unknown workflow'},404)
                    except (ValueError,TypeError) as exc: return self.reply({'error':str(exc)},400)
                if self.path == '/api/local/prepare':
                    from .intelligence import prepare_native
                    try: return self.reply(prepare_native(store))
                    except ValueError as exc: return self.reply({'error':str(exc)},400)
                if self.path == '/api/memory/import':
                    from .importer import import_history
                    try: return self.reply(import_history(store,payload.get('data')))
                    except (ValueError,TypeError,KeyError,OverflowError) as exc: return self.reply({'error':str(exc)},400)
                if self.path in ('/api/local/settings','/api/local/index','/api/memory/collection','/api/memory/reflect'):
                    from .intelligence import settings, index_batch, collection, generate
                    try:
                        if self.path == '/api/local/settings': return self.reply(settings(store,payload))
                        if self.path == '/api/local/index': return self.reply(index_batch(store))
                        if self.path == '/api/memory/collection': return self.reply(collection(store,payload.get('id'),payload.get('name')))
                        from .diary import journal
                        day = journal(store,payload.get('day',''),payload.get('offset',0))
                        rows = day['entries'][:8]
                        if not rows: raise ValueError('No conversations were captured on this day')
                        return self.reply({'answer':generate(store,'Reflect on the recorded day: what was explored, possible open questions, and one optional next step. Do not assume a task is unfinished just because completion is not recorded.',rows,day['note']), 'sources':rows,'generated':True})
                    except (ValueError,TypeError) as exc: return self.reply({'error':str(exc)},400)
                if self.path == '/api/capture/start':
                    from .capture import start_background
                    try: return self.reply(start_background(store.home))
                    except (ValueError,OSError) as exc: return self.reply({'error':str(exc)},400)
                if self.path == '/api/diary/note':
                    from .diary import save_note
                    try: return self.reply(save_note(store,payload.get('day',''),payload.get('body')))
                    except (ValueError,TypeError): return self.reply({'error':'Choose a valid date and a note under 20,000 characters'},400)
                if self.path.startswith('/api/entries/') and self.path.endswith('/favorite'):
                    from .diary import favorite
                    try: return self.reply(favorite(store,self.path.split('/')[3],payload.get('favorite')))
                    except ValueError as exc: return self.reply({'error':str(exc)},400)
                if self.path == "/api/capture/stop":
                    store.capture_stop(True)
                    return self.reply({"ok": True})
                if self.path == "/api/ask":
                    from .intelligence import ask
                    try: return self.reply(ask(store,payload))
                    except (ValueError,TypeError) as exc: return self.reply({'error':str(exc)},400)
                return self.reply({"error": "Not found"}, 404)
            parts = urlsplit(self.path).path.split("/", 2)
            if len(parts) != 3 or parts[1] not in upstreams or "/" + parts[2] not in ROUTES:
                return self.reply({"error": "Unsupported provider or route"}, 404)
            provider, route = parts[1], "/" + parts[2]
            messages = payload.get("messages", payload.get("input", ""))
            if isinstance(messages, list):
                prompt = "\n\n".join(f"{m.get('role', 'user')}: {content_text(m.get('content', ''))}" for m in messages if isinstance(m, dict))
            else:
                prompt = content_text(messages)
            for field in ('system','instructions'):
                context = content_text(payload.get(field,''))
                if context: prompt = field + ': ' + context + '\n\n' + prompt
            ident = store.add(provider, str(payload.get("model", "unknown")), prompt,
                              self.headers.get("X-Wirebrain-Project", "Inbox"))
            # Serialize then redact string leaves only, preserving valid JSON and types.
            def clean(value):
                if isinstance(value, str): return redact(value)
                if isinstance(value, list): return [clean(v) for v in value]
                if isinstance(value, dict): return {k: clean(v) for k, v in value.items()}
                return value
            body = json.dumps(clean(payload) if config["redact_on_wire"] else payload).encode()
            headers = {"Content-Type": "application/json", "Accept-Encoding": "identity"}
            for name in ("Authorization", "x-api-key", "anthropic-version", "anthropic-beta", "OpenAI-Organization", "OpenAI-Project"):
                if self.headers.get(name): headers[name] = self.headers[name]
            request = urllib.request.Request(upstreams[provider] + route, body, headers)
            capture = Capture()
            status = "complete"
            started = False
            try:
                opener = urllib.request.build_opener(NoRedirect)
                with opener.open(request, timeout=120) as response:
                    self.send_response(response.status)
                    mime = response.headers.get("Content-Type", "application/json")
                    self.send_header("Content-Type", mime)
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    started = True
                    if "text/event-stream" in mime:
                        pending = []
                        last_save = 0
                        for line in response:
                            self.wfile.write(line)
                            self.wfile.flush()
                            if line.startswith(b"data:"):
                                pending.append(line[5:].strip())
                            if not line.strip() and pending:
                                try: capture.event(json.loads(b"\n".join(pending)))
                                except (ValueError, TypeError, AttributeError): pass
                                pending = []
                                if time.monotonic() - last_save > .3:
                                    store.update(ident, capture.text, "streaming", capture.usage)
                                    last_save = time.monotonic()
                    else:
                        raw = response.read()
                        self.wfile.write(raw)
                        try: capture.event(json.loads(raw))
                        except (ValueError, TypeError, AttributeError): pass
            except urllib.error.HTTPError as exc:
                status = "error"
                store.update(ident, capture.text, status, capture.usage)
                exc.close()
                self.reply({"error": "Upstream rejected the request", "upstream_status": exc.code}, exc.code)
            except (OSError, ValueError):
                status = "interrupted" if started else "error"
                if not started:
                    self.reply({"error": "Upstream connection failed"}, 502)
            finally:
                store.update(ident, capture.text, status, capture.usage)
    return Handler


def serve(store, config):
    gateway = (ThreadingHTTPServer(("127.0.0.1", config["gateway_port"]), handler_factory(store, config))
               if config.get('enable_api_gateway',False) else None)
    try:
        dashboard = ThreadingHTTPServer(("127.0.0.1", config["dashboard_port"]), handler_factory(store, config, True))
    except OSError:
        if gateway: gateway.server_close()
        raise
    stop = threading.Event()

    def reflect():
        while not stop.wait(60):
            try:
                store.reflection(datetime.now(timezone.utc).date().isoformat())
                from .intelligence import settings, index_batch
                if settings(store)['embedding_model']: index_batch(store)
            except Exception: pass

    if gateway: threading.Thread(target=gateway.serve_forever, daemon=True).start()
    threading.Thread(target=reflect, daemon=True).start()
    print(f"Your Wirebrain diary  http://127.0.0.1:{config['dashboard_port']}\nPress Ctrl+C to stop the diary.", flush=True)
    if gateway: print(f"Optional developer gateway: http://127.0.0.1:{config['gateway_port']}",flush=True)
    try:
        dashboard.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        stop.set()
        if gateway:
            gateway.shutdown()
            gateway.server_close()
        dashboard.server_close()
