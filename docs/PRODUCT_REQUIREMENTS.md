# P6.1a — Structured requirements foundation
This is the first incremental delivery of P6.1, not complete AI product discovery. P5.9 24-hour acceptance remains pending. The branch is stacked on P5.9; do not merge to main until dependency and acceptance gates are resolved.

## Scope
- Web-first project-scoped structured PRD/SRS fields, functional and nonfunctional requirements, acceptance criteria and linked user stories.
- Human-authored revisions only. Immutable document revisions with SHA-256 digest, author, approval actor and timestamps. New revisions invalidate planning readiness.
- Explicit approval of the current digest and version; unresolved questions block approval.
- Existing session, CSRF and project RBAC guard the routes; no inference, external calls or deployment.
- GET /api/projects/{pid}/requirements
- POST /api/projects/{pid}/requirements (expected_version, document)
- POST /api/projects/{pid}/requirements/approve (version, digest, confirmation: APPROVE PRODUCT REQUIREMENTS)
- Open Product Requirements from the dashboard. JSON form is an initial technical UI, not final product UX.
- Existing P0–P5 pipeline behavior is unchanged. planning_ready is the input contract for future P6.2, not an enforced gate on legacy workflow or evidence of product UAT.

## Next increments
P6.1b: integrate PO/Research/BA independent proposals, cross review and synthesis through the durable agent queue and tracked inference. Persist provenance, reject demo as real evidence, validate conflicts and review the final document.
P6.1c: user-friendly editing, real offline acceptance and browser coverage; P6.2 must consume only approved current revisions.

## P6.1b incremental offline acceptance
The reusable discovery module generates independent PO A/B drafts, exchanges cross-reviews,
synthesizes a structured document, and requests a final B review. Invalid schema, unresolved
questions or a blocking final review cannot produce a ready-for-human-review result.
The trusted CLI runs six actual local-model calls through existing tracked inference and
resource/concurrency/budget guards on an isolated synthetic project. It verifies fixture scope,
traceability, token ledger, budget release, and version/digest approval and persistence.
The report is requirements.json in the existing offline-inference-report artifact.
The approval actor is a test fixture, not an actual human sign-off. This is not production
acceptance: durable queue, Research/BA collaboration, HTTP/API integration, real human
adoption, provenance in production storage and browser coverage remain to be delivered.
The existing human-authored UI and legacy pipeline remain unchanged.
