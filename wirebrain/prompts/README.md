# Wirebrain prompt catalog

AI behavior is defined in Markdown files here. `catalog.json` registers each prompt's ID, version, role, variables, and optional output schema. Python supplies data and enforces application rules.

| Folder | Purpose |
| --- | --- |
| `memory/` | Extract facts and topics; consolidate whole and per-app memory |
| `recall/` | Answer questions using original conversations and reviewed memory |
| `reflect/` | Daily reflection and focused study guides |
| `reports/` | Weekly, standup, study, timeline, research, and handoff reports |
| `gateway/` | Text-only ChatGPT testing gateway and connection test |
| `mcp/` | Receiving-assistant guidance and read-only tool descriptions |

Use `${variable}` for declared variables. Escape a literal dollar sign as `$$` in a template. JSON braces and Markdown need no escaping. Inserted values are treated as data and substituted once; their dollar signs are not expanded again.

See [prompt development](../../docs/PROMPTS.md) from a source checkout. For the public guide, use [docs/PROMPTS.md on GitHub](https://github.com/Saireddybv/wirebrain/blob/main/docs/PROMPTS.md).
