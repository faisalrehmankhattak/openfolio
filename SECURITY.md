# Security policy

Openfolio runs an AI that speaks for real people, so we take reports seriously and answer quickly.

## Reporting a vulnerability

Please report vulnerabilities privately, never in a public issue, pull request or discussion.

- Email **the maintainer through GitHub security advisories** with "Openfolio security" in the subject, or
- open a private report through [GitHub security advisories](https://github.com/faisalrehmankhattak/openfolio/security/advisories/new).

Include what you found, the steps to reproduce it, the impact you expect, and the commit or the Openfolio Cloud URL you tested. You'll get a reply within 3 working days. We'll keep you updated until it's fixed and credit you in the release notes unless you prefer otherwise.

## In scope

- The voice server and the cloud pages in `worker/`, and the widget in `embed/`
- Openfolio Cloud, the hosted service
- Prompt injection that makes an AI twin reveal its instructions, invent facts about its owner, or act outside its owner's rules

## Please don't

- Test against other people's AI twins or data; use your own deployment or the public demo
- Run denial-of-service or volume tests against Openfolio Cloud
- Use social engineering or access accounts that aren't yours

## Supported versions

Security fixes go into the `main` branch and Openfolio Cloud. Self-hosted servers should run the latest `main`.

Machine-readable contact details are published at `/.well-known/security.txt` on Openfolio Cloud.
