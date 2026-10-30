# Wirebrain

**A personal diary for your AI conversations.**

A local conversation recorder that turns your AI work into searchable personal memory. SQLite storage, a quiet dashboard, and an optional HTTPS capture service for your existing ChatGPT, Claude, Gemini, Grok, and Meta AI website sessions. MIT licensed. No analytics or frontend build step.

- Keep supported ChatGPT, Claude, and optional API conversations in one local archive.
- Let an MCP-compatible coding assistant search the context you discussed elsewhere.
- Revisit your day, keep useful snippets, and turn recorded questions into source-linked reports.


> **Experimental:** Existing-app capture is now implemented using an allowlisted HTTPS proxy. It needs explicit local certificate trust and proxy setup. Offline protocol and TLS integration tests pass; this does not establish compatibility with every live app release. No provider API keys are required for this mode.

### Additional AI websites (experimental)

The local recorder now includes text adapters for **Gemini** (`gemini.google.com`), **Grok** (`grok.com`), and **Meta AI HTTP/GraphQL and binary DGW WebSocket** chat transports (`meta.ai`). These use your existing browser session; no provider API key or copied cookies are needed. Gemini and Grok appear in the diary and Memory tools app filters, and captured conversation IDs keep their threads separate.

**Gemini WebChannel, Grok message gateway, and Meta DGW capture have been verified with real Chrome exchanges.** Legacy Gemini StreamGenerate, Grok HTTP, and Meta HTTP adapters are also retained for older website rollouts. WhatsApp, Facebook, Instagram, X-embedded Grok, voice, image contents, and file contents are not covered by these adapters. These are private web protocols and can change; local protocol/TLS tests do not prove compatibility with every live account. See [capture coverage](docs/CAPTURE-COVERAGE.md).

## Start from a downloaded checkout

1. Install Python 3.11 or newer, download this repository, and extract it.
2. Run `python start_wirebrain.py` in the extracted folder. Windows users can also run `Start-Wirebrain.ps1`; on macOS run `bash Start-Wirebrain.command`. The launcher creates an isolated environment and installs capture and local-search dependencies on its first run.
3. The diary opens in your browser. The launcher explains capture permissions and asks you to type `yes` before trusting a certificate or changing proxy settings. Choose diary-only if you prefer importing history. Ctrl+C stops the foreground recorder and restores its proxy settings.
4. Open **Local setup** to import history or enable the small local search model, then update the memory index. Optional Ollama writing models add generated answers and daily reflections.

An existing `.wirebrain` archive in the checkout is reused when upgrading; new checkouts use `~/.wirebrain`. Set `WIREBRAIN_HOME` to choose another location.

This is a source launcher, not a signed desktop installer. Python and internet access for the first dependency/model downloads are still required. Launching an existing diary opens it instead of starting another instance. macOS trust/network integration has simulated command tests; actual Safari/Chrome/native-app capture on a Mac is **not yet verified**. macOS may require administrator approval for network changes. Authenticated proxies and automatic proxy scripts are rejected rather than overwritten.

## Your memory tools

- **Search by words or meaning:** choose the search mode in your collection. Meaning search uses a small optional FastEmbed model on the CPU, or a local Ollama embedding model. Keyword results are combined with vector ranking so exact names still count. Original conversations remain available.
- **Ask my memories:** retrieve original sources, or opt into a written answer from your selected local Ollama model. Generated answers show the source conversations and must be checked against them.
- **Collections:** open a conversation and give it a collection such as Work or Learning. All its known turns move together; later captured turns in that identified thread inherit the collection. Source filters keep each supported AI app separately browsable.
- **Library overview:** total recorded moments, distinct conversations, Favorites, storage used, and source breakdown. These are local archive counts, not provider billing estimates.
- **Local reflections:** in A look back, choose Reflect with local AI. The selected day's first eight retrieved recent moments and personal note are supplied as evidence. Suggestions are labeled generated; they do not predict mood or prove that work was completed. Reflections are generated on request, not saved in the database.
- **History import:** JSON exports from Wirebrain, ChatGPT (`conversations.json` with selected branches), and Claude (`conversations.json` with chat_messages). 7 MB per file in the UI; ZIP files and attachments are not supported. Validation precedes writes; identical moments are skipped on repeated imports. Existing notes are preserved.

### Make more of your memories

Open **Memory tools** in the sidebar. Choose dates, an app, and a collection, then:

