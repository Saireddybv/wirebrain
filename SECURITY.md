# Security policy

Wirebrain 0.1 is an experimental single-user local tool, not a hardened multi-user service. Keep its HTTP listeners on loopback. The database is plaintext and may contain sensitive conversations even after best-effort redaction.

Do not post API keys, real chat exports, or exploit details exposing private information in a public issue. Use the private reporting channel linked below.

Security-relevant boundaries: upstream destinations are fixed, authentication headers are not persisted, dashboard requests validate Host/Origin, frontend text uses textContent, and MCP exposes read-only memory tools. Regex secret matching is not a data-loss prevention guarantee. Local processes running under your account remain trusted.

Optional HTTPS capture uses mitmproxy and a local CA private key. Enabling `--install-ca` expands local certificate trust on supported operating systems; enabling `--system-proxy` changes their proxy settings until capture stops. HTTPS decryption is restricted to the adapter's explicitly allowlisted AI hosts. Never share the CA private key or enable public access to the interception listener. Full HTTP flows and authentication headers are not written to disk. Upstream certificate verification remains enabled. See [capture setup and rollback](docs/HTTPS_CAPTURE.md).

## Report a vulnerability

Use [GitHub private vulnerability reporting](https://github.com/Saireddybv/wirebrain/security/advisories/new). Include the affected version, impact, and a minimal synthetic reproduction. Do not open a public issue with exploit details, account data, private conversations, or credentials. Coordinate disclosure with the maintainer; response times are best effort while the project has a sole maintainer.

The project is pre-1.0. Security fixes target the latest development version; older versions do not have a separate maintenance commitment. Update to the latest reviewed release or commit when a fix is available.

## HTTP MCP and optional writing backends

The authenticated MCP listener is separate from the diary and capture ports. It binds to loopback and may be placed behind a trusted HTTPS tunnel using the configured public origin. Keep the diary approval API, interception proxy, and developer API gateway private. An entered public address does not create a tunnel or establish public compatibility.

HTTP MCP uses OAuth code flow with S256 PKCE, exact registered redirects, resource-bound hashed tokens, collection-scoped grants, local approval, and revocation. A client name is self-reported; compare pairing codes and redirect destinations before approving. This single-owner authorization implementation is experimental, not a hardened multi-user identity service. Local processes under the owner's account remain trusted. See [HTTP MCP setup](docs/REMOTE_MCP.md).

The optional ChatGPT sign-in testing backend sends selected evidence to OpenAI through an existing Codex CLI login. MCP clients can likewise send retrieved context to their providers. These are explicit alternatives to local Ollama inference, not guarantees that all processing stays on-device. Do not share authorization databases, model credentials, local CA keys, or diary exports.
