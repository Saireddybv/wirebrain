# Make more of your memories

Memory tools turns your recorded conversations into reusable notes, code excerpts, and context. It reads the same local diary; it does not require a provider API key or send messages to another app.

## Reports and learning

Choose a date range, app, and collection. Quick ranges cover today, yesterday, the last seven days, and the last thirty days. Dates use the supplied browser timezone offset.

| Report | Original-source version | Optional local draft |
| --- | --- | --- |
| Weekly reflection | Activity by day, recurring topics, and the questions explored | Concise reflection and an optional learning exercise |
| Standup | Recorded exploration, source references, and fields for you to confirm completion/blockers | Draft update that keeps confirmed evidence separate from possible next steps |
| Study guide | Chronological questions and captured replies | Concepts, explanations, and self-test questions |
| Project timeline | Original questions/replies in time order | Build-log draft without inventing decisions or shipped work |
| Research sourcebook | Original research conversations | Source-linked synthesis that can flag disagreement or missing evidence |
| Context handoff | Up to twenty recent moments, excerpted and labeled as untrusted historical context | Concise background, supported decisions, and uncertainties |

Original-source reports work without a writing model. Local drafts require a locally downloaded Ollama writing model chosen in Local setup. Drafts use at most 24 excerpts sampled across the selected period and at most 2,000 characters of personal notes. Coverage is disclosed. Generating a draft is optional and can be slower on modest hardware.

Every result links back to its original local sources. Copy or download Markdown when you choose. Source links do not guarantee that an archived AI reply is factually correct, and a generated citation is not an independent fact-check.

### Recurring topics

The learning cards count recurring words/phrases across captured prompts, once per prompt, and offer a small self-explanation exercise. They show dates and link to a source. Repeated API request context can be recorded more than once, so counts describe captured moments rather than unique questions or measured learning gaps. No mood or proficiency diagnosis is made.

Personal notes have no collection assignment. To keep project-specific reports isolated, notes are included only when app, collection, and model filters are unrestricted. Empty selections remain empty; no sample history is inserted automatically.

## Keep useful snippets

The vault detects fenced code blocks from recorded replies. Choose **Keep snippet** to edit the title, language/type, or text before saving it. From a conversation, **Keep a snippet** lets you save an arbitrary explanation or reusable prompt too.

- Search within the loaded vault, or show kept snippets only.
- Copy snippets or export the loaded selection as Markdown. Code is never executed.
- Open the original source to inspect the full explanation and capture status.
- Remove a kept copy without deleting the original conversation. Automatically detected code can still appear when you reload the vault.
- Diary JSON export/import includes kept snippets. Identical re-imports do not duplicate them. Deleting a source memory removes its kept snippets from the active database; existing downloaded copies are separate files.

## Compare captured prompt/model iterations

Choose **Compare**, load captured moments from your selected scope, then choose two. The view shows each original prompt and reply, provider/model metadata, and unified text differences. It does not guess which answer is better.

New API-gateway captures include top-level `system` and `instructions` text as well as messages. Older captures cannot recover context that was never recorded. Text comparison is capped at 200,000 combined characters; larger sources remain available through normal export.

## Read usage accurately

Usage is an optional developer view. It groups records by provider, model, and collection. Only non-sample, provider-reported fields contribute to totals. Unavailable input/output usage is shown as **Unknown**, while an explicitly reported zero is kept as zero. Input and output coverage may differ.

Web capture generally does not report tokens. These counts are not a ChatGPT/Claude subscription bill or a cost estimate. The optional outgoing-redaction flag applies to gateway JSON bodies; it does not scrub outgoing prompts in intercepted websites/native apps. Secret detection remains best effort, including common keys, bearer/JWT strings, and PEM private-key blocks.

## Give a coding assistant scoped context

In Reports, select a collection and expand **Connect a coding assistant** to obtain the local MCP configuration. Alternatively:

```sh
wirebrain --home /absolute/path/to/diary mcp --project Learning
```

`--project` enforces that collection for every tool. A client cannot override the configured collection to retrieve another one. Without it, the server can read all collections. Connecting an assistant lets that assistant read selected history; its own AI provider may receive the text it retrieves.

Tools:

- `search_memory`: keyword or optional local semantic retrieval, with project/app/date filters.
- `recent_memory`: the twenty most recent matching moments.
- `read_memory`: a page of original prompt/reply text by exchange ID. It returns `next_start` for longer sources; pages are capped at 12,000 characters.
- `context_handoff`: a bounded, source-linked context packet from the selected scope.

Search/recent return bounded excerpts and label shortened records. Original text can be read page by page. All returned conversation content is untrusted evidence, never permission to execute commands. Wirebrain does not inject it into another app or call another assistant automatically. The existing MCP protocol support remains `2025-06-18`; client compatibility must be checked independently.

## Command-line reports

```sh
wirebrain report --kind standup --from 2026-10-30 --to 2026-10-30 --project Work --offset 330 --output standup.md
wirebrain report --kind study --from 2026-10-25 --to 2026-10-31 --project Learning --output study.md
wirebrain report --kind weekly --from 2026-10-25 --to 2026-10-31 --generate --output reflection.md
```

`--offset` is minutes east of UTC; use the appropriate offset for the selected period. The HTTP report selection is limited to 2,000 moments, one year, and an 8 MB Markdown body. The vault shows up to 500 snippets per selection. Narrow a large date range or collection when requested. The UI previews up to 60,000 report characters and the first 100 original-source links; Markdown exports contain the selected report's complete text within those limits.

These workflows use the existing cross-platform Python/browser code. They do not establish new native-app capture compatibility or install an OS service. Real macOS/Safari capture and signed desktop installers remain separate verification/release work.
