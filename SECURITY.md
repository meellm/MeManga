# Security Policy

## Supported versions

Only the latest release receives security fixes. Fixes are made on the
`main` branch and ship in the next release. Older releases and other
branches are unsupported.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Email `info.meellm@gmail.com` with:
- A short description of the issue.
- Steps to reproduce (URL, payload, only the config lines needed, etc.).
- The MeManga version and the OS you're running on. The desktop app shows
  the version in its window title and on the Settings page. With Docker,
  give the image tag. `memanga --version` (or
  `python -m memanga --version`) also prints it.

Send only the details needed. Do not send your whole `config.yaml`, which
can contain your app password. Remove email addresses, passwords, tokens,
user names in file paths and other personal details from any config
output, logs or screenshots.

`memanga config show` hides the app password and the part of an email
address before the `@`. It does not remove everything personal, so read the
output before you send it.

You'll get an acknowledgement within 72 hours. Once a fix lands we'll
coordinate disclosure timing with you and credit you in the release
notes (unless you'd rather stay anonymous).

## Scope

In scope:
- Code execution via crafted manga URLs, config files, or
  scraper-returned content.
- Credential leaks (config file, keyring, SMTP password, etc.).
- Network requests to unexpected hosts.
- Path-traversal or arbitrary-write bugs in the downloader.

Out of scope:
- Vulnerabilities in third-party scraper sites (we don't control them).
- Bugs in dependencies — please report those upstream (we'll pick up
  patched releases on the next dependency bump).
- Social engineering or physical-access scenarios.
