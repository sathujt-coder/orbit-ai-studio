# ORBIT AI Studio — GitHub delivery plan

Target: `sathujt-coder/orbit-ai-studio`.

## Scope
The validated local ORBIT v0.4 bundle includes 12 departments, 24 agents, a 3D office interface, independent proposals, cross-review, quality gates, task history, a GitHub-delivery module and a coding artifact exporter.

**Important:** This foundation PR only sets up repository hygiene and CI. It does not contain the full v0.4 source bundle. Do not merge it as a product release until the complete application source has been uploaded and CI passes.

## Upload the existing v0.4 ZIP

1. Download `orbit-ai-software-studio-v04-coding-factory.zip` from the ChatGPT conversation.
2. Extract it. The application files live inside `ai-studio-company/`.
3. Clone the repository and check out `feat/orbit-v04-foundation`.
4. Copy the *contents* of `ai-studio-company/` to repository root. Preserve `.github/`, `backend/`, `web/`, `tests/`, `tools/`, `docs/`, `README.md`, `start.sh` and `.gitignore`.
5. Run `python3 -m unittest discover -s tests -v`, `node --check web/app.js`, and `node --check web/world3d.js`.
6. Commit and push. GitHub Actions will validate the full codebase.

## Quality / security safeguards

- No tokens, credentials, `.env` files, or generated SQLite databases in Git.
- Code and cross-review results must be independently verified; AI-generated approvals are not substitutes for executed tests or security audits.
- Require human approval before merging, publishing to stores, or deploying to production.
- Keep the MVP bound to localhost; it has no production authentication/RBAC.
- Never run generated code outside a sandbox.

## Next milestone

Implement actual coding-agent isolated worktrees, sandboxed execution, deterministic acceptance tests, PR-based delivery and independent security review, then release automation gated by human approval.