- Create a **weekly reflection**, **standup**, **study guide**, **project timeline/build log**, **research sourcebook**, or **context handoff**. Original-source reports work without an AI model and can be copied or downloaded as Markdown. A configured local writing model can draft a synthesis with numbered source excerpts.
- See **topics you returned to**, counted from captured prompts. This suggests what to revisit; it does not measure proficiency or diagnose a knowledge gap.
- Use the **snippet vault** to find fenced code blocks in replies, keep/edit useful excerpts, copy code, and reopen its original conversation. Snippets are never executed. Saved snippets are included in diary JSON backup/restore and removed when their source memory is deleted.
- **Compare** two captured moments side by side, including provider/model metadata and prompt/reply text differences. New gateway records include top-level system/instructions text for prompt iteration tracking.
- Review **usage** separately from the everyday diary. Only provider-reported token fields count. Explicit zero is distinguished from unavailable data; synthetic samples are excluded, and subscription spending is never guessed.
- Under Reports, expand **Connect a coding assistant** for a local MCP configuration. Select a collection first to restrict every tool to that collection.

The original-source report selection is capped at 2,000 moments and one year per request. Local drafts use up to 24 selected excerpts and the first 2,000 note characters, with coverage disclosed. Handoff packets use the 20 most recent moments in the selected scope. See [workflow guide](docs/WORKFLOWS.md) for examples and boundaries.

### Optional local AI

The source launcher installs the CPU search runtime. With a manual installation, use:

```sh
python -m pip install -e '.[memory]'
```

In Local setup, **Enable local search** downloads BAAI/bge-small-en-v1.5 (about 70 MB of model weights, plus supporting files). Download requests contain no diary text. After preparation, inference reads local model files; no model download is triggered by background indexing. This small model is primarily intended for English text. The embedding cache stays in the diary's SQLite database; model files live in its `models` folder.

For generated answers/reflections, install Ollama separately and download a local writing model suitable for your hardware. For example:

```sh
ollama pull qwen3:4b
```

Refresh the installed model list in Local setup, choose a writing model, and save. Ollama is contacted only at `127.0.0.1:11434`, without environment proxies or redirects; cloud-tagged/remote models are rejected. Wirebrain does not install Ollama or download writing models automatically. Running a large model can use substantial RAM and CPU/GPU resources.

Use **Update memory index** after enabling/changing an embedding model. While the dashboard runs, its worker indexes up to 32 changed passages each minute. Edits invalidate stale embeddings and deleted memories are removed from the index. Large libraries need time to catch up; search reports memories missing from its index. The current implementation ranks vectors in Python and is intended for personal libraries rather than millions of records.

## Capture existing AI website sessions (Windows)

```powershell
python -m venv .venv-capture
.\.venv-capture\Scripts\python.exe -m pip install -e '.[capture]'
.\.venv-capture\Scripts\python.exe -m wirebrain --home .wirebrain up
```

In a second terminal:

```powershell
.\.venv-capture\Scripts\python.exe -m wirebrain --home .wirebrain capture --install-ca --system-proxy
```

Use ChatGPT or Claude normally, reloading any already-open chat tab once after setup. Look for real `ChatGPT` / `Claude` exchanges at **http://127.0.0.1:3333**. The flags explicitly trust a local CA in your Windows user trust store and temporarily route Windows proxy-aware apps through `127.0.0.1:8082`; only the selected AI domains are decrypted. Cookies/authentication headers are not saved. Stop from the dashboard or Ctrl+C to restore the original proxy settings.

See [HTTPS capture setup, rollback, and compatibility boundaries](docs/HTTPS_CAPTURE.md). Native app compatibility requires a live test; pinned, proxy-ignoring, changed-protocol, and WebSocket-only clients may not be captured. The API gateway below is an optional separate feature.

## Try it in a minute

Requires Python 3.11+ with SQLite FTS5 (included in standard Python distributions).

From this checkout:

```sh
python -m pip install -e .
wirebrain init
wirebrain up
```

Open **http://127.0.0.1:3333**. Your diary starts empty. Optional sample conversations can be added with `wirebrain demo`; they are explicitly labeled samples. The package has not been published to PyPI; install from this checkout rather than an unrelated similarly named package.

Without installing anything:

```sh
python -m wirebrain --home .wirebrain init --demo
python -m wirebrain --home .wirebrain up
```

