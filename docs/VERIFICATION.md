# Verification

## Latest local results

Validated on Windows with Python 3.11 and the optional capture/search dependencies:

- All 58 tests passed, including the real local HTTPS interception test.
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
```

CI defines core tests on Linux, Windows, and macOS, a Windows HTTPS capture job, and combined capture/search runtime import checks on all three platforms. Configured CI jobs are not evidence of a completed remote run.
