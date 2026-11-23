# ORBIT v0.6 — Independent Web candidate evaluation (increment 3)

## Delivered
- Compare independent DEV-A and DEV-B code candidates **only** after both have passed review and Docker sandbox verification.
- Verify both lane source hashes against sandbox evidence and require at least one executed, passing test per lane.
- Human Tech Lead may explicitly select **A or B** with named reviewer, 20+ character rationale and exact confirmation token.
- A selected candidate remains untrusted: no automatic publish, PR, merge or production release.
- 13 unit tests cover success and fail-closed scenarios.

## Important limitations
- The existing Coding Factory still generates two proposals sequentially and by default selects A in its own manifest. This evaluator adds an **independent optional selection decision**; it does not yet change that original export/PR path. Do not treat this as an integrated selection gate.
- Verification reports are local process records and are not cryptographically signed. Host access, runner identity, model independence and CI artifact provenance require production hardening.
- Current sandbox verifies Python and JavaScript only, not full frontend builds, TypeScript, JSX or browser E2E of AI-generated features.
- Real AI requires configured external/local models; demo proposals are explicitly rejected.
- The module is intentionally **not** exposed as an unauthenticated HTTP endpoint.

## Next
Wire the selection decision into the verified PR exporter after authenticated authorization, and add a sandboxed Web frontend build/test adapter.
