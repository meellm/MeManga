# Security Policy

## Supported versions

Only the latest release receives security fixes. Fixes are made on the
`main` branch and ship in the next release. Older releases and other
branches are unsupported.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Email `info.meellm@gmail.com` with:
- A short description of the issue.
- Steps to reproduce (URL, payload, manga config snippet, etc.).
- The MeManga version and the OS you're running on. The command line
  prints the version with `memanga --version` (or
  `python -m memanga --version`); the desktop app shows it in its window
  title and on the Settings page.

Remove email addresses, app passwords and other personal details from
any config output, logs or screenshots you send. `memanga config show`
already hides the app password and email addresses.

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
