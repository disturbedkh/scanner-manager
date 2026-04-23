# Security Policy

## Supported versions

Only the latest `0.9.x` alpha series is receiving security fixes.
Older pre-alpha builds are unsupported.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Use GitHub's private
[Security Advisories](https://github.com/disturbedkh/scanner-manager/security/advisories/new)
to submit a coordinated disclosure. Include:

- A description of the issue and the impact.
- Steps to reproduce.
- Your preferred disclosure timeline (defaults to 90 days).

We aim to acknowledge reports within 7 days.

## Scope

In scope:

- Arbitrary code execution / privilege escalation via malicious HPD
  files, RadioReference responses, installer downloads, or workspace
  manifests.
- Credential leakage from the `keyring`-backed RR account store.
- Accidental bundling of Uniden-copyrighted binaries in any published
  artifact.

Out of scope (but still feel free to file a normal issue):

- Cosmetic UI glitches.
- Rate-limiting / DoS via intentionally pathological user input (the
  app is local-only; denial-of-service on your own PC is not a
  security vulnerability).

## Installer manifest integrity

Scanner Manager downloads Uniden installers from URLs pinned in
`data/uniden_installers.json`. Each entry has a pinned SHA-256 that is
verified *before* the installer ever runs. If you suspect the manifest
itself has been tampered with (e.g. it references a file you believe
is malicious), please report it via the advisory process above.
