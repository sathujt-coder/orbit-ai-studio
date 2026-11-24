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
