# Prompt development

Wirebrain's AI prompts live in `wirebrain/prompts/`, grouped by feature. They are bundled in source distributions and wheels and loaded through `wirebrain.prompting`. There is no YAML parser or template-engine dependency.

## Layout

```text
wirebrain/
  prompting.py
  prompts/
    catalog.json
    memory/
      extract.md
      extract.schema.json
      overview.md
      overview.schema.json
    recall/
      system.md
      context.md
      question.md
    reflect/
      daily.md
      study.md
    reports/
      weekly.md
      standup.md
      study.md
      timeline.md
      research.md
      handoff.md
      handoff_recipient.md
    gateway/
      text_only.md
      connection_test.md
    mcp/
      context.md
      tools/*.md
```

`catalog.json` is the registry. Each entry records a stable ID, integer version, logical role, relative file, declared variables, and optional JSON schema. Metadata is not included in the model prompt.

```python
from wirebrain.prompting import render_prompt, load_schema, prompt_info

instruction = render_prompt('reflect.study', topics='SQLite indexing')
schema = load_schema('memory.extract')
version = prompt_info('reflect.study')['version']
```

## Editing a prompt

1. Find its feature folder and stable ID in the catalog.
2. Edit the Markdown instructions. Keep source boundaries, uncertainty, citations, and privacy constraints explicit.
3. Bump its catalog version when changing behavior. Add or change declared variables alongside the calling code. Keep output schemas and Python validation consistent.
4. Run `python -m unittest discover -s tests -v`. Tests cover the catalog, substitution, extraction, citations, isolation, source deletion, gateway behavior, and reports.
5. Review the prompt change through the normal pull-request workflow. Use synthetic examples and include the intended behavior change and relevant test evidence.

Use `${name}` placeholders. Literal dollars in a template use `$$`; JSON braces and ordinary Markdown are literal. Only declared variables are accepted, missing or extra variables fail clearly, and values must be strings. Variables are substituted once, so chat text containing `$HOME`, `${schema}`, or braces remains text. The loader does not evaluate code, expand environment variables, include other files, or accept paths supplied by conversations.

## What stays in Python

Python retains provider calls, scope checks, extraction limits, source validation, persistence, schemas for HTTP/MCP arguments, and ordinary UI/report copy. Markdown holds model instructions and receiving-assistant guidance. Structured AI response schemas are JSON beside the associated prompts. Tests and synthetic test messages remain test code.

## Reloading and caches

Prompts are package resources cached for the life of a server process. Restart Wirebrain after changing them. There is no remote prompt fetch, dashboard prompt editor, or per-conversation override.

Consolidated-memory fingerprints include the overview prompt's content hash, so editing it and restarting invalidates the cached overview. It will be rebuilt using the configured writing backend when needed. An extraction prompt edit affects new or changed queued inputs; it does not silently reprocess the entire archive or spend quota on old chats.

No private conversations, tokens, OAuth credentials, account data, or local generated memories belong in prompt files. For ChatGPT testing mode, selected runtime excerpts still go to OpenAI as described in [the gateway guide](CHATGPT_TEST_GATEWAY.md).
