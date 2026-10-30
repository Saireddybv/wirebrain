# Contributing to Wirebrain

Thanks for helping make AI memory useful, private, and easy to run locally.

## Propose a change

Use an issue for a reproducible bug or a focused feature proposal. Use Discussions for questions and early ideas. Report vulnerabilities privately using [GitHub security advisories](https://github.com/Saireddybv/wirebrain/security/advisories/new).

Fork this repository, create a descriptive feature branch, and open a pull request against `main`. Keep each PR focused on one problem and explain the resulting behavior and how you checked it. Draft PRs are welcome for early feedback.

## Develop locally

Use Python 3.11 or newer and Node.js 22 or newer for JavaScript syntax checks:

```sh
python -m venv .venv
# Activate .venv using your operating system's activation command.
python -m pip install -e .
python -m unittest discover -s tests -v
node --check wirebrain/static/app.js
node --check wirebrain/static/workflows.js
```

For capture changes, install `python -m pip install -e ".[capture]"` and run the synthetic capture tests. For embedding changes, use `python -m pip install -e ".[capture,memory]"` and `python -m pip check`. Installing these extras does not require changing your system proxy or trusting a certificate.

Keep dependencies minimal and preserve offline operation where practical. Capture must remain explicit opt-in, with clear certificate and proxy controls. Add useful regression tests for behavior changes; use synthetic provider fixtures and local HTTP integration tests. CI must not sign into real AI accounts, change a system proxy, or require private conversations.

Never commit chat archives, cookies, authorization headers, tokens, local databases, certificates, private keys, or raw traffic dumps. Check screenshots and test fixtures for personal information before uploading them.

## Review and merge

All changes to `main` go through a PR, including maintainer changes. The required checks must pass against an up-to-date branch, and review conversations must be resolved. The repository uses squash merges and deletes merged feature branches automatically.

The current sole maintainer can merge their own PR after checks pass; another person's approval is optional. Contributor PRs receive maintainer review. See [GOVERNANCE.md](GOVERNANCE.md), [SECURITY.md](SECURITY.md), and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
