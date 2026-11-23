# ORBIT v0.6 — Web Factory, increment 2: real browser tests

## Delivered
- The project creation dialog defaults to **Web app**; Mobile and Flutter options have been removed from the new-project UI.
- The initial demo project and DevOps/Marketing descriptions are Web-first.
- Backend project creation defaults to `Web app`; bootstrap reports `0.6.0-web-first`.
- GitHub Actions runs a separate **real Chromium E2E job**, using pinned Playwright 1.56.1, a fresh temporary SQLite database and an isolated localhost server.
- E2E checks the dashboard boots, 24 agents exist, two members render, the Web project form excludes Mobile, project creation persists 12 tasks, and origin/validation protections reject unsafe requests.
- CI saves backend logs if the browser test fails.

## Verification scope and limitations
This is a **real browser test of the existing ORBIT Web UI and API**, not browser execution of untrusted generated code. It does not yet implement isolated frontend/backend coding workspaces, full feature testing, dependency scans, staging, UAT or production authentication. Do not interpret CI success as product acceptance.

## Next increments
1. Independently generated frontend/backend feature candidates with explicit contract tests and reviewer evidence.
2. Secure, allowlisted web build/test adapters for isolated Docker environments.
3. Staging UAT and authenticated acceptance evidence with production-grade RBAC.
