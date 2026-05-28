# Security Policy

## Supported versions

Only the latest minor release on the `main` branch receives security
fixes. Older versions are unsupported.

## Reporting a vulnerability

**Please do not open a public GitHub issue for security reports.**

Email `info.meellm@gmail.com` with:
- A short description of the issue.
- Steps to reproduce (URL, payload, manga config snippet, etc.).
- The MeManga version (`MeManga.exe --version` or
  `python -m memanga --version`) and the OS you're running on.

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
