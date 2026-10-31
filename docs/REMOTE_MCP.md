# Connect assistants over HTTP MCP

Wirebrain supports local stdio MCP and authenticated Streamable HTTP MCP using protocol version `2025-06-18`. Both expose the same eight read-only memory tools and database. HTTP lets compatible clients share one running server. A web/cloud assistant additionally needs a reachable HTTPS endpoint and support for this OAuth flow; entering a URL does not connect or publish anything by itself.

## Start locally

1. Start the diary normally, then open **Tools → Continue & connect → Remote MCP**.
2. Keep port **3334** and leave the HTTPS address empty. Click **Start / apply**.
3. For an HTTP coding client, open **Connect an HTTP coding client with a token**. Select its collection in the main collection filter, name the connection, and create its configuration.
4. Copy that configuration into a client supporting HTTP MCP and bearer headers. The token is shown once, lasts 30 days, and should be kept private. Revoke it in **Connected assistants** when no longer needed.

The endpoint is `http://127.0.0.1:3334/mcp`. The MCP server binds only to `127.0.0.1`; unauthenticated memory requests are rejected. Local stdio clients can continue using their existing command configuration without HTTP tokens.

**Stop MCP** stops HTTP access without stopping the diary, recorder, or local stdio clients. Connections remain configured until revoked or expired. Once enabled, HTTP MCP starts again when the diary restarts; explicitly stopping it disables that automatic start.

The command `wirebrain --home /absolute/path/to/data mcp-http --port 3334` starts the diary with HTTP MCP enabled. Use the Tools controls when the diary is already running, rather than starting a duplicate instance. The CLI and UI use the same configuration.

## Add HTTPS later

1. Configure a trusted HTTPS reverse proxy or tunnel to forward to **`http://127.0.0.1:3334`**. It must forward `/mcp`, `/oauth/*`, and `/.well-known/*`. Use an origin dedicated to Wirebrain MCP, without a path prefix.
2. Keep the diary/dashboard port **3333 private**. The HTTP MCP listener does not serve the diary or local approval controls.
3. Enter the public origin, for example `https://memory.example.com`, in **Public HTTPS address**, then **Start / apply**. Copy the displayed `https://memory.example.com/mcp` URL.
4. Add that MCP URL to the assistant using OAuth. Client support and account eligibility vary. Wirebrain advertises authorization/resource metadata and dynamic client registration.
5. During sign-in, the browser shows a pairing code. On the computer running Wirebrain, open **Tools → Remote MCP → Refresh connections**. Match the code and redirect destination, choose a collection, refresh if needed, and approve. A client name is self-reported, not verified identity.
6. The sign-in page continues automatically after approval. Ask the assistant: “Find my Claude conversation from the last hour, read the relevant turns, and continue.” It decides when to call tools; connecting alone does not automatically inject the archive into every prompt.

Wirebrain does not create a tunnel, register a domain, or test public reachability when an address is entered. The computer, diary/MCP process, and tunnel must stay running. Changing the public address changes the token audience; reconnect clients for the new address.

Reverse proxies must preserve either the configured public Host or the loopback Host, and preserve Authorization headers. Wirebrain validates Host and any supplied Origin; unrecognized browser origins are rejected. It does not trust arbitrary forwarded headers to construct OAuth URLs. HTTPS termination must be on the trusted tunnel/proxy, never expose an unauthenticated proxy to the diary.

## Authorization and limits

- OAuth authorization code flow with mandatory S256 PKCE, exact registered redirects, resource audience binding, and `memory:read` scope. Public clients use `token_endpoint_auth_method: none`.
- Requests expire after five minutes. One-use codes expire after 60 seconds. OAuth access tokens last one hour; rotating refresh tokens and grants last up to 30 days. Reauthorization is needed after grant expiry.
- Tokens and authorization codes are persisted as SHA-256 hashes in `mcp-access.sqlite3`, separate from conversation exports. The HTTP configuration and grant metadata live there too. Do not publish or share this database. Backups of chats do not transfer authorization grants.
- A grant has one fixed collection or all collections. Tool arguments cannot broaden it. Revoking the grant immediately invalidates its access/refresh tokens on subsequent requests.
- HTTP uses JSON responses; notifications receive HTTP 202. GET streams are not offered (405). Clients must accept both JSON and SSE as required by Streamable HTTP. No legacy HTTP+SSE endpoint is supplied.
- Requests are bounded to 1 MB and 24 concurrent handlers. No access/request/body logs are written by this listener. Authorization metadata and registration are public; memory reads require a token.
- Approval is authorized by access to the trusted local diary on your computer. This is a single-owner local product, not a multi-user identity server. Do not expose the diary approval API to a network.

Only captured conversations and derived memory are available. Read-only tools cannot edit memory, run commands, or send messages. Retrieved content may be sent to the assistant's AI provider, according to that client's permissions. Long histories use search, bounded excerpts and pagination; the entire archive is not sent on every question.

Protocol references: [Streamable HTTP](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports), [MCP authorization](https://modelcontextprotocol.io/specification/2025-06-18/basic/authorization).
