# ORBIT v0.6 — Web-first implementation, phase 1

This PR delivers the **Web acceptance state machine** and CI tests. It does **not** deliver a full Web Development Factory, real browser E2E, production deployment or independent evidence verification.

## Policy

Mobile stays locked until all ten Web requirements have recorded evidence and a named human explicitly signs off. Changing any evidence after signoff invalidates acceptance. The signoff is a local process record, **not a cryptographic identity signature**: anyone able to edit the JSON could forge it. Production needs authenticated approvers, immutable audit storage and server-side RBAC.

The ten gates are: approved scope, working frontend/backend, independent review, unit/integration/E2E, security, accessibility/responsive, staging UAT, backup/restore, monitoring/rollback and production smoke tests.

## Usage (Python)

```python
from backend.web_acceptance import new_register, record, evaluate, signoff
r = new_register("my-web-project")
print(evaluate(r))  # mobile_unlocked: False
# Record each requirement with a real evidence URL and named reviewer.
# After all pass, require explicit human confirmation:
# r = signoff(r, owner="Human Product Owner", confirmation="ACCEPT WEB my-web-project")
```

The implementation is deliberately not connected to the public-facing localhost API: signoff must not be available anonymously. No automated mobile build, merge or production deployment is triggered by the flag.

## Next development increments

1. Browser E2E test harness (Playwright) with reproducible browser and artifact setup.
2. Frontend and backend feature workspaces and independent agent proposals.
3. Staging UAT evidence ingestion with authentication and human reviewer verification.
4. CI coverage for real Web feature implementations and deployment approval.
