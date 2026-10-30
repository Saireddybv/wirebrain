import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from .store import Store

DEFAULTS = {"gateway_port": 8080, "dashboard_port": 3333, "redact_on_wire": False}


def seed(store):
    if any(r["demo"] for r in store.list(limit=100000)):
        return
    samples = [
        ("openai", "demo · OpenAI", "Atlas", "How should I implement row-level security for a multi-tenant workspace?",
         "Use a workspace_members table and policies scoped to auth.uid(). Test SELECT, INSERT and UPDATE independently. Keep service-role credentials on the server; never ship them to the browser."),
        ("anthropic", "demo · Claude", "Atlas", "Why does my streaming endpoint buffer the entire response?",
         "Check the reverse proxy: disable response buffering and return Content-Type: text/event-stream. Flush each event and send periodic heartbeats. Verify with curl --no-buffer before debugging the frontend."),
        ("groq", "demo · Groq", "Wirebrain", "Design a local-first memory pipeline with SQLite FTS5.",
         "Capture → normalize → redact → SQLite. Use WAL for concurrent reads and writes. Update the full-text index alongside conversation writes, and expose source excerpts with every search result."),
        ("openai", "demo · OpenAI", "Homelab", "Explain Docker networking between my API and PostgreSQL.",
         "Containers on the same Compose network resolve each other by service name. Use postgres:5432 inside the API container. localhost points back to the current container, not the host or database."),
        ("anthropic", "demo · Claude", "Wirebrain", "What should an honest daily reflection include?",
         "Group the original questions by project. Preserve timestamps and links to evidence. A question about shipping a feature is not proof that it shipped. Keep inferred conclusions clearly separate from recorded activity.")]
    for provider, model, project, prompt, response in samples:
        ident = store.add(provider, model, prompt, project, demo=True)
        store.update(ident, response, usage={"input_tokens": 124, "output_tokens": 218})


def main():
    for stream in (sys.stdin, sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Wirebrain — your AI work, remembered locally")
    parser.add_argument("--home", default=os.environ.get("WIREBRAIN_HOME") or str(Path.home() / ".wirebrain"))
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init", help="Create a local database and config")
    init.add_argument("--demo", action="store_true", help="Add clearly labeled sample conversations")
    up = commands.add_parser("up", help="Open your personal diary and its local activity worker")
    up.add_argument('--api-gateway',action='store_true',help='Also enable the optional developer gateway')
    up.add_argument("--gateway-port", type=int)
    up.add_argument("--dashboard-port", type=int)
    up.add_argument("--redact-on-wire", action="store_true", help="Also redact detected secrets before forwarding prompts")
    commands.add_parser("demo", help="Add labeled sample data (makes no AI requests)")
    mcp = commands.add_parser("mcp", help="Run the read-only MCP stdio server")
    mcp.add_argument('--project',default='',help='Restrict every memory tool to this collection')
    reports = commands.add_parser('report',help='Export a source-linked personal workflow as Markdown')
    reports.add_argument('--kind',choices=['weekly','standup','study','timeline','research','handoff'],default='weekly')
    reports.add_argument('--from',dest='date_from')
    reports.add_argument('--to',dest='date_to')
    reports.add_argument('--project',default='')
    reports.add_argument('--provider',default='')
    reports.add_argument('--offset',type=int,default=0,help='Timezone offset in minutes east of UTC')
    reports.add_argument('--generate',action='store_true',help='Use the configured local writing model')
    reports.add_argument('--output',type=Path)
    commands.add_parser("doctor", help="Check local storage and configuration")
    capture = commands.add_parser("capture", help="Capture existing ChatGPT/Claude HTTPS traffic; no provider API key needed")
    capture.add_argument("--port", type=int, default=8082)
    capture.add_argument("--install-ca", action="store_true", help="Explicitly trust the local interception CA in the user certificate store")
    capture.add_argument("--system-proxy", action="store_true", help="Explicitly route supported proxy-aware apps through capture; restored on exit")
    reset = commands.add_parser("capture-reset", help="Restore saved proxy settings after an unclean capture shutdown")
    reset.add_argument("--remove-ca", action="store_true", help="Also remove this Wirebrain home's exact CA from the user trust store")
    search = commands.add_parser("search", help="Search local memory")
    search.add_argument("query")
    reflection = commands.add_parser("reflect", help="Print a deterministic local activity digest")
    reflection.add_argument("--day", default=datetime.now(timezone.utc).date().isoformat())
    export = commands.add_parser("export", help="Export redacted history as JSON")
    export.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        store = Store(args.home)
        config_path = Path(args.home) / "config.json"
        config = {**DEFAULTS, **(json.loads(config_path.read_text()) if config_path.exists() else {})}
        if args.command == "init":
            if not config_path.exists():
                config_path.write_text(json.dumps(config, indent=2), encoding="utf-8")
            if args.demo: seed(store)
            print(f"Ready: {store.home}\nStart with: wirebrain up\nNo certificates or shell profiles were changed.")
        elif args.command == "demo":
            seed(store)
            print("Sample conversations added and labeled DEMO.")
        elif args.command == "up":
            from .gateway import serve
            for key in ("gateway_port", "dashboard_port"):
                config[key] = getattr(args, key) or config[key]
                if not isinstance(config[key], int) or not 1 <= config[key] <= 65535:
                    raise ValueError("Ports must be integers between 1 and 65535")
            config["redact_on_wire"] = args.redact_on_wire or config["redact_on_wire"]
            config['enable_api_gateway'] = args.api_gateway
            serve(store, config)
        elif args.command == "capture":
            from .capture import run
            run(store.home, args.port, args.install_ca, args.system_proxy)
        elif args.command == "capture-reset":
            from .capture import reset_proxy, remove_ca
            store.capture_stop(True)
            reset_proxy(store.home)
            if args.remove_ca: remove_ca(store.home)
            print("Previous proxy settings restored.")
        elif args.command == "mcp":
            from .mcp import run
            run(store,args.project)
        elif args.command == 'report':
            from .workflows import report
            result = report(store,vars(args))
            if args.output: args.output.write_text(result['body'],encoding='utf-8')
            else: print(result['body'])
        elif args.command == "search":
            print(json.dumps(store.list(args.query), indent=2, ensure_ascii=False))
        elif args.command == "reflect":
            datetime.strptime(args.day, "%Y-%m-%d")
            print(store.reflection(args.day))
        elif args.command == "export":
            data = store.export()
            if args.output:
                args.output.write_text(data, encoding="utf-8")
                print(f"Exported to {args.output}")
            else: print(data)
        elif args.command == "doctor":
            with store.connect() as db:
                integrity = db.execute("PRAGMA integrity_check").fetchone()[0]
            print(f"Database: {store.path}\nIntegrity: {integrity}\nSearch: SQLite FTS5\nRuntime: Python {sys.version.split()[0]}\nConfig: {json.dumps(config)}")
    except (OSError, ValueError) as exc:
        parser.exit(1, f"wirebrain: {exc}\n")


if __name__ == "__main__":
    main()
