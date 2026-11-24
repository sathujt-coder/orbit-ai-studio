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

## P6.1c — Durable discovery integration (pending CI)
- New queue kind requirements, with startup migration preserving legacy queue rows and events.
- POST /api/projects/{pid}/requirements/discover with confirmation RUN AI REQUIREMENTS.
- GET /api/projects/{pid}/requirements includes latest task, evidence, models and adoption readiness.
- POST /api/projects/{pid}/requirements/adopt with queue_id, digest, expected_version and confirmation ADOPT AI REQUIREMENTS.
- Worker uses existing tracked provider, routing, resource, budget and concurrency guards; demo rejected.
- Evidence plus terminal state commit together. Interrupted jobs are not automatically replayed; explicit retry captures a fresh idea/current version.
- Reviewed draft adoption is explicit, project-scoped and stale-version protected. It creates an unapproved revision with a provenance link; separate human approval remains mandatory.
- Running discovery cannot be cancelled or paused mid-inference; queued tasks can be controlled in Task Queue.
- UI polls discovery state without overwriting a user's document edits. Research/BA collaboration and P6.2 enforcement remain separate increments.

## P6.1d — Research / BA collaboration (pending acceptance)
- Research A/B independently analyze the supplied idea, then cross-review. No web search or fabricated market evidence.
- BA A/B independently consume both research drafts/reviews; derive workflows, rules, edge cases and unknowns, then cross-review.
- PO A/B independently consume both department handoffs, cross-review, synthesize and independently review the final document. Department blockers must be assessed and unresolved decisions preserved; semantic correctness remains a human-review responsibility.
- One durable queue task uses a shared distinct routed A/B pair (not six different models), 14 bounded tracked calls, per-department agent IDs and existing guards. No automatic replay. A deployment must allow at least 14 calls per discovery run, subject to all other budget limits.
- Full handoffs are included in existing project-scoped evidence and shown in the Requirements UI. No auto-adoption or auto-approval.
- Real offline smoke now checks exact 14-call phase/agent provenance, department handoffs, token/cost ledgers and existing approval invariants. Browser E2E specific to Requirements and live human sign-off are still pending.

## P6.1e — Browser and final acceptance gates (pending CI)
- P6.1b real-model CI exposed missing functional/nonfunctional coverage. Keep strict validation;
  at most one corrective inference per PO document phase, no retry on provider/admission failures.
  14 normal calls, up to 3 format repairs; the configured run budget must permit the chosen limit.
  Repair attempts are tracked separately; an invalid repair blocks the task.
- Offline acceptance checks exact phase/agent order including bounded repairs, actual model token
  ledger, queue/evidence persistence, adoption and approval. Failed runs include sanitized attempt metadata.
- Dedicated Chromium job uses actual HTTP, RBAC, CSRF, queue and SQLite with explicitly synthetic
  model transport in a test-only process. It must never count as real inference evidence.
- Browser gates cover queue submission, evidence, adoption, reviewer approval, revision invalidation,
  cross-project access, rejected/stale adoption, and unsaved edit protection.
- Final engineering acceptance requires both current-commit regression/browser and real offline
  acceptance PASS, plus review of requirements.json. Production sign-off and P5.9 soak remain separate.

## P6.1e follow-up — grouped model output contract
The real 3B models completed Research/BA but failed PO document creation/repair.
Use two mandatory nonempty model-generated requirement groups with an embedded story per item;
the backend assigns deterministic IDs and traceability links, then applies the unchanged
product_requirements.validate gate. No requirement text, acceptance criteria or story is invented
by the backend. The stored canonical document and human UI contract are unchanged.
Repair regenerates from the original inputs plus validation error without appending malformed output.
The real offline test uses a 300-second provider timeout (not a production default change);
the 17-call cap, existing resource limits and strict final-review/approval gates remain in force.
Provider failures surface a bounded phase/class diagnostic, with no automatic retry.

## P6.1e follow-up — scope fidelity and bounded semantic revision
Commit ec9649b completed all 14 real inference calls but the final quality gate blocked:
registration/project management scope creep, unresolved questions, and repeated draft review feedback.
The original user idea is authoritative; existing capabilities are dependencies, not deliverables.
Nonblocking research unknowns remain in preserved department evidence; essential unknowns still block.
Final B review independently evaluates the actual latest document against the idea, without copying
historical reviewer verdicts. One A semantic revision and one fresh B review are allowed;
initial and revised evidence are retained. Persistent blockers or open questions still prevent adoption.
No auto-approval or backend removal of questions. 14 normal calls, at most 2 semantic revision calls
and up to 4 bounded document-format repairs (20 total maximum). The offline test checks exact phase
order, all token/cost and adoption gates, plus an independent fixture scope-creep check.
CI timeout is extended only to accommodate the bounded extra model calls.

## P6.1f — Human scope contract and deterministic quality enforcement (pending CI)
The c8f67b9 real-model run completed 16 calls but returned identical before/after
documents containing unrequested registration and project management, three open
questions, and a falsely positive reviewer verdict. New discovery submissions
require an explicit human-authored scope_contract in POST /requirements/discover.
The Requirements page exposes the source idea and a JSON contract editor. Each rule
has id, kind, required, an exact evidence substring from the source idea, and
matches (AND of OR literal phrase groups). forbidden lists unauthorized capability
phrases; nonblocking_questions lists exact user-deferred questions. At least one
required rule per kind. The immutable queue input snapshots the contract; retries
reuse it and revalidate against the source. Legacy evidence without a contract
cannot be newly adopted. Human-authored manual requirements remain available.
Backend checks coverage, unsupported/forbidden requirements, forbidden metadata and
open questions. Targeted projection may remove unauthorized items and their story
links only if structurally valid and required coverage remains; it defers only
explicitly designated questions and preserves original content in evidence. A fresh
independent B review is required after deterministic repair. Remaining defects use
one bounded model revision/recheck; a no-op revision blocks adoption. Persistence
and adoption independently recompute the contract gate, regardless of model verdict.
Literal matching and exact quotes are deterministic but do not prove semantic
entailment or completeness; human approval remains mandatory. The original offline
fixture idea and independent semantic checks remain; the fixture now supplies an
explicit test-author contract, so a future PASS is for contracted discovery, not
unconstrained free-text inference. 14 baseline calls, either a fresh scope recheck
or 2 model revision calls plus existing format repairs, at most 20 calls.