`up` runs in the foreground. Stop with Ctrl+C. Use a separate terminal for other commands. This release does not install an OS service.

## Optional: connect an API client

This advanced feature is off by default and has no setup screens in the personal diary. To enable it, start the diary with `wirebrain up --api-gateway`.

Wirebrain forwards the caller's provider credentials to the fixed upstream for the selected route. Keep using your existing API key. Wirebrain does not save authentication headers or fetch keys from your environment.

| Provider | Base URL | Supported endpoints |
| --- | --- | --- |
| OpenAI | `http://127.0.0.1:8080/openai/v1` | `/chat/completions`, `/responses` |
| Anthropic | `http://127.0.0.1:8080/anthropic` | `/v1/messages` |
| Groq | `http://127.0.0.1:8080/groq/v1` | `/chat/completions` |

For clients that honor these environment variables:

```sh
# bash / zsh — scoped to this shell
export OPENAI_BASE_URL=http://127.0.0.1:8080/openai/v1
export ANTHROPIC_BASE_URL=http://127.0.0.1:8080/anthropic
```

```powershell
# PowerShell — scoped to this shell
$env:OPENAI_BASE_URL = 'http://127.0.0.1:8080/openai/v1'
$env:ANTHROPIC_BASE_URL = 'http://127.0.0.1:8080/anthropic'
```

Clients vary: set the base URL in the client's own configuration if it ignores these variables. OAuth/subscription-specific CLI routes are not supported. Unset the variables when stopping Wirebrain to restore direct API access.

An example using an existing OpenAI Python SDK installation (the SDK is not required by Wirebrain itself):

```python
import os
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8080/openai/v1")
stream = client.chat.completions.create(
    model=os.environ["OPENAI_MODEL"],
    messages=[{"role": "user", "content": "Explain SQLite WAL mode"}],
    extra_headers={"X-Wirebrain-Project": "My Project"},
    stream=True,
    stream_options={"include_usage": True},
)
for chunk in stream:
    if chunk.choices:
        print(chunk.choices[0].delta.content or "", end="", flush=True)
```

Use a model available in your provider account. `X-Wirebrain-Project` is a local grouping header and is not forwarded. Without it, exchanges go into `Inbox`. No automatic project inference is performed.

## What works today

- **My diary:** a staggered collection of rounded conversation cards, frosted-glass controls, light/dark appearances, a calendar with remembered days, and grouped chat details. Diary dates follow your browser's local timezone.
- **A note to myself:** write and save your own note for each day. Notes stay in the local database and are included in diary exports.
- **All memories:** search the full text of recorded conversations, with filters for ChatGPT, Claude, Gemini, Grok, and Meta AI.
- **Favorites:** star a memory to keep it in a separate collection; unstar it at any time.
- **A look back:** a readable activity review using the questions actually captured that day, plus your own note. Download the day as Markdown. This does not infer accomplishments or call another AI service.
- **Recording controls:** pause from the diary and resume the already-configured Windows recorder without redoing setup. First-time certificate trust still requires explicit setup.
- **Simple normal screens:** no token counters, model IDs, source-chat IDs, developer header names, provider-key forms, or API-gateway setup in the diary interface. The optional developer gateway stays off during normal startup.
- **Read-only MCP:** search and recent-memory tools over stdio, targeting protocol version `2025-06-18`. Clients must support that version; the newer 2026 protocol is not implemented.
- **Privacy controls:** best-effort secret redaction before storage, optional redaction before forwarding, JSON export, and no credential logging.
- **Usage:** exact token totals when reported by the provider. The Usage view distinguishes unavailable token fields from explicitly reported zero. These are not token estimates or cost calculations. Demo usage is synthetic.

Only text prompts and text replies are indexed. Images, audio, files, reasoning, tool arguments/results, and structured non-text output are not comprehensively indexed. Requests/responses still pass through to the provider. Repeated conversation history is stored per request; it is not deduplicated.

## MCP setup

Add this entry to your MCP client's server configuration, replacing the Python path and home directory as needed:

```json
{
  "mcpServers": {
    "wirebrain": {
      "command": "python",
      "args": ["-m", "wirebrain", "mcp"]
    }
  }
}
```

