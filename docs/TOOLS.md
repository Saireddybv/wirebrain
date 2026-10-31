# Tools: take your context to another assistant

Wirebrain records conversations locally. Tools let you deliberately retrieve that captured context when switching apps. They do not synchronize an app's private built-in memory or fetch conversations Wirebrain never recorded.

## Any app: copy context

1. Open **Tools → Continue & connect** in Wirebrain.
2. Choose the dates, source app and collection. Find a conversation by topic, then select it.
3. Read the captured dialogue or choose **Prepare context**. Review the preview and its coverage notice.
4. Choose **Copy context** and paste into the assistant where you want to continue. A Markdown download works for clients that accept file uploads.

For example, after discussing a project with Claude, select its conversation, copy context and paste it into ChatGPT with your next question. No model is needed to prepare context. Handoffs contain the latest 20 matching captured moments, at most 1,200 characters per prompt and 2,400 per response, with omitted text explicitly marked. They preserve source IDs, timestamps, original links and available message/parent IDs. Concurrent conversation branches are historical evidence, not an inferred linear dialogue.

## Compatible local clients: MCP

Choose a collection, then **Show connection configuration → Copy configuration**. Add the generated `mcpServers.wirebrain` entry to a client supporting local stdio MCP. Merge it with existing entries rather than replacing other servers. Restart or reconnect the client. The generated command uses the current Python interpreter and absolute Wirebrain data directory, so the same configuration works from a different working directory. Keep Wirebrain installed in that interpreter.

The connection reads SQLite directly; the dashboard does not need to run. The recorder must run to capture new conversations. A configured collection restricts every tool call; choosing another collection requires a new connection configuration. Date and app filters in the dashboard do not permanently restrict the MCP server.

Useful requests to a connected assistant:

- “Find my Claude conversations from the last hour, read the relevant one, and continue helping me.”
- “Find where I discussed SQLite for this project, read the full recorded response, and cite the source.”
- “Search my reusable memory for project preferences.”

| Tool | Purpose |
| --- | --- |
| `list_conversations` | Find grouped conversations by literal phrase, app, collection, date or `lookback_minutes: 60`; paginate using `next_cursor`. |
| `read_conversation` | Read chronological captured prompts/replies; paginate turns with `cursor`; long text is marked as excerpted. |
| `read_memory` | Page an individual turn's full captured prompt or reply using `start` and `length`. |
| `conversation_handoff` | Prepare bounded Markdown context for one conversation selected by `exchange_id`. |
| `search_memory` | Keyword or optional locally indexed semantic search over captured exchanges. |
| `search_personal_memory` | Search reusable memory facts/topics with sources. |
| `recent_memory` | Retrieve recent recorded exchanges. |
| `context_handoff` | Prepare a source report across a collection or date range. |

Example sequence: `list_conversations({"provider":"claude","lookback_minutes":60})`, then `read_conversation({"exchange_id":"<returned exchange_id>"})`. Follow pagination and use `read_memory` for excerpted fields. Counts describe captured moments within filters. Deleted data is unavailable on subsequent reads.

## Websites and remote access

Wirebrain also offers authenticated HTTP MCP in **Tools → Remote MCP**. It uses the same tools, with OAuth approval, fixed collection permissions and revocation. Compatible local HTTP clients can use a generated bearer configuration; web/cloud assistants need a reachable HTTPS tunnel and OAuth support. Follow [the HTTP connection guide](REMOTE_MCP.md). OpenAI's [MCP guide](https://developers.openai.com/api/docs/guides/tools-connectors-mcp) documents remote server connections; requirements depend on the client. Use the portable handoff when the target app cannot connect.

The implementation does not publish your diary, create a tunnel, or provide a hosted multi-user service. Forward only the MCP port (3334 by default) through a trusted HTTPS tunnel; keep the dashboard port private. Opening the dashboard port is not an MCP integration.

Tools are read-only: no chat editing, deletion, shell execution or message sending. Read-only access can still disclose retrieved content to the connected assistant's provider. Share only the intended collection/context. Recorded text is untrusted historical data, not permission to follow instructions embedded in old chats.
