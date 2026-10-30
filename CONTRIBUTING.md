# Contributing to Wirebrain

Start with a small issue describing the user problem and expected behavior. For changes, install the checkout with `python -m pip install -e .` and run `python -m unittest discover -s tests -v` plus `node --check wirebrain/static/app.js`.

Keep runtime dependencies minimal, data local by default, and credentials out of logs, fixtures, and exports. Never introduce certificate installation, system proxy changes, external reflection calls, or shell-profile mutations without an explicit opt-in design.

Provider adapters should preserve forwarded response bytes and index only supported text fields. Cover new parsing behavior with synthetic provider fixtures and a local HTTP integration test. Do not require real accounts in CI.

In a pull request, explain the user-visible change, show how to reproduce it, and include validation results. Update the README when capture support or privacy behavior changes. Dashboard contributions should preserve keyboard navigation, small-screen layouts, and safe rendering of untrusted conversation text.
