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
.\.venv-capture\Scripts\python.exe -m wirebrain --home .wirebrain capture --install-ca --local-capture
```

The experimental Windows path uses mitmproxy Local Capture for Chrome, ChatGPT and Claude processes. Windows may ask for permission to start the network redirector. Setup trusts this diary's CA for the current user. Keep the private key under the diary certificates directory private. No browser extension, second login or Windows manual proxy configuration is involved. Process selection covers the browser process, including unrelated tabs. The host registry controls eligible HTTPS traffic. A client may reject the CA or use a different helper process. Native app coverage and forced termination on a real device are pending verification.

Open your existing ChatGPT or Claude tab and submit a **new** message. If the browser already has a persistent connection, reload the tab after enabling capture. View the prompt and streamed text reply at **http://127.0.0.1:3333**. Captures have `ChatGPT` or `Claude` source badges and are kept separate from `DEMO` records. Token usage is unavailable for web capture and is not estimated.

The dashboard reports whether the listener is active and whether Windows routing is enabled. That is listener/routing status, not proof that every app is compatible. A real captured exchange is the proof.

## Windows prototype acceptance checks

On a test PC, record the manual proxy enable flag, server, bypass and WinINet flags before starting. Check the same values during recording, after pause, after forced termination, and after removal. Do not enable the legacy proxy for these tests.

1. Submit distinct multi-turn probes in existing signed-in Chrome ChatGPT and Claude tabs. Compare the complete replies and conversation IDs with the diary.
2. Repeat separately in each native app. Record app version, process names and observed result, including rejected certificates or unsupported transports.
3. While loading an unrelated site in Chrome, force-stop the recorder and separately test terminating the controller. Verify fresh HTTPS connections work, with no manual proxy edits and no further captures.
4. Pause, run the exact CA removal command below, and verify the diary CA fingerprint is absent from the current-user root store. Compare the original network settings and check that the redirector is no longer intercepting. Keep the diary database unless the owner requests deletion.

## Stop and undo

Process capture stops when paused. The proxy restoration guidance below applies to legacy system-proxy sessions.

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

### Evidence for a release candidate

The version 1 registry accepts exact lowercase DNS names only. Wildcards, implicit subdomains, duplicate keys, invalid provider bindings and empty registries are rejected. Its SHA-256 covers canonical sorted compact JSON of the host map; this detects accidental edits, not malicious replacement of both the file and hash. Coverage changes currently require redistributing the package.

For process capture, require explicit HTTP/1 Host or HTTP/2 and HTTP/3 authority matching TLS SNI, allowing the default HTTPS port. Missing or inconsistent identities skip recording. This supplements upstream TLS validation. The per-flow diagnostics identify matched allowlisted hosts and gate decisions without logging raw unrecognized hosts or request data. Traffic bypassing the HTTP parser may have no diagnostic event.

Use a separate trial diary. Save timestamped evidence outside the public repo. From PowerShell, run scripts/check_windows_trial.ps1 with -OutputFile before.json **before** enabling capture. Repeat for during.json, paused.json and removed.json. After removal, pass -Baseline before.json to make the comparison fail when the recorded proxy values, connection blobs, root thumbprints, or redirector/driver state differ. Investigate each difference; the snapshot covers specified network and trust state, not the entire machine.

Compare each test reply with the text visible in the source app. Repeat abrupt termination during a page load and a fresh HTTPS handshake; retain timing and verify fresh connections in Chrome. Record pass, fail, or untested for each native app separately. A successful startup or matching proxy snapshot is insufficient. Keep the Windows installer release gated on clean removal, verified crash behavior, signing and a reproducible build.

Tagging a candidate `v*` triggers the Windows capture release workflow; it can also be dispatched manually. Only run its full seven-cycle gate on a disposable Windows machine with Chrome, Playwright, and the capture dependency. Three Chrome cases use a clean browser profile and a synthetic loopback TLS origin on port 443. Each requires agreement between Chrome and the diary at a specific streamed chunk, kills the worker, and checks fresh public HTTPS before resetting trust. The gate fails if a checkpoint is missing or snapshots drift. An interrupted in-flight reply is expected. Do not publish a candidate unless this workflow has passed for its commit; workflow configuration alone is not evidence of a passing run.

Initial Windows observations (2026-11-03): Chrome ChatGPT captured all ten requested numbers. Chrome Claude missed a first send and captured the retry after reload. The private trial ledger counted 408 earlier HTTP-gate events, zero gate drops, and no event identifiable as the first send. Connection reuse, bypass, and handshake failure have not been distinguished. Native ChatGPT captured the expected text but reported interrupted; native Claude 4.4212.0 had no matching recorded turn. Neither observation establishes certificate pinning. Four teardown cycles matched baseline after cleanup; the three Chrome stream checkpoints need their own evidence.
