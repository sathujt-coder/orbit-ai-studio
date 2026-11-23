# ORBIT v0.6 — Tech Lead-selected code Draft PR

## Delivered
- The verified PR exporter now requires a Tech Lead decision for either DEV-A or DEV-B.
- The decision is compared with fresh sandbox evidence for both lanes; source digests, project ID and candidate comparison must match.
- Only the selected candidate is written under `agent-proposals/<job>/candidate-A/` or `candidate-B/`; no generated code is written into production application paths.
- Preflight validation rejects invalid candidate paths before any GitHub write.
- The publish CLI now requires `--decision /path/to/decision.json` for both dry-run and apply.
- Seven regression tests cover selecting B, rejecting stale decisions and preventing untrusted paths.

## CLI example
```bash
python tools/publish_verified_code.py --job-id JOB_ID --repo OWNER/REPO --db company.sqlite --decision /secure/decision.json
# Only after explicit human authorization:
ORBIT_GITHUB_WRITES=1 GITHUB_TOKEN=... python tools/publish_verified_code.py --job-id JOB_ID --repo OWNER/REPO --db company.sqlite --decision /secure/decision.json --apply --confirm "CREATE CODE PR JOB_ID"
```

## Limitations
- The decision JSON is not cryptographically signed and is not independently authenticated. Run only in a trusted operator environment; production needs RBAC, immutable audit trail and approver identity binding.
- No automatic merge, deployment or mobile development.
- Sandbox still supports Python/JS only; TypeScript/React build and browser E2E of **AI-generated** features remain outstanding.
- Legacy tests that assumed an implicit DEV-A exporter need updating to pass an explicit decision.
