# P6.2 — Project Planning & Task Decomposition

Baseline: P6.1 technical acceptance at 4feb315 (Regression 45425297424,
real local-model acceptance 45425297410). This is a stacked draft on the
accepted P6.1 branch; P5.9 24-hour soak and production sign-off remain separate.
Do not merge the stack until all dependent gates are resolved.

## P6.2a — approved input and deterministic planning foundation (pending CI)
- Read only the current approved PRD, verify version/digest and no unresolved
  questions. Never consume a stale or unapproved revision.
- Separate immutable project_plans revisions, source PRD composite FK, digest,
  author, separate explicit approval. New PRD revisions immediately invalidate
  plan execution readiness, including after that newer PRD is approved.
- Seed a deterministic WBS skeleton: one implementation and one verification
  task for each approved functional/nonfunctional requirement. No model calls.
  This is a starter, not an AI-generated implementation plan or semantic QA.
- Human can edit title, dependencies, linked requirements and effort estimates.
  Backend rejects missing requirement coverage, unknown IDs, cycles, duplicate
  dependencies, self-dependencies and verification before implementation.
  Every verifier must transitively depend on all implementation tasks for its
  linked requirements. Tasks are not dispatched by this module.
- Estimate minutes are null until entered; approval requires all positive
  integer estimates. Sum is person-effort; longest dependency path is only a
  lower bound assuming unlimited parallel resources, not a promised schedule.
- Same-origin session/CSRF and project RBAC. Write (owner/developer), approve
  (owner/reviewer), viewer read-only. Re-check authorization at mutation.
- API GET /api/projects/{pid}/planning
- API POST /api/projects/{pid}/planning/seed (expected_version,
  requirements_version, requirements_digest, confirmation CREATE PLAN DRAFT)
- API POST /api/projects/{pid}/planning (same version/digest input + document)
- API POST /api/projects/{pid}/planning/approve (version, digest, requirements_version,
  requirements_digest, confirmation APPROVE PROJECT PLAN)
- Web Planning page, saved WBS table, source criteria, DAG order/traceability,
  editable JSON and approval. No actual human UAT yet. No legacy workflow
  changes; execution_ready is a future P6.3 input contract, not authorization
  to run code, deploy or bypass existing legacy execution gates.
- New unit and Chromium HTTP fixture tests; existing real-inference CI continues
  to verify P6.1 regression, not real PM inference.

## Planned increments
P6.2b PM A/B independent plan proposals using approved snapshots;
P6.2c WBS deliverables and milestone breakdown; P6.2d AI task decomposition;
P6.2e dependency and critical path hardening; P6.2f resource estimates;
P6.2g milestones/sprint scheduling; P6.2h cross-review/quality gate;
P6.2i durable planning queue, API/UI and explicit adoption;
P6.2j real local PM acceptance and browser coverage. No P6.3 until acceptance.

## P6.2b — independent PM proposals (pending CI)
P6.2a checkpoint 79f12fc passed regression and real P6.1 regression. New durable planning kind snapshots the current approved PRD/version/digest, rechecks authorization and source before calls and persistence, and uses the existing budget/resource/concurrency guards and distinct model routing. PM-A/B see identical source inputs, never the other proposal. Each returns one concrete implementation and verification title per requirement. Backend assigns IDs, required verification edges and null estimates, then independently validates the graph. One bounded invalid-output regeneration per lane; provider failures are not retried. Limits: 8 requirements, 10 KB PRD, 4 calls per discovery. No semantic cross-review, automatic adoption or execution at this stage; proposals are evidence only. UI displays status and evidence; old snapshots become stale. Real offline acceptance uses two actual local Qwen models and verifies ledger and unchanged plan state. Legacy requirements and P5.9 baseline remain unchanged.

### P6.2b.1 — browser project selection isolation
Regression run 45516034783 on 8721e07: 295 Python tests passed and the Planning Chromium test passed; the shared Requirements Chromium test failed at line 58 (expected planning_ready true). Reviewer navigation previously relied on the default project; concurrent fixtures share reviewer accounts and can change the visible project list. The test now deliberately starts on a second, unapproved project with identical PRD content, selects the intended project explicitly, asserts the loaded revision, captures the actual approval HTTP request and checks its exact version/digest and 200 response, and verifies the decoy remains unapproved. No production quality gates, authorization rules, or inference behavior changed. Regression verification pending CI.

### P6.2b.2 — deterministic scope and bounded targeted repair (pending CI)
Artifact 14979053586 on d46a742: A/TASK-1 and A/TASK-3 used excluded "project management interface"; B passed. The approved PRD exclusions are now mandatory literal checks on objectives and task titles. A submitting human may supply additional forbidden phrases and requirement/kind-specific match groups, each grounded in an exact approved description or acceptance criterion. These rules are immutable per queued snapshot and are not a general semantic oracle. A scope failure can consume the lane's single remaining retry on exact flagged field patches; no unrelated changes or new IDs/edges/estimates. Storage independently recomputes scope and repair convergence, and reads fail closed for legacy unverified evidence. Structural readiness is distinguished from scope readiness; no automatic adoption or semantic cross-review. The original independent acceptance regex is retained. The fixture adds explicit rule groups and a separate scope/repair audit gate. Real acceptance remains pending.

### P6.2b.3 — exact-key repair protocol and content integrity (pending CI)
Artifact 14982719177 (80ee3d6) had A scope violations, a malformed repair of unknown exact cause, two 160-character cut-off task titles, and B's 159-character embedded JSON objective. The new quality policy flags JSON/code contamination, control characters, boundary-length text and conservative incomplete-title signals, plus duplicate verification titles. It does not claim grammatical or semantic proof. Each repair has a dynamic flat object schema with exactly the flagged IDs as required keys, no extras, duplicate JSON keys rejected, short plain-text values, safe diagnostic codes and bounded target metadata. Compact context contains only affected requirements/acceptance groups and exclusions, never the broken text, stories, other lane, or unflagged task titles. The stored audit replays the patch and verifies schema/context digests. Legacy evidence without the new policy is not ready. Two calls per lane maximum including format OR scope retry; provider/admission failures are not replayed. Original 14 CI gates and independent regex retained; content_quality adds a 15th gate. Extra fixture match groups are AND constraints, not a relaxation. Actual local inference acceptance still pending.
