# Security policy

Wirebrain 0.1 is an experimental single-user local tool, not a hardened multi-user service. Keep its HTTP listeners on loopback. The database is plaintext and may contain sensitive conversations even after best-effort redaction.

Do not post API keys, real chat exports, or exploit details exposing private information in a public issue. If this repository is published on GitHub, use its private vulnerability reporting feature when enabled; otherwise ask the maintainer for a private reporting channel without including sensitive details.

Security-relevant boundaries: upstream destinations are fixed, authentication headers are not persisted, dashboard requests validate Host/Origin, frontend text uses textContent, and MCP exposes read-only search. Regex secret matching is not a data-loss prevention guarantee. Local processes running under your account remain trusted.

Optional HTTPS capture uses mitmproxy and a local CA private key. Enabling `--install-ca` expands the current Windows user's certificate trust; enabling `--system-proxy` changes their proxy settings until capture stops. HTTPS decryption is restricted to the adapter's three allowlisted AI domains. Never share the CA private key or enable public access to the interception listener. Full HTTP flows and authentication headers are not written to disk. Upstream certificate verification remains enabled. See [capture setup and rollback](docs/HTTPS_CAPTURE.md).
