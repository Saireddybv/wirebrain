# Verification

## Latest local results

Validated on Windows with Python 3.11 and the optional capture/search dependencies:

- All 77 tests passed, including the real local HTTPS interception test.
- `node --check wirebrain/static/app.js` passed.
- `python -m pip check` reported no broken requirements.
- Source and wheel packages built successfully. The source archive includes launchers and excludes local diaries, virtual environments, certificates, screenshots, and downloaded models.
- The small CPU embedding model was downloaded and exercised against a local diary. A meaning-based query retrieved a relevant conversation when keyword search returned no matches.

Tests use synthetic conversations and temporary databases. The HTTPS test uses an offline provider and a temporary certificate trusted only by its test client; it does not change operating-system trust or proxy settings.

## Coverage

- ChatGPT snapshots and compact JSON patches; Claude delta and legacy completion formats; UTF-8 split across network chunks; interrupted responses and exclusion of unrelated domains.
- Source-thread grouping, provider namespaces, history repair without unrelated history import, and preservation of unidentified legacy exchanges.
- Local-day calendars and notes, Favorites, exports, deletion, and safe rendering of conversation text.
- Semantic retrieval without lexical overlap, provider/collection filtering, stale-index invalidation, and removal of embeddings when memories are deleted.
- Whole-thread collections, validated and repeatable JSON imports, source-linked answers, local-day reflection requests, and cross-origin rejection.
- Windows proxy backup/restoration against a mocked registry; macOS proxy setup/restoration and failure recovery against mocked system commands.

## Browser checks

The Chromium-based preview was checked at desktop, tablet, narrow-phone, and landscape sizes. Navigation, drawer dismissal, search, original-source opening, and the local setup screen were exercised. No horizontal page overflow was observed at the checked sizes. Screenshots containing diary content remain outside version control.

## Boundaries

- macOS certificate/proxy integration is implemented but has not been verified on real Mac hardware. Safari and native Mac app capture are not established by simulated command tests.
- Ollama writing-model answers and reflections have mocked local-service integration coverage. A real writing-model inference run has not been verified in this workspace.
- No signed Windows installer or notarized macOS app has been built. The provided launchers require Python and first-run dependency downloads.
- Offline protocol/TLS tests do not guarantee compatibility with every release of ChatGPT or Claude, pinned clients, proxy-ignoring apps, voice, attachments, or unsupported transports. Check a real exchange before claiming support for an app release.

## Reproduce

```sh
python -m pip install -e '.[capture,memory]'
python -m pip check
python -m unittest discover -s tests -v
node --check wirebrain/static/app.js
node --check wirebrain/static/workflows.js
```

CI defines core tests on Linux, Windows, and macOS, a Windows HTTPS capture job, and combined capture/search runtime import checks on all three platforms. Configured CI jobs are not evidence of a completed remote run.


## Memory workflows — 2026-10-31

Story: select dates/app/collection in Memory tools → local workflow API → scoped SQLite records → report/snippet/comparison/usage result → original-source opening or Markdown export.

| Boundary | Result | Evidence |
| --- | --- | --- |
| UI → API → report | Passed | Weekly report created from the existing diary; study-guide Markdown downloaded through the browser |
| Collection isolation | Passed | A sample Learning report excluded Personal conversations and unassigned personal notes |
| Snippet persistence | Passed | Fenced code detected; kept/custom excerpts saved through the browser and refreshed immediately; JSON round-trip and source deletion covered by tests |
| Prompt/model comparison | Passed | Two recorded model variants rendered side by side with prompt/reply differences |
| Usage availability | Passed | Unknown fields remained Unknown; samples excluded; explicit zero, partial field reporting, and older metadata migration covered by tests |
| MCP process | Passed | A real stdio subprocess restricted recent-memory output to its configured collection; paged original reads and scope-escape rejection covered by tests |
| CLI reports | Passed | Collection-scoped study-guide export contained selected Q&A and excluded personal context |
| Responsive layout | Passed in Chromium preview | No horizontal page overflow at observed phone (325×703), tablet (853×750), and desktop (1440×900) CSS viewports; new mobile form controls use 16px text |
| Optional writing model | Configuration/error path verified | Missing model produced an actionable message; generated-report sampling and source coverage tested with a mocked local service |

The complete capture-enabled suite passed 77 tests, including real local HTTPS interception, and both frontend JavaScript files passed syntax checks. New tests cover recurrence counts, scope boundaries, report formats, handoff limits, snippet backup/restore, comparisons, per-field usage, gateway system/instructions capture and redaction, and launcher upgrade/home selection.

One Windows rejection-path test exposed a connection-close race with unread POST bytes. Rejected bodies are now discarded within bounded size/time limits before the denial response, without parsing or acting on them. The regression suite passed after the fix.

Browser write tests used an isolated sample diary on a separate port; no sample records were inserted into the real diary. Screenshots and generated reports remain in ignored local storage. The Mac/Safari and real writing-model boundaries stated above still apply. GitHub Actions are configured to syntax-check both frontend scripts.


## Additional website adapters — 2026-10-31

The capture-enabled suite passes **104 tests**, including the existing real local HTTPS interception test expanded to five HTTP website formats. Both frontend scripts pass Node syntax checks.

Live Chrome verification on this PC confirmed:

- Meta AI: submitted prompt and complete answer through DGW binary WebSocket frames, with the real conversation UUID.
- Grok: submitted user item inside `response.create`, message-gateway text chunks, correct chat ID, and matching history repair. Empty `output_text.done` does not erase streamed text.
- Gemini: submitted prompt through the newer dedicated WebChannel host, full protobuf answer snapshot and terminal marker, stable reply-ID matching, and correct source chat link. Frame counters are not used as turn IDs.

Protocol fixtures cover fragmentation, malformed inputs, response byte preservation, privacy of diagnostics, distinct chat/channel isolation, and unsupported/partial outcomes. Only supported answer fields are extracted; reasoning and tool payloads are excluded. No provider credentials are copied into fixtures or documentation.

These checks verify the observed Chrome website sessions. Physical macOS/Safari capture, native Gemini/Grok/Meta apps, embedded AI inside social or messaging apps, voice, and image/file contents were not verified by this change. New adapters remain experimental because private website protocols can change. See [capture coverage](CAPTURE-COVERAGE.md).
