# Reflect

Reflect provides an overview, a study guide, an AI-use map, a searchable macro library, memory suggestions, and the diary's rounded conversation cards. Suggestions are reviewed in Reflect rather than the Memory page.

Choose a period, app, and collection. The period ends on the date selected in the sidebar calendar. The tools support up to 2,000 captured moments per scan and a maximum one-year explicit date range; narrow the selection if a larger archive exceeds this limit. The Conversations tab shows the selected calendar day's conversations with the same app and collection filters.

## Study guide

Repeated terms are counted once per explanation or troubleshooting prompt. A topic needs at least two qualifying prompts before it appears. Greetings, labeled tests, and demo data are excluded. Repetition suggests something to revisit; it does not establish a knowledge gap or inability.

Create a guide for a recurring topic. The default guide needs no model: it supplies an explain-in-your-own-words exercise, a small example task, a self-check, and excerpts from original sources. Optional AI drafting uses the configured writing backend with up to eight selected source conversations. A ChatGPT testing backend sends those excerpts to OpenAI; local Ollama keeps generation local. Captured AI answers can be wrong, so the guide retains evidence for checking.

## AI-use map

The map groups prompt wording into learning/troubleshooting, routine formatting, writing/building, decision support, personal communication, research, and other/unclear requests. Each bar shows a count and percentage of analyzed prompts, with source examples and an optional reflection question.

These are transparent heuristics, not a validated psychological measure. They do not measure time spent, cognitive dependency, personal agency, or loss of independence. A request for a draft or advice is not evidence that someone surrendered a decision. Open the original prompts when a label seems wrong.

## Macro library

Wirebrain automatically saves conservative structured-text candidates: multi-section or placeholder-based prompts, email drafts with a Subject line and recognizable template structure, and workflows containing at least three numbered or checklist steps. Completed chats are scanned in the background (the 100 most recent moments each minute) and when you open or refresh Reflect (up to the selected range's 2,000 moments).

Templates retain their exact source text and a link to the conversation. Structural matching does not prove quality or correctness. Review before reusing. You can search, read, copy, download, or remove templates. No template, prompt, command, or workflow is executed, and no email is sent. Recognized secrets and redacted content are excluded.

The library reuses the local snippet store so templates are included in diary JSON backups. Removing an extracted macro also stores a content hash to stop the same template being automatically added again. Those markers survive backup/restore; an older backup does not override a current removal. Editing a source prompt, reply, or collection invalidates automatic templates derived from it. Deleting a conversation removes its templates. Manually saved ordinary code snippets keep their existing behavior.

## Memory suggestions

Possible personal facts appear under Suggestions, filtered to the selected period, app, and collection. Approve, edit, or dismiss them there. Only reviewed facts and automatically extracted discussion topics enter reusable Memory; unreviewed personal facts are excluded from memory overviews and recall. Source quotes and links remain available.
