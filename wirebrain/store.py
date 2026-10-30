"""Local persistence. Credentials and raw request headers never enter SQLite."""
import json
import re
import sqlite3
import uuid
import hashlib
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def redact(text):
    patterns = [r"(?s)-----BEGIN (?:[A-Z0-9]+ )*PRIVATE KEY-----.*?-----END (?:[A-Z0-9]+ )*PRIVATE KEY-----",
                r"(?i)\bBearer\s+[A-Za-z0-9._~+/-]{8,}=*",
                r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b",
                r"\bgithub_pat_[A-Za-z0-9_]{20,}",
                r"\bsk-[A-Za-z0-9_-]{12,}", r"\bgsk_[A-Za-z0-9]{12,}",
                r"\bgh[pousr]_[A-Za-z0-9]{20,}", r"\bAKIA[A-Z0-9]{16}\b",
                r"(?i)(?:api[_-]?key|password|secret|token)\s*[=:]\s*['\"]?[^\s'\",;]{8,}"]
    for pattern in patterns:
        text = re.sub(pattern, "[REDACTED]", text)
    return text


def content_text(value):
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(content_text(item) for item in value if isinstance(item, (str, dict)))
    if isinstance(value, dict):
        return str(value.get("text", value.get("content", "")))
    return ""


class Store:
    def __init__(self, home):
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.path = self.home / "memory.sqlite3"
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS conversations (
                  id TEXT PRIMARY KEY, created TEXT, provider TEXT, model TEXT,
                  project TEXT, prompt TEXT, response TEXT, status TEXT,
                  input_tokens INTEGER DEFAULT 0, output_tokens INTEGER DEFAULT 0,
                  demo INTEGER DEFAULT 0);
                CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts USING fts5(id UNINDEXED, prompt, response, project);
                CREATE TABLE IF NOT EXISTS reflections (day TEXT PRIMARY KEY, body TEXT, updated TEXT);
                CREATE TABLE IF NOT EXISTS capture_state (id INTEGER PRIMARY KEY CHECK (id=1), body TEXT);
                CREATE TABLE IF NOT EXISTS capture_control (id INTEGER PRIMARY KEY CHECK (id=1), stop INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS capture_diagnostics (host TEXT PRIMARY KEY, requests INTEGER DEFAULT 0, prompts INTEGER DEFAULT 0, last_seen TEXT);
                CREATE TABLE IF NOT EXISTS capture_routes (route TEXT PRIMARY KEY, keys TEXT, count INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS threads (id TEXT PRIMARY KEY, provider TEXT NOT NULL, conversation_id TEXT NOT NULL, title TEXT, source_url TEXT);
                CREATE TABLE IF NOT EXISTS exchange_threads (exchange_id TEXT PRIMARY KEY, thread_id TEXT, message_id TEXT, parent_message_id TEXT, response_message_id TEXT);
                CREATE INDEX IF NOT EXISTS exchange_thread_index ON exchange_threads(thread_id);
                CREATE TABLE IF NOT EXISTS diary_notes (day TEXT PRIMARY KEY, body TEXT NOT NULL, updated TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS intelligence_settings (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS memory_vectors (exchange_id TEXT, model TEXT, part INTEGER, hash TEXT, vector TEXT, PRIMARY KEY(exchange_id,model,part));
                CREATE TABLE IF NOT EXISTS entry_flags (exchange_id TEXT PRIMARY KEY, favorite INTEGER DEFAULT 0);
                CREATE TABLE IF NOT EXISTS usage_metadata (exchange_id TEXT PRIMARY KEY, reported INTEGER NOT NULL DEFAULT 0,
                  input_reported INTEGER NOT NULL DEFAULT 0, output_reported INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS saved_snippets (id TEXT PRIMARY KEY, exchange_id TEXT NOT NULL,
                  title TEXT NOT NULL, content TEXT NOT NULL, language TEXT NOT NULL, created TEXT NOT NULL);
            """)
            db.execute('BEGIN IMMEDIATE')
            columns = {row['name'] for row in db.execute('PRAGMA table_info(usage_metadata)')}
            for field, counter in (('input_reported','input_tokens'),('output_reported','output_tokens')):
                if field not in columns:
                    db.execute(f'ALTER TABLE usage_metadata ADD COLUMN {field} INTEGER NOT NULL DEFAULT 0')
                    db.execute(f'UPDATE usage_metadata SET {field}=1 WHERE exchange_id IN (SELECT id FROM conversations WHERE {counter}>0)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def add(self, provider, model, prompt, project="Inbox", demo=False):
        ident = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (ident, datetime.now(timezone.utc).isoformat(), provider, redact(model),
                        redact(project)[:120], redact(prompt), "", "streaming", 0, 0, int(demo)))
            db.execute("INSERT INTO memory_fts VALUES (?,?,?,?)", (ident, redact(prompt), "", redact(project)))
        return ident

    def update(self, ident, response, status="complete", usage=None):
        usage = usage or {}
        reported = [usage.get('input_tokens',usage.get('prompt_tokens')),
                    usage.get('output_tokens',usage.get('completion_tokens'))]
        reported = [value if isinstance(value,int) and not isinstance(value,bool) and value>=0 else None for value in reported]
        with self.connect() as db:
            db.execute("UPDATE conversations SET response=?,status=?,input_tokens=coalesce(?,input_tokens),output_tokens=coalesce(?,output_tokens) WHERE id=?",
                       (redact(response), status, *reported, ident))
            db.execute("UPDATE memory_fts SET response=? WHERE id=?", (redact(response), ident))
            if any(value is not None for value in reported):
                db.execute('INSERT INTO usage_metadata VALUES (?,1,?,?) ON CONFLICT(exchange_id) DO UPDATE SET reported=1,input_reported=max(usage_metadata.input_reported,excluded.input_reported),output_reported=max(usage_metadata.output_reported,excluded.output_reported)',
                           (ident,int(reported[0] is not None),int(reported[1] is not None)))

    def link_exchange(self, ident, provider, conversation_id="", message_id="", parent_message_id="", response_message_id="", title=""):
        # Namespace IDs by service; a project name or similar prompt is never a chat ID.
        def clean(value): return value[:512] if isinstance(value, str) else ""
        conversation_id = clean(conversation_id)
        thread_id = hashlib.sha256((provider + '\0' + conversation_id).encode()).hexdigest() if conversation_id else None
        with self.connect() as db:
            row = db.execute("SELECT provider,prompt FROM conversations WHERE id=?", (ident,)).fetchone()
            if not row or row['provider'] != provider: return
            current = db.execute("SELECT thread_id FROM exchange_threads WHERE exchange_id=?", (ident,)).fetchone()
            if current and current['thread_id'] and thread_id and current['thread_id'] != thread_id:
                return  # Never silently reassign an exchange to a different source chat.
            if thread_id:
                from urllib.parse import quote
                source_id = conversation_id.rsplit('/', 1)[-1]
                source_url = (("https://chatgpt.com/c/" if provider == 'chatgpt' else "https://claude.ai/chat/") + quote(source_id, safe="")) if provider in ('chatgpt','claude') else ""
                if provider == 'gemini': source_url = 'https://gemini.google.com/app/' + quote(source_id.removeprefix('c_'), safe='')
                elif provider == 'grok': source_url = 'https://grok.com/c/' + quote(source_id, safe='')
                if provider == 'meta' and re.fullmatch(r'[0-9a-fA-F-]{36}', source_id): source_url = 'https://www.meta.ai/prompt/' + quote(source_id, safe='')
                db.execute("INSERT OR IGNORE INTO threads VALUES (?,?,?,?,?)", (thread_id, provider, conversation_id, redact(title or row['prompt'])[:120], source_url))
                if source_url:
                    db.execute("UPDATE threads SET source_url=? WHERE id=? AND source_url=''",(source_url,thread_id))
                existing = db.execute('SELECT c.project FROM conversations c JOIN exchange_threads e ON e.exchange_id=c.id WHERE e.thread_id=? AND c.id<>? ORDER BY c.created LIMIT 1',(thread_id,ident)).fetchone()
                if existing:
                    db.execute('UPDATE conversations SET project=? WHERE id=?',(existing['project'],ident))
                    db.execute('UPDATE memory_fts SET project=? WHERE id=?',(existing['project'],ident))
            db.execute("""INSERT INTO exchange_threads VALUES (?,?,?,?,?) ON CONFLICT(exchange_id) DO UPDATE SET
                thread_id=coalesce(excluded.thread_id,exchange_threads.thread_id),
                message_id=coalesce(nullif(excluded.message_id,''),exchange_threads.message_id),
                parent_message_id=coalesce(nullif(excluded.parent_message_id,''),exchange_threads.parent_message_id),
                response_message_id=coalesce(nullif(excluded.response_message_id,''),exchange_threads.response_message_id)""",
                (ident, thread_id, clean(message_id), clean(parent_message_id), clean(response_message_id)))

    def thread(self, exchange_id):
        with self.connect() as db:
            row = db.execute("SELECT thread_id FROM exchange_threads WHERE exchange_id=?", (exchange_id,)).fetchone()
        rows = self.list(limit=10000, thread_id=row['thread_id']) if row and row['thread_id'] else self.list(limit=1, exchange_id=exchange_id)
        return sorted(rows, key=lambda r:r['created'])

    def repair_chatgpt_history(self, data):
        """Repair uniquely matched partial captures; never import unrelated history."""
        from .webcapture import history_pairs
        repaired = 0
        links = []
        conversation_id = data.get('conversation_id', '') if isinstance(data, dict) else ''
        with self.connect() as db:
            for pair in history_pairs(data):
                if not isinstance(pair["created"], (float, int)): continue
                prompt, response = redact(pair["prompt"]), redact(pair["response"])
                candidates = []
                for row in db.execute("SELECT * FROM conversations WHERE provider='chatgpt' AND demo=0 AND prompt=?", (prompt,)):
                    created = datetime.fromisoformat(row["created"]).timestamp()
                    if abs(created - pair["created"]) <= 300 and len(response) >= len(row["response"]) and response.startswith(row["response"]):
                        candidates.append(row)
                if len(candidates) != 1: continue
                ident = candidates[0]["id"]
                if len(response) > len(candidates[0]['response']):
                    db.execute("UPDATE conversations SET response=?,status='complete' WHERE id=?", (response, ident))
                    db.execute("UPDATE memory_fts SET response=? WHERE id=?", (response, ident))
                    repaired += 1
                if conversation_id:
                    links.append((ident, pair))
            if repaired: db.execute("DELETE FROM reflections")
        for ident, pair in links:
            self.link_exchange(ident, 'chatgpt', conversation_id, pair.get('message_id'), pair.get('parent_message_id'), pair.get('response_message_id'), data.get('title', ''))
        return repaired

    def list(self, query="", limit=100, day=None, thread_id=None, exchange_id=None, day_offset=0, favorites=False,
             date_from=None, date_to=None, provider='', project='', model=''):
        with self.connect() as db:
            args = []
            sql = """SELECT c.*,coalesce(flags.favorite,0) AS favorite,e.thread_id,e.message_id,e.parent_message_id,e.response_message_id,
                     t.conversation_id,t.title AS thread_title,t.source_url,
                     coalesce(u.reported,CASE WHEN c.input_tokens>0 OR c.output_tokens>0 THEN 1 ELSE 0 END) AS usage_reported,
                     coalesce(u.input_reported,CASE WHEN c.input_tokens>0 THEN 1 ELSE 0 END) AS input_reported,
                     coalesce(u.output_reported,CASE WHEN c.output_tokens>0 THEN 1 ELSE 0 END) AS output_reported FROM conversations c
                     LEFT JOIN exchange_threads e ON c.id=e.exchange_id LEFT JOIN threads t ON e.thread_id=t.id
                     LEFT JOIN entry_flags flags ON flags.exchange_id=c.id
                     LEFT JOIN usage_metadata u ON u.exchange_id=c.id"""
            if query:
                words = re.findall(r"\w+", query, re.UNICODE)[:24]
                if not words:
                    return []
                sql += " JOIN memory_fts f ON c.id=f.id WHERE memory_fts MATCH ?"
                args.append(" OR ".join('"' + w + '"' for w in words))
            else:
                sql += " WHERE 1=1"
            if day:
                sql += " AND date(c.created,?)=?"
                args.extend((f"{int(day_offset)} minutes", day))
            if favorites:
                sql += " AND flags.favorite=1"
            for boundary, operator in ((date_from, '>='), (date_to, '<=')):
                if boundary:
                    sql += f' AND date(c.created,?) {operator} ?'
                    args.extend((f'{int(day_offset)} minutes', boundary))
            if provider:
                aliases = {'chatgpt': ('chatgpt','openai'), 'claude': ('claude','anthropic')}
                values = aliases.get(provider, (provider,))
                sql += ' AND c.provider IN (' + ','.join('?' for _ in values) + ')'
                args.extend(values)
            if project:
                sql += ' AND c.project=?'
                args.append(project)
            if model:
                sql += ' AND c.model=?'
                args.append(model)
            if thread_id:
                sql += " AND e.thread_id=?"
                args.append(thread_id)
            if exchange_id:
                sql += " AND c.id=?"
                args.append(exchange_id)
            sql += (" ORDER BY bm25(memory_fts), c.created DESC LIMIT ?" if query
                    else " ORDER BY c.created DESC LIMIT ?")
            return [dict(r) for r in db.execute(sql, (*args, limit))]

    def delete(self, ident):
        with self.connect() as db:
            db.execute("DELETE FROM memory_fts WHERE id=?", (ident,))
            db.execute("DELETE FROM conversations WHERE id=?", (ident,))
            db.execute("DELETE FROM memory_vectors WHERE exchange_id=?", (ident,))
            db.execute("DELETE FROM exchange_threads WHERE exchange_id=?", (ident,))
            db.execute("DELETE FROM entry_flags WHERE exchange_id=?", (ident,))
            db.execute('DELETE FROM usage_metadata WHERE exchange_id=?', (ident,))
            db.execute('DELETE FROM saved_snippets WHERE exchange_id=?', (ident,))
            db.execute("DELETE FROM threads WHERE id NOT IN (SELECT thread_id FROM exchange_threads WHERE thread_id IS NOT NULL)")
            # Derived summaries may contain deleted content; invalidate all of them.
            db.execute("DELETE FROM reflections")

    def reflection(self, day):
        rows = self.list(limit=10000, day=day)
        groups = {}
        for row in reversed(rows):
            groups.setdefault(row["project"], []).append(row)
        lines = [f"# Reflection · {day}", "", f"{len(rows)} captured exchanges · {len(groups)} projects", "",
                 "This local activity digest quotes your history; it does not infer completed work.", ""]
        for project, items in groups.items():
            lines += [f"## {project}", ""]
            for item in items:
                lines += [f"- {item['prompt'][:240].replace(chr(10), ' ')} ({item['provider']}, {item['status']})"]
            lines += [""]
        if not rows:
            lines += ["No conversations captured for this UTC date yet."]
        body = "\n".join(lines)
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO reflections VALUES (?,?,?)",
                       (day, body, datetime.now(timezone.utc).isoformat()))
        return body

    def projects(self):
        groups = {}
        for row in self.list(limit=10000):
            groups.setdefault(row["project"], []).append(row)
        return [{"name": name, "count": len(rows), "updated": rows[0]["created"],
                 "markdown": "# " + name + "\n\n" + "\n\n".join(
                     f"## {r['created'][:16]} · {r['model']}\n\n{r['prompt']}\n\n{r['response']}" for r in rows)}
                for name, rows in groups.items()]

    def export(self):
        return json.dumps(self.list(limit=1000000), indent=2, ensure_ascii=False)

    def capture_state(self, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO capture_state VALUES (1,?)", (json.dumps(value),))
            row = db.execute("SELECT body FROM capture_state WHERE id=1").fetchone()
        state = json.loads(row[0]) if row else {"running": False}
        if state.get("running"):
            import time
            if time.time() - state.get("heartbeat", 0) > 15:
                state = {**state, "running": False, "stale": True}
        return state

    def capture_stop(self, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO capture_control VALUES (1,?)", (int(value),))
            row = db.execute("SELECT stop FROM capture_control WHERE id=1").fetchone()
        return bool(row[0]) if row else False

    def capture_seen(self, host, prompt=False):
        with self.connect() as db:
            db.execute("INSERT INTO capture_diagnostics VALUES (?,?,?,?) ON CONFLICT(host) DO UPDATE SET requests=requests+excluded.requests, prompts=prompts+excluded.prompts,last_seen=excluded.last_seen",
                       (host, int(not prompt), int(prompt), datetime.now(timezone.utc).isoformat()))

    def capture_diagnostics(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM capture_diagnostics ORDER BY last_seen DESC")]

    def capture_route(self, host, method, path, body):
        # Only protocol vocabulary is retained; identifiers, values and query strings are discarded.
        from urllib.parse import urlsplit
        vocabulary = {"backend-api", "backend-anon", "api", "organizations", "chat_conversations", "completion", "conversation", "f", "prepare", "resume", "messages", "conversations", "chat", "stream", "send", "v1", "v2", "response", "responses", "ask", "append_message", "chat_message", "websocket", "user", "retry_completion"}
        segments = [s if s in vocabulary else ":segment" for s in urlsplit(path).path.split("/") if s]
        keys = []
        try:
            data = json.loads(body)
            known_keys = {"prompt", "messages", "message", "model", "action", "input", "content", "text", "parent_message_id", "conversation_id", "attachments", "files", "tools", "stream", "timezone", "timezone_offset_min", "completion", "query"}
            if isinstance(data, dict): keys = sorted(set(data) & known_keys)
        except (ValueError, TypeError, UnicodeError): pass
        route = f"{host} {method} /{'/'.join(segments)}"
        with self.connect() as db:
            db.execute("INSERT INTO capture_routes VALUES (?,?,1) ON CONFLICT(route) DO UPDATE SET keys=excluded.keys,count=count+1", (route, json.dumps(keys)))

    def capture_routes(self):
        with self.connect() as db:
            return [dict(r) for r in db.execute("SELECT * FROM capture_routes ORDER BY count DESC")]
