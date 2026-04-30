# Contributing

## Workflow

1. Create a branch for each change.
2. Keep changes scoped and documented.
3. Run the validation commands before opening a pull request.

## Local validation

Backend:

```bash
python -m pytest backend/tests -q
python -m compileall backend
```

Frontend:

```bash
cd frontend
npm run type-check
npm run build
```

## Pull request expectations

- Describe the user-facing impact
- Note any environment variable or migration changes
- Include screenshots for frontend changes when relevant
- Call out risks, follow-up work, or limitations explicitly

## Security

- Never commit `.env` files or credentials
- Keep demo-only security bypasses disabled by default
- Avoid exposing debug endpoints or local tooling in production routes
