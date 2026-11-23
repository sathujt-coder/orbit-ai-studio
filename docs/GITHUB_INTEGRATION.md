# ORBIT AI v0.3 — GitHub Delivery (configured for `sathujt-coder/orbit-ai-studio`)

## What is actually implemented

- A **GitHub Delivery** panel in the 3D office dashboard with repository, export history, final-artifact selection, preview and explicit `CREATE DRAFT PR` confirmation.
- Backend-only GitHub REST calls. No API key stored in browser/SQLite or shipped in the ZIP.
- Quality gate: only the **latest** final artifact from a completed stage; both independent A and B drafts and the two **cross reviews from the same stage execution**, verdicts `APPROVE` and score >=80. Human approval is additionally required for Security/DevOps/Marketing.
- Database audit log and per-artifact idempotency: avoid duplicate PR creations from the dashboard.
- GitHub contents are restricted to **Markdown documents under `docs/agent-deliverables/`** and draft PRs; this version never merges, executes AI-generated code, deploys, or submits apps to app stores.
- CI runs unit tests, JS parse checks and Python compilation. CI is read-only.

**Cannot verify the GitHub repository from this package.** Check that the repository exists and that the credential has access. A ChatGPT GitHub connection does not provide a credential automatically to this local Python backend.

## First: upload code to your repository safely

Use Git authentication already configured on your own Mac (GitHub CLI or Git credential manager). From a parent directory containing the unzipped `ai-studio-company` folder:

```bash
# Clone your actual repository to a separate local checkout.
git clone https://github.com/sathujt-coder/orbit-ai-studio.git

# Inspect contents first (important if this repo contains existing code).
ls -la orbit-ai-studio

# Create a new branch instead of pushing directly to main.
cd orbit-ai-studio
git switch -c orbit/v0.3-github-delivery

# Copy the ORBIT application into the repo root (does NOT delete existing files).
cp -R ../ai-studio-company/. ./

# Inspect what will be committed. Never commit company.sqlite, .env or secrets.
git status --short
git diff --stat
git add .
git diff --cached --stat
git commit -m 'feat: ORBIT 0.3 GitHub delivery dashboard and audited draft PRs'
git push -u origin orbit/v0.3-github-delivery
```

Open a PR from that branch into `main` and review the changed files. If your GitHub repo isn't empty, compare/merge rather than overwriting blindly.

## Run locally (no GitHub write permission)

```bash
cd ai-studio-company
python3 backend/server.py
```

Visit `http://127.0.0.1:8787` → **GitHub Delivery**. In demo mode, workflow text is illustrative; **not actual research or code execution**. Run a stage to create an eligible final document. Preview needs no GitHub token or outbound API request.

## Enable outbound GitHub draft PRs (optional)

1. On your own computer, provision a short-lived GitHub App installation token (preferred) or fine-grained PAT for **only** `sathujt-coder/orbit-ai-studio`. Permissions required: **Contents: Read and write** and **Pull requests: Read and write**, plus basic repository metadata.
2. Never share your token in chat, the web UI, git history, or a screenshot.
3. Export it in the private shell/session where you start the backend, then start the backend:

```bash
export ORBIT_GITHUB_REPO='sathujt-coder/orbit-ai-studio'
export ORBIT_GITHUB_WRITES=1
# Set GITHUB_TOKEN in your private shell using a secure credential mechanism.
# Example if you authenticate with GitHub CLI and it has access:
export GITHUB_TOKEN="$(gh auth token)"
python3 backend/server.py
```

GitHub CLI tokens may have different access rights from fine-grained PATs; confirm the token is authorized for this repository. `ORBIT_GITHUB_WRITES=1` is **never** necessary for the demo or preview.

Then: create a project → run an agent stage → select its final document in GitHub Delivery → **Kiểm tra trước khi gửi** → **Tạo draft PR** → type `CREATE DRAFT PR`. The real branch and PR are only created at this last step. No auto-merge.

A legacy v0.1/v0.2 database is migrated without deleting previous data. Legacy final documents lack an auditable `run_id`, so rerun the stage before exporting through v0.3.

## Branch protection / quality

Protect `main` with GitHub branch protection/rulesets, require the `Unit tests and JS syntax` CI check, and require a **human** review. AI cross-review in ORBIT is not an independent GitHub account and does not count as a human reviewer or CI result. Enable 2FA and least-privilege credentials. Avoid turning this local MVP into a public server: it has no user authentication, session management, hardened sandbox, or remote authorization.

## Planned, not yet implemented

Full repository read/write code agents with isolated git worktrees and sandbox test execution, verified code review comments, GitHub issue tracking, deployment environments, Flutter builds and Play Store/App Store automated submissions. Each needs additional isolation, auth and approval safeguards.
