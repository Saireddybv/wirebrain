# Website capture coverage

Wirebrain captures supported text messages passively from your existing session.
It does not authenticate to providers, replay requests, or need their API keys.
The UI must not describe an experimental adapter as verified for every account.

| Website | Submitted text | Reply framing | Verification |
| --- | --- | --- | --- |
| ChatGPT | Conversation POST | SSE snapshots and patches | Local TLS tests and user-confirmed Chrome use |
| Claude | Completion POST | SSE text blocks and legacy completions | Local TLS tests and user-confirmed app/browser use |
| Gemini | StreamGenerate form, positional `f.req` | XSSI-prefixed JSON frames, cumulative candidate text | Experimental: synthetic protocol and local TLS tests |
| Grok website, HTTP | New conversation and follow-up POST | JSON lines or SSE, tokens and final model response | Synthetic protocol and local TLS tests |
| Grok website, message gateway | Submitted user item in response.create; session-to-chat mapping | JSON WebSocket text chunks and final text; matching history repair | Local protocol tests and live Chrome full prompt/reply verified |
| Meta AI website, HTTP transport | Explicit `useAbraSendMessageMutation` only | GraphQL bot-response snapshots | Experimental: synthetic protocol and local TLS tests |
| Meta AI website, binary DGW WebSocket | Protobuf request prompt fields | Protobuf response, bounded UI snapshots and patches | Local protocol tests and live Chrome prompt/full reply verified |
| Gemini newer WebChannel | Submitted prompt protobuf, scoped to a channel | Length-framed JSON/base64 protobuf; answer snapshots and terminal marker | Local protocol tests and live Chrome full prompt/reply verified |

## Boundaries

- These new adapters do not cover AI embedded in WhatsApp, Facebook, Instagram, or X.
- Image/file contents, voice, alternate answer branches, and hidden thinking are not captured by these text adapters.
- A running proxy is readiness, not proof that a browser routed a conversation through it.
- Partial replies stay marked interrupted; unknown response MIME types stay unsupported.
- Existing ChatGPT history is used to repair uniquely matched captures, not automatically import uncaptured chats.
- Only the exact allowlisted hosts are decrypted. Adding `gemini.google.com` does not include Google accounts, Gmail, or other Google subdomains. Adding Meta AI does not include Facebook or Instagram.
- Model names remain unknown when the website uses opaque model selectors. Token counts remain unknown when absent.
- Meta conversation IDs are grouped. Canonical UUID conversations link to the observed `/prompt/<id>` website route.
- Binary WebSocket bytes are forwarded unchanged; requests are never replayed. Only the answer UI sections are rendered, excluding reasoning and tool instructions.

## Live check

With capture enabled, reload the website in your normal signed-in browser and send a short test prompt. Check the diary's date, app filter, full reply, and thread grouping. Test a second turn in the same chat and a separate chat. Do not count a synthetic fixture or a signed-out homepage fetch as live account verification.

## Protocol references

The passive parsers were implemented from published transport descriptions and source inspection; no provider credentials or authentication routines were imported.

- [Gemini web protocol description](https://github.com/etrnkz/gemini-unofficial-api/blob/main/docs/protocol.md)
- [Gemini request/response transport implementation](https://github.com/HanaokaYuzu/Gemini-API/blob/master/src/gemini_webapi/client.py)
- [Grok new and follow-up transport implementation](https://github.com/realasfngl/Grok-Api/blob/main/core/grok.py)
- [Meta HTTP/GraphQL transport implementation](https://github.com/Strvm/meta-ai-api/blob/main/src/meta_ai_api/main.py)
- [Meta binary DGW transport description](https://github.com/mir-ashiq/metaai-api/blob/main/src/metaai_api/parser.py)

## Automated checks

The suite includes exact-host and route checks, malformed-body rejection, arbitrary UTF-8 byte boundaries, cumulative snapshots, thinking exclusion, completion/partial/error states, secret redaction, thread links, unchanged response bytes, and synthetic exchanges through an actual local HTTPS interception proxy for all five HTTP adapters. No OS trust or proxy changes are made by the TLS integration test itself.

- [Current Meta DGW/protobuf field descriptions](https://github.com/myounis1996/metaai-reversed/blob/main/src/proto/ecto.js)
- [Gemini WebChannel rollout report](https://github.com/Sophomoresty/gemini-web2api/issues/110)
