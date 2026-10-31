<div align="center">

# Wirebrain

### Git tracks your code. Wirebrain remembers the thinking behind it.

A local-first memory and personal diary for your AI conversations.<br>
Find past answers, reflect on your work, and carry context between assistants.

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](pyproject.toml)
[![Status: experimental](https://img.shields.io/badge/Status-experimental-orange.svg)](#project-status)

[Website](https://saireddybv.github.io/wirebrain/) · [Get started](#quick-start) · [Connect an assistant](#connect-an-assistant) · [Documentation](#documentation) · [Contribute](CONTRIBUTING.md)

</div>

---

Your useful answers are scattered across ChatGPT, Claude, Gemini, Grok, and Meta AI. Wirebrain keeps the supported conversations you capture or import in one searchable place on your computer, with their original prompts, replies, and source links.

**No provider API key is required for the diary, history imports, or supported existing-session capture.** Keyword search and original-source tools work without an LLM. Optional models add semantic search, reusable memory, and source-linked writing.

## Project status

Experimental software for a single local owner. Capture uses changing private web protocols and an opt-in HTTPS proxy. Windows is the primary live-tested platform; real-device macOS capture is still pending. Wirebrain does not capture every app or synchronize providers' private saved-memory stores.

## What you can do

| Feature | What it does |
| --- | --- |
| **My diary** | Browse grouped conversation cards, select a day, sort latest/oldest, keep Favorites, and see local storage usage. Responsive light and dark appearances. |
| **Search** | Find exact words with SQLite FTS5, or combine word matches with optional local embeddings to search by meaning. Open the original evidence. |
| **Memory** | Build reusable topics automatically when AI processing is enabled. Review personal-fact suggestions in Reflect. View combined Wirebrain memory or filter by AI app and collection. |
| **Reflect** | Revisit recurring learning topics, inspect a source-linked map of request types, and reuse automatically extracted prompts, email drafts, and workflows. |
| **Tools** | Read whole captured conversations, prepare context handoffs, export reports, save code snippets, compare prompts/replies, and inspect provider-reported usage. |
| **MCP** | Let compatible assistants search memory, discover chats, and read captured turns. Use local stdio or a shared authenticated HTTP endpoint with collection permissions and revocation. |
| **Import and export** | Import supported ChatGPT, Claude, or Wirebrain JSON exports. Back up conversations, notes, reusable memory, and saved snippets locally. |

Reflections are grounded in captured evidence. A repeated question is not a proficiency score, a diagnosis, or proof that work was completed.

## Quick start

Install **Python 3.11 or newer**, then run:

```sh
git clone https://github.com/Saireddybv/wirebrain.git
cd wirebrain
python start_wirebrain.py
```

Or [download the repository ZIP](https://github.com/Saireddybv/wirebrain/archive/refs/heads/main.zip), extract it, and run `python start_wirebrain.py` in that folder.

1. The launcher creates an isolated Python environment and installs the capture and local-search dependencies. The first setup needs internet access.
2. Your diary opens at **http://127.0.0.1:3333/**.
3. Choose whether to enable existing-session capture. The launcher asks before trusting a local certificate or changing proxy settings. You can choose diary-only and import history instead.
4. Use your supported AI apps normally. Reload already-open chat tabs after enabling capture. Optional AI features are in **Local setup**.

Windows also provides `Start-Wirebrain.ps1`; on macOS use `bash Start-Wirebrain.command`. This is a source launcher, not a signed desktop installer or a published npm package.

### Start and stop

Keep the launcher terminal open while using Wirebrain. **Ctrl+C** stops its foreground processes and restores proxy settings when its recorder exits normally. The diary's recording controls can pause or resume an already-configured recorder.

If capture ended unexpectedly, restore its saved proxy settings with:

```sh
wirebrain --home /absolute/path/to/your/diary capture-reset
```

Use the Python environment created by the launcher when `wirebrain` is not on your PATH. Global `--home` comes before the subcommand. An existing checkout archive is reused; new checkouts default to `~/.wirebrain`. Set `WIREBRAIN_HOME` to choose another location. See [capture setup and recovery](docs/HTTPS_CAPTURE.md).

## Capture support

| Source | Current coverage |
| --- | --- |
| ChatGPT | Text conversations through supported web/app requests and streams. |
| Claude | Text conversations through supported web/app requests and streams. |
| Gemini | Supported `gemini.google.com` text chat transports. |
| Grok | Supported `grok.com` text chat transports. |
| Meta AI | Supported `meta.ai` HTTP and binary/WebSocket text chat transports. |

Gemini, Grok, and Meta AI adapters have been checked with live Chrome exchanges. Availability still depends on the website rollout, request format, and whether traffic reaches the proxy. Some native apps bypass proxies or reject interception certificates.

Images, voice, file contents, WhatsApp/Facebook/Instagram chats, and X-embedded Grok are not comprehensively covered. Wirebrain cannot recover history it never captured unless you import a supported export.

**Platform notes:** Windows has live capture verification. macOS has trust/proxy setup and simulated restoration tests, but actual Safari, Chrome, and native-app capture on a Mac is not yet verified. Linux can run the diary, imports, and MCP; Windows/macOS automatic certificate and proxy setup does not apply there.

[Capture coverage and limitations →](docs/CAPTURE-COVERAGE.md)

## Connect an assistant

Discuss a project in Claude, then ask a connected coding assistant:

> “Find my Claude conversation from the last hour, read the relevant turns, and help me continue.”

The assistant retrieves context on demand through Wirebrain's read-only tools. It can request more turns when needed; Wirebrain does not send the entire archive with every question.

### Local desktop and coding clients

Open **Tools → Continue & connect → Show connection configuration**, choose a collection if you want restricted access, and copy the generated configuration into a client supporting local stdio MCP. Reconnect or restart that client.

A generic configuration looks like this; replace the interpreter and data directory with your own absolute paths:

```json
{
  "mcpServers": {
    "wirebrain": {
      "command": "/absolute/path/to/python",
      "args": ["-m", "wirebrain", "--home", "/absolute/path/to/diary", "mcp"]
    }
  }
}
```

Multiple clients can read the same local database. The stdio connection does not require the dashboard to stay running. The recorder must run to capture new conversations. Local Claude Desktop retrieval has been verified using a synthetic conversation.

### HTTP clients and web assistants

Open **Tools → Remote MCP** and start the authenticated HTTP server. Its default endpoint is **http://127.0.0.1:3334/mcp**. HTTP coding clients can use a generated bearer configuration; OAuth clients require local approval, a fixed collection permission, and can be revoked.

Web/cloud assistants additionally need a reachable **HTTPS tunnel or reverse proxy to the MCP port**, plus compatible OAuth/MCP support. Wirebrain does not create a tunnel. Keep the diary port **3333 private**. The OAuth flow is tested locally; a live public ChatGPT/Claude web connection is not yet verified.

| MCP tool | Purpose |
| --- | --- |
| `list_conversations` | Find chats by app, topic, collection, date, or recent activity. |
| `read_conversation` | Read captured turns in chronological, paginated form. |
| `read_memory` | Page an individual prompt or reply, including long text. |
| `search_memory` | Search the captured conversation archive. |
| `search_personal_memory` | Retrieve reusable memory with supporting sources. |
| `recent_memory` | Read recent recorded exchanges. |
| `conversation_handoff` | Prepare portable context for one conversation. |
| `context_handoff` | Prepare a source report across a collection or date range. |

MCP targets protocol version `2025-06-18`; client compatibility varies. Connected assistants may send retrieved context to their AI provider. Tools cannot change your archive, run commands, or send messages. [Local connection guide](docs/TOOLS.md) · [HTTP and OAuth guide](docs/REMOTE_MCP.md)

## Optional AI features

**Semantic search:** enable the small local CPU embedding model in Local setup, then update the memory index. FastEmbed or a locally installed Ollama embedding model can supply embeddings. Keyword search works without either.

**Memory and writing:** choose a locally downloaded Ollama writing model that fits your hardware. Enable automatic memory processing to extract useful topics and suggestions from idle conversations. Personal facts require review in Reflect before they enter reusable recall. Original conversations remain available throughout.

**ChatGPT sign-in testing:** an optional writing backend uses an existing official Codex CLI ChatGPT login. This sends selected input and evidence to OpenAI and uses that account's allowance; it is separate from local inference. There is no provider API-key fallback. See [the testing gateway guide](docs/CHATGPT_TEST_GATEWAY.md).

Model downloads need internet access. After downloading local models, local inference runs on your computer. No writing model is downloaded or enabled silently.

## How it works

```text
Supported AI sessions → opt-in local HTTPS recorder
Supported JSON exports → history importer
                                 ↓
                    SQLite archive + text search
                                 ↓
              Optional local embeddings and writing
                                 ↓
                  Diary · Memory · Reflect · Tools
                                 ↓
             Read-only MCP → connected assistants
```

The interface is plain HTML, CSS, and JavaScript, with no frontend build step or CDN runtime. Core storage uses Python's standard library and SQLite. Capture and embedding runtimes are optional dependency groups. Model instructions live in versioned Markdown files under [`wirebrain/prompts/`](wirebrain/prompts/), with JSON schemas and a catalog.

There is also a separate, opt-in developer API gateway for existing API clients. It is off during normal startup; see [developer workflows](docs/WORKFLOWS.md).

## Privacy and boundaries

- **Local storage, explicit sharing.** The archive is stored on your device. Local Ollama/FastEmbed inference is local. Connected assistants and the optional ChatGPT testing backend can send selected context to their providers.
- **Capture is opt-in.** HTTPS capture requires trusting a local CA and configuring a proxy. Only the adapter's explicit AI allowlist is decrypted. Certificates, credentials, and raw traffic are not public project assets.
- **Plaintext archive.** SQLite and exported files are not encrypted by Wirebrain. Use OS account protection and disk encryption. Best-effort secret redaction can miss sensitive text.
- **Separate network surfaces.** The dashboard, recorder, and optional API gateway stay private on loopback. Only the authenticated MCP listener is designed for use behind a trusted HTTPS tunnel. Local processes under your account remain trusted.
- **Deletion has limits.** Removing a source invalidates its derived memory and search entries. This is not forensic erasure of SQLite pages, backups, exports, or context already shared with another assistant.
- **No universal capture promise.** Provider protocols change. Partial captures and unsupported output can occur. Source links, capture status, and excerpt coverage help you verify what was actually recorded.

[Security policy](SECURITY.md) · [Capture permissions and rollback](docs/HTTPS_CAPTURE.md)

## Documentation

| Guide | Covers |
| --- | --- |
| [Capture setup](docs/HTTPS_CAPTURE.md) | Permissions, platform setup, and recovery. |
| [Capture coverage](docs/CAPTURE-COVERAGE.md) | Supported transports and exclusions. |
| [Personal memory](docs/PERSONAL_MEMORY.md) | Automatic extraction, evidence, review, and forgetting. |
| [Reflect](docs/REFLECT.md) | Study guides, AI-use map, macro library, and suggestions. |
| [Tools](docs/TOOLS.md) | Conversation reading, local MCP, and portable handoffs. |
| [Remote MCP](docs/REMOTE_MCP.md) | Shared HTTP endpoint, OAuth, tokens, and HTTPS setup. |
| [Workflows](docs/WORKFLOWS.md) | Reports, snippets, comparisons, and reported usage. |
| [Prompts](docs/PROMPTS.md) | Versioned Markdown instructions and JSON schemas. |
| [Verification](docs/VERIFICATION.md) | Test evidence and remaining limits. |

## Development and contribution

```sh
python -m venv .venv
# Activate the environment using your operating system's activation command.
python -m pip install -e .
python -m unittest discover -s tests -v
python scripts/check_site.py
```

Use Node.js for syntax checks on JavaScript files in `wirebrain/static/`. Capture tests can use `python -m pip install -e ".[capture]"`; semantic-runtime work can use `".[capture,memory]"`. CI covers Windows, Linux, and macOS without real accounts or private chat fixtures.

We welcome focused fixes, provider compatibility reports, accessibility improvements, and better synthetic protocol fixtures. Open an [issue](https://github.com/Saireddybv/wirebrain/issues), join [Discussions](https://github.com/Saireddybv/wirebrain/discussions), or read [CONTRIBUTING.md](CONTRIBUTING.md). All changes to `main` go through pull requests and required checks. Never attach real conversations, cookies, keys, certificates, or private screenshots to public reports.

[Roadmap](ROADMAP.md) · [Governance](GOVERNANCE.md) · [Code of conduct](CODE_OF_CONDUCT.md)

## License

[MIT](LICENSE). Free to use, inspect, modify, and contribute to. Wirebrain is an independent project and is not affiliated with the AI providers it supports.
