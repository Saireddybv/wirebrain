# Capture your existing ChatGPT and Claude conversations

This mode reads the HTTPS traffic of the existing websites and compatible desktop apps. It uses your normal signed-in sessions. No provider API keys, API billing account, SDK integration, or base-URL environment variables are needed.

## Install and start (Windows)

From the repository directory:

```powershell
python -m venv .venv-capture
.\.venv-capture\Scripts\python.exe -m pip install -e '.[capture]'
.\.venv-capture\Scripts\python.exe -m wirebrain --home .wirebrain init
.\.venv-capture\Scripts\python.exe -m wirebrain --home .wirebrain up
```

In another terminal, explicitly enable capture:

```powershell
.\.venv-capture\Scripts\python.exe -m wirebrain --home .wirebrain capture --install-ca --system-proxy
```

These two flags are a deliberate one-time choice: trust the local capture certificate in the current Windows user's certificate store, and temporarily set that user's Windows HTTP proxy to `127.0.0.1:8082`. No administrator/root trust store or shell profile is changed. The CA's private key remains under `.wirebrain/certificates/`; do not share or commit that directory.

Open your existing ChatGPT or Claude tab and submit a **new** message. If the browser already has a persistent connection, reload the tab after enabling capture. View the prompt and streamed text reply at **http://127.0.0.1:3333**. Captures have `ChatGPT` or `Claude` source badges and are kept separate from `DEMO` records. Token usage is unavailable for web capture and is not estimated.

The dashboard reports whether the listener is active and whether Windows routing is enabled. That is listener/routing status, not proof that every app is compatible. A real captured exchange is the proof.

## Stop and undo

Click **Stop capture** in the dashboard, or press Ctrl+C in the capture terminal. Previous proxy values are restored before the listener stops. The dashboard can remain running.

A separate recovery process starts before Wirebrain changes the system proxy. If the recorder exits abruptly, the recovery process restores that session's saved settings. It leaves a proxy that you manually disabled or replaced alone. Normal stopping also restores settings before shutting down the listener.

Recovery cannot run during a power failure or if all Wirebrain processes are killed together. Restore the saved proxy values manually in those cases:

```powershell
.\.venv-capture\Scripts\python.exe -m wirebrain --home .wirebrain capture-reset
```

To also remove **this Wirebrain home's exact certificate** from the user trust store:

```powershell
.\.venv-capture\Scripts\python.exe -m wirebrain --home .wirebrain capture-reset --remove-ca
```

If the internet stops working before you can run that command, open **Windows Settings → Network & internet → Proxy**, edit **Use a proxy server**, and turn it off if its address is **`127.0.0.1:8082`** (or your configured capture port). Do not disable an unrelated corporate or VPN proxy. Reload or restart the affected browser. Wirebrain does not need to be running for this emergency step.

The saved proxy backup prevents a second automatic setup from overwriting your original settings. Resolve a leftover backup with `capture-reset` before starting capture again. That explicit command restores the original snapshot; pause capture first if you intend to replace its settings manually.

The system proxy routes proxy-aware web traffic through the local listener, including sites that are not recorded. The interception allowlist controls which HTTPS connections are decrypted; it does not provide a direct-network fallback when the listener is unavailable. Keep capture paused when it is not needed.

## Capture boundary

- Only `chatgpt.com`, `chat.openai.com`, and `claude.ai` are eligible for TLS interception. Other hosts are tunneled through the proxy without HTTPS decryption.
- Only submitted generation requests are saved: ChatGPT `/backend-api/conversation` and `/backend-api/f/conversation`, and Claude `/api/organizations/{id}/chat_conversations/{id}/completion`.
- It indexes submitted text and assistant text from full-message snapshots, ChatGPT patches, Claude text deltas, and legacy Claude completion events. Existing history is not automatically imported.
- ChatGPT compact deltas inherit omitted paths and operations, including nested patch batches and multiple text parts. When an existing captured conversation is reopened, its canonical history can repair a uniquely matched partial reply. Repair requires the same prompt, a timestamp within five minutes, and a longer reply that starts with the recorded text; it does not import uncaptured chats or alternate branches.
- Exchanges now retain source conversation IDs and available message/parent IDs. ChatGPT IDs come from the submitted request or the server's first streamed response for a new chat. Claude IDs come from its organization/conversation route. IDs are namespaced by provider (and by organization for Claude), so separate chats and services do not merge.
- The live feed groups exchanges by source chat and offers an **Open original** link. Selecting an exchange shows the captured turns in that chat in time order. Search filters the displayed matching exchanges; the detail view loads the captured conversation.
- Earlier records without retained IDs remain marked **Chat identity unavailable** and are never merged based on a shared project or similar text. Reopening ChatGPT history can associate a uniquely matched earlier record with its actual source chat, including a reply that was already fully captured.
- Cookies and authorization headers transit the proxy in memory as needed for your normal account, but are never persisted to the memory database or traffic dump files. The adapter never saves whole HTTP flows.
- Regex redaction runs before prompts and responses are persisted. Captured response bytes are returned unchanged to the client. This is a memory recorder, not an outgoing secret firewall for web chats.
- Normal upstream TLS certificate verification stays enabled. Do not bypass certificate warnings if setup fails.
- Apps that ignore Windows proxy settings, reject the local CA, use certificate pinning, use an unhandled transport, or change their private protocol are not guaranteed to work. Errors and unsupported response formats do not get marked as successfully captured.
- Attachments, generated files, images, voice, tool results, and private reasoning are not comprehensively indexed. WebSocket-only generations are not supported by this adapter.
- Capture affects future traffic only, while the recorder is running. It is not an OS background service.

**Desktop app coverage must be verified in each app.** The code does not install per-app plugins; compatible clients are captured through their existing network requests. A desktop app using the same accepted endpoints can be handled, but the current test fixtures do not prove compatibility with a particular app release.

## Verification

```powershell
.\.venv-capture\Scripts\python.exe -m unittest discover -s tests -v
```

The suite includes a real HTTPS CONNECT proxy test. A test client trusts a temporary CA only within its own SSL context; it sends ChatGPT and Claude protocol fixtures through mitmproxy to an offline HTTP streaming provider. The test verifies that both replies reach SQLite and credentials do not. It neither trusts a certificate system-wide nor changes Windows routing nor contacts the real services. Live account verification remains a separate step.

The optional dependency is isolated in `.venv-capture`. Python 3.11 currently installs mitmproxy 11.0.2 for these tests. Keep this local experimental interceptor private; do not expose its listener to other machines.
