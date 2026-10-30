# Governance

Wirebrain is an MIT-licensed, community-driven project maintained by [@Saireddybv](https://github.com/Saireddybv). The maintainer is responsible for releases, security reports, project direction, and merging contributions.

## Decisions and contributions

Discuss larger changes in a public issue or Discussion before investing substantial effort. Explain the user need, alternatives, compatibility, and privacy implications. Small fixes can go straight to a PR. Decisions and their reasons should be recorded in the relevant issue or PR so contributors can follow them.

## Protected main branch

Changes require a pull request, passing `Required checks`, an up-to-date branch, resolved review conversations, and a squash merge. Force pushes and deletion of `main` are blocked. There are no configured rule bypass actors. GitHub administrators can still edit repository rules, so settings changes should be documented openly.

While there is one maintainer, external approval is optional so the maintainer can merge their own PRs. Other contributors' PRs are reviewed by the maintainer. CODEOWNERS requests the maintainer's review; it does not impose an additional approval requirement. Revisit mandatory independent review when more maintainers join.

## Releases and access

Release only reviewed changes from `main`, with a version and release notes describing behavior, compatibility, and known limitations. A merged PR does not by itself publish a package. Give collaborators only the access they need; grant broader access after sustained contributions and public discussion.

Security reports follow [SECURITY.md](SECURITY.md). Community participation follows [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
