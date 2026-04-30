# Security Notes

## Reporting

Please avoid filing public issues that include secrets, tokens, or exploitable details. Share sensitive findings privately with the maintainers.

## Current security posture

- `.env` files are intended to remain untracked
- weak or placeholder `SECRET_KEY` values are rejected at startup
- the direct email-only password reset flow is disabled by default
- debug-token UI routes are not part of the public release surface

## Deployment expectations

- rotate secrets before every public deployment
- restrict CORS to trusted frontend origins
- keep MongoDB off the public internet unless it is properly secured
- use verified reset tokens instead of direct password replacement flows
