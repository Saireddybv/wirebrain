# Personal memory

Memory has two tabs: **My memory** shows automatically extracted topics and reviewed facts together, and **Conversations** retains the original archive. Personal facts awaiting review appear in **Reflect → Suggestions**. The AI app buttons filter the sources; they do not read any provider's private saved-memory store. You do not need to add memories manually.

## Combined and per-app memory

In My memory, **Wirebrain** shows the combined reusable memory across captured apps. Selecting ChatGPT, Claude, Gemini, Grok, or Meta AI shows that app's consolidated memory. The overview cites its supporting memories and can open their original conversations. No separate copy of each fact is created for each view.

An overview uses personal-scope memory unless you select a collection, in which case it uses only that exact collection. Unreviewed personal facts are excluded. Empty app views stay empty rather than inventing a profile. The original Conversations tab remains available even when a chat contains no useful reusable memory.

With automatic processing and a writing backend enabled, an overview is synthesized when you open that view and only regenerated after its inputs or backend change. Cached overviews are removed when underlying memories are edited or forgotten, and in-flight generation rechecks its inputs before saving. A failed synthesis backs off for five minutes while original memories remain visible. Overview drafts are limited to 32 recent reusable memories, with coverage shown when the scope contains more; the full memory cards remain searchable. Derived overviews are regenerated after restoring a diary backup rather than copied into the backup.

## Start using it

Memories appear from recorded conversations after background processing. You can edit or forget them. Set a collection to restrict a fact to that project; leave it blank for personal memory. Saving an edit approves it. Every extracted memory includes the exact supporting human quote and a link to the original conversation. Research questions may yield topic memories labeled as questions you explored, not claims about your identity. These topic memories are usable automatically; inferred personal facts require review before recall.

For local extraction, install Ollama and select a **locally downloaded writing model** in Local setup. Alternatively, explicitly choose [ChatGPT sign-in testing mode](CHATGPT_TEST_GATEWAY.md), which sends selected excerpts to OpenAI through your authenticated Codex CLI. Click **Refresh memories** for a bounded pass, or enable **Build memories automatically**. Background extraction is off until enabled. The existing embedding setting enables optional local meaning-based recall. Wirebrain does not silently download a writing model or switch providers.

## How extraction works

- A SQLite queue tracks inserted messages and changes to their human prompt, collection, or capture status. A completed input is fingerprinted after processing; unchanged inputs are skipped, including across restarts. Changes only to the AI answer do not trigger another extraction.
- Each pass handles at most two completed messages from chats idle for at least two minutes. Streaming chats and labeled demo data are excluded. The worker checks once a minute. A failed pass is shown in the UI and automatic retries back off for ten minutes; a manual run can retry sooner.
- Only the human prompt is sent for extraction, capped at its first 5,000 characters. AI replies are excluded. The local model returns schema-constrained JSON with at most four facts and exact evidence quotes. Wirebrain validates the result again before saving.
- The model is instructed to skip questions, hypothetical scenarios, pasted third-party content, sensitive information, secrets, and temporary chatter. Quote validation cannot prove that a claim follows from its source. Suggestions require human approval before recall.
- Exact normalized duplicates in the same scope share a fact with multiple sources. Paraphrases and conflicting preferences are not silently merged or resolved by the model. Edit the existing approved fact, or forget the outdated one, when reviewing a change.

## Scope and recall

Ordinary Inbox and Web conversations produce personal-scope suggestions. A named collection produces suggestions restricted to that exact collection. You may explicitly change a fact's scope in its editor.

The Memory page can browse all scopes because it belongs to the local owner. **Ask my memories from the fact tabs** uses approved facts in the exact selected collection, or personal-scope facts when no collection is selected, plus only their linked conversation evidence. It does not mix other project facts into an answer. The Conversations tab retains the existing archive search behavior. Choosing a provider requires matching source evidence, so manually added facts without an AI source appear under All.

Fact recall combines word matches and cached local embedding scores when available, and returns at most eight facts. Semantic candidate selection is bounded to 2,000 recent approved facts per scope; exact word matches can find older facts. The page shows up to 200 results. Generated answers cite reviewed facts as `[M1]` and original conversations as `[1]`. Memory is retrieved context, not a modification of model weights, and quoted content is never treated as instructions to execute.

The read-only MCP tool `search_personal_memory` exposes the same reviewed facts. A collection-restricted MCP server cannot request another scope. Connecting an assistant may send retrieved information to that assistant's provider; the connection is explicit. Wirebrain does not inject memory into normal ChatGPT or Claude website requests.

## Editing, forgetting, and source changes

Edits preserve the previous text and scope for inspection and invalidate cached embeddings. The local model never overwrites an approved fact. Forgetting deletes its text, source links, edit history, and vector, and keeps only a content hash plus supporting-message exclusion IDs. Those messages cannot generate new suggestions again, including after a restart or a prompt edit. Exact forgotten fact hashes are blocked from automatic recreation; a genuinely new message paraphrasing an old fact can still produce a new suggestion for review. An explicit user save may recreate a forgotten fact.

Deleting or changing the human text or collection of a source conservatively removes every derived fact linked to it, including its stored history and vectors. Extraction and indexing recheck the source/fact inside their write transaction so in-flight work cannot resurrect deleted data. Original conversations are retained when you forget a fact.

Diary JSON exports include approved facts, suggestions, evidence, edit history, and forgetting markers. Import validates these before writing and remaps source IDs. Import does not enable background processing or download models; local forgetting decisions win over older backups. Keep exported backups private, just like the plaintext local SQLite archive.