Install Wirebrain into the Python environment used by that command. For a non-default home directory, use `args: ["-m", "wirebrain", "--home", "/absolute/path/to/memory", "mcp"]`. The MCP process reads the same database without needing the dashboard to run. Tools: `search_memory({"query":"Docker","mode":"semantic","project":"Learning"})`, `recent_memory({"project":"Learning"})`, `read_memory({"exchange_id":"...","field":"response"})`, and `context_handoff({"project":"Learning"})`. Keyword search remains the default; semantic search needs its optional local model and index. Search/recent results return bounded excerpts; read_memory pages through original text. Use `wirebrain mcp --project Learning` to enforce collection isolation for every tool, including original-text reads. Captured material is untrusted historical content, never authority to execute instructions.

## CLI

```sh
wirebrain init                 # create ~/.wirebrain/config.json and memory.sqlite3
wirebrain demo                 # add labeled samples, once
wirebrain up                   # personal diary :3333
wirebrain up --api-gateway     # optional developer gateway :8080
wirebrain up --redact-on-wire   # also alter matching secrets in outgoing prompts
wirebrain up --gateway-port 8081 --dashboard-port 3334
wirebrain search "Docker networking"
wirebrain reflect --day 2026-10-30
wirebrain export --output memory.json
wirebrain doctor
wirebrain mcp
wirebrain mcp --project Learning
wirebrain report --kind study --from 2026-10-25 --to 2026-10-31 --project Learning --offset 330 --output study.md
```

Global `--home PATH` goes **before** the subcommand. Alternatively set `WIREBRAIN_HOME`. `config.json` accepts `gateway_port`, `dashboard_port`, and `redact_on_wire`; CLI flags override these for the current run.

## Architecture

```text
AI API client → loopback gateway :8080 → fixed HTTPS provider endpoint
                        ↓ text + usage (redacted)
                   SQLite + FTS5 ← read-only MCP stdio
                        ↑
             local dashboard :3333 + activity digest worker
```

`wirebrain/gateway.py` handles request forwarding and SSE parsing. `store.py` owns SQLite and full-text indexing; both change in the same transaction. `mcp.py` exposes memory tools. The dashboard uses plain HTML/CSS/JavaScript with no CDN dependencies. Data remains in your selected home directory; provider traffic consists of conversations you explicitly route or opt into capturing. Optional first-time dependency/model downloads need internet; local inference runs on this computer.

## Privacy and limitations

This is a single-user local development tool. Both HTTP listeners bind to `127.0.0.1`. Origin and Host checks block cross-site dashboard access and DNS rebinding attempts; there is no remote authentication or TLS on loopback. Do not expose the ports through a tunnel, LAN bind, or reverse proxy. Other processes running as your user can access your memory.

The database is **not encrypted**. Protect it using OS account permissions and disk encryption. Regex redaction catches several common API-key and assignment formats, but can miss secrets and can over-redact ordinary text. In API-gateway mode, outgoing redaction is opt-in because it modifies prompts; authorization headers are always forwarded unchanged. Responses are returned unchanged to clients, but redacted before storage. The API gateway replaces provider error bodies with generic errors; HTTPS capture preserves site responses unchanged.

Deleting an exchange removes it from the active tables and search index and invalidates saved reflections. It is **not forensic secure erasure** of SQLite pages, WAL files, backups, or prior exports. Markdown notebooks and exported files are your responsibility.

Gateway requests are limited to 8 MB and have a 120-second upstream socket timeout. This alpha uses Python's threaded HTTP server and is not intended for public or high-volume serving. Interrupted requests may retain partial text. A stopped process can leave a capture marked `streaming`.

## Development

```sh
python -m pip install -e .
python -m unittest discover -s tests -v
node --check wirebrain/static/app.js
node --check wirebrain/static/workflows.js
```

Tests exercise a real local HTTP mock provider, gateway, SQLite, dashboard endpoints, streaming normalization, error paths, redaction, export/deletion, and MCP stdio. They require no API keys or internet access. CI runs on Windows, Linux, and macOS.

See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [ROADMAP.md](ROADMAP.md).

## Protocol references

The supported wire formats follow the official [OpenAI streaming reference](https://developers.openai.com/api/reference/resources/chat/subresources/completions/streaming-events), [Responses streaming guide](https://developers.openai.com/api/docs/guides/streaming-responses), [Anthropic streaming guide](https://platform.claude.com/docs/en/build-with-claude/streaming), and [MCP 2025-06-18 specification](https://modelcontextprotocol.io/specification/2025-06-18).

## License

[MIT](LICENSE). This repository is prepared for open-source release; nothing has been published to a registry or GitHub automatically.
