# ORBIT AI v0.3 — Release notes

Target repo: `https://github.com/sathujt-coder/orbit-ai-studio.git` (configured, not pushed or verified by this package).

## Added
- GitHub Delivery dashboard panel with live local backend config indicators.
- Quality-gated preview and opt-in draft PR creation from the application, without putting tokens in the frontend.
- A/B draft/review run IDs and migration for 0.1/0.2 SQLite databases. Only verified final artifacts are exported.
- Export history and idempotency reservation in SQLite.
- Same-origin + local-host checks and required custom request header for browser POST operations.
- Offline integration tests for the bridge, alongside existing workflow and PR helper tests.

## Security note
This is a **local-only experimental MVP**, not a secure multi-tenant or autonomous code deployment system. Never expose its port publicly or give a low-trust party local access to it. The app may create **draft documentation PRs** only when writes are explicitly enabled and the operator types a confirmation phrase.

## Running

```bash
python3 backend/server.py
python3 -m unittest discover -s tests -v
```

See `docs/GITHUB_INTEGRATION.md` for publishing/updating GitHub and enabling a local write token. The repository's actual permission, branch protection and CI status were not verified here.
