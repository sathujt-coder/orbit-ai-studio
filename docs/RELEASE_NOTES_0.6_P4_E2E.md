# P4.2 — Resumable end-to-end operator workflow

Run on a trusted local workstation with configured P4.1 providers and Docker. No credentials in source or chat. First run the live probe, then:

    python tools/run_real_models.py --db company.sqlite --project PROJECT_ID --spec "Implement a small Web backend feature in Python and unittest" --execute --confirm "RUN REAL MODELS PROJECT_ID"

Record the returned JOB_ID. Use the following separate steps (replace placeholders). Images must be trusted and already present by digest.

    python tools/p4_e2e.py --db company.sqlite --job-id JOB_ID status
    python tools/p4_e2e.py --db company.sqlite --job-id JOB_ID verify --python-image python@sha256:YOUR_ACTUAL_DIGEST --confirm "RUN SANDBOX JOB_ID"
    python tools/p4_e2e.py --db company.sqlite --job-id JOB_ID select --selected B --techlead "Named Lead" --rationale "Actual human review rationale of both candidates" --confirm "SELECT DEV-B JOB_ID"
    python tools/p4_e2e.py --db company.sqlite --job-id JOB_ID prepare --decision-output decision.json
    python tools/publish_verified_code.py --db company.sqlite --job-id JOB_ID --repo OWNER/REPO --decision decision.json

The final command defaults to dry run. A/B choice is a human decision, not automatic. Apply separately only if authorized. No application overwrite, merge or deployment. Every stage checks persisted current evidence; changed verification invalidates selection. P4 requires manifests for both candidates; existing legacy CLI remains compatible. DB and local operator are trusted; no signature or authenticated Tech Lead identity for CLI. Supports legacy Python/JS and narrow React welcome profile; standalone TypeScript adapter is not integrated here.

CI tests two local HTTP fixtures, independent prompts and reciprocal review, actual Docker on fixed handwritten Python candidates in a separate CI job, persisted report, B selection, stale decision rejection and dry-run bundle. It does NOT exercise real inference or actual GitHub writes. Do not run arbitrary external model output on standard CI runners. Real two-model end-to-end must be executed with configured provider and human-approved isolated sandbox on a suitable operator machine. CI success is not P4 real inference acceptance.