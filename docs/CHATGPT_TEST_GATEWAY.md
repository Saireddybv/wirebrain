# ChatGPT sign-in testing gateway

Wirebrain can use an existing **Codex CLI ChatGPT sign-in** as an optional writing backend. This is separate from local Ollama inference. It sends selected prompts, evidence excerpts, and questions to OpenAI and uses the account's Codex allowance. Plan access, availability, and limits still apply; there is no API-key fallback.

## Use it

1. Install the official Codex CLI, then run `codex login` and choose ChatGPT sign-in. Complete the browser login yourself. If you are already signed in, no additional login is needed.
2. In Wirebrain's Local setup, choose **ChatGPT sign-in · testing** as the writing backend and save. Embeddings can remain local.
3. Use **Test ChatGPT connection** to verify a reply. In Memory, enable **Build memories automatically**, or use Refresh memories for a bounded pass.

Wirebrain invokes `codex exec` through stdin with structured output schemas, an ephemeral session, a temporary empty working directory, a read-only sandbox, disabled tools/integrations, and ignored user configuration. It does not copy OAuth tokens, inspect browser cookies, scrape ChatGPT's website, or expose your login through an HTTP proxy. Codex manages its own credential storage and renewal. Wirebrain checks that the credential is ChatGPT sign-in rather than API-key login, strips API-key environment variables from the child process, rejects tool outputs, and requires a completed inference turn.

The integration's API routes remain on the guarded loopback dashboard. The connection-test route accepts only a fixed hello test; memory extraction uses the existing bounded source pipeline. Prompts travel through stdin and replies stay in process memory rather than temporary session files. Approved or automatically generated topic memories are persisted in the local SQLite database with evidence.

The implementation uses the CLI's default accessible model, rather than guessing account entitlements from a catalog. A successful actual response verifies access. Sign out, switch the writing backend back to Ollama, or turn off automatic memory processing to stop subsequent cloud extraction. An in-flight request may finish.

OpenClaw also documents ChatGPT/Codex subscription authentication. This adapter is a Wirebrain testing integration with the official Codex CLI, not an OpenClaw dependency or an implementation of OpenClaw's gateway protocol. See [OpenClaw's setup](https://docs.openclaw.ai/providers/openai/setup) and [OpenAI's non-interactive mode documentation](https://learn.chatgpt.com/docs/non-interactive-mode).
