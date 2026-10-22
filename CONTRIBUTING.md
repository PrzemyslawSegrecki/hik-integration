# Contributing

Thanks for helping! Bug reports from other doorbell models and firmware versions are especially valuable.

## Reporting a problem

Open an issue and include: doorbell model and firmware, how you run the app (Docker / dev), the `[check]` lines
from the startup log and the output of **Menu → Debug → Connection test**.
**Remove passwords, tokens and public addresses from anything you paste.**

## Development

See [Development in the README](README.md#development). Before opening a pull request run:

```bash
npm run typecheck && npm test && npm run build
```

- New server logic needs a pytest test; keep `mypy --strict` and TypeScript `strict` clean.
- Keep `apps/web/src/types.ts` and `apps/server/hik_server/models.py` in sync.
- No CDN dependencies in the UI; no credentials in code, docs or tests.
- Changes to call handling (`doorbell.py`, `hikvision.py`) should be tried on a real doorbell - say what you tested.
- Commit messages: imperative mood, English (`Fix hang-up retry after 401`).
