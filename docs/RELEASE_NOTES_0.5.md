# ORBIT v0.5 — Isolated Coding Verification and Draft PR Delivery

## Delivered

- Separate, independent DEV-A and DEV-B source proposals continue from v0.4.
- **Verification provenance:** rechecks status, reciprocal A/B review scores, selected candidate SHA-256 manifest and the active source bytes.
- **Fail-closed static screening:** malformed Python, possible credentials and some clearly dangerous execution primitives are blocked. This is heuristic screening, **not** a comprehensive security audit.
- **Sandbox runner:** only Docker, explicit human confirmation, pinned container images, no container network, read-only workspace and root filesystem, non-root UID, no capabilities, process/memory/CPU/time limits, and no GitHub tokens passed to containers.
- **Evidence for both lanes:** runs Python `unittest` and/or Node syntax and test checks in separate ephemeral workspaces. Requires at least one executed test in each supported language; records summaries in SQLite for read-only display in the Coding Factory UI.
- **Opt-in draft code PR:** only after a recorded passing report for both lanes, with a second explicit human confirmation and a separately configured GitHub token. Generated files stay under `agent-proposals/<job-id>/candidate-A/`; no mutation to application source, no auto-merge or deploy.

## Important safety/accuracy boundaries

1. **Docker is required**, but may not be available on your host. An unavailable Docker daemon returns `not_verified` and blocks a code PR. Tests in CI mock the Docker interface and do **not** claim to have executed real AI-generated code in Docker.
2. Verification only supports **Python (`*.py`) and JavaScript (`*.js`)** as executable source, plus passive assets `.md/.txt/.json/.css/.yaml/.yml`. **Flutter/Dart, TS/TSX/JSX and HTML require future adapters and must not be marked verified** by this version.
3. The source proposals need at least one `test_*.py` or `*.test.js` per applicable language. Unit tests passing do not prove correctness or safety. Models may fabricate tests; use independent QA/human review.
4. **Docker is isolation-in-depth, not a formal security boundary** against all vulnerabilities. Run untrusted model-generated code only on a dedicated disposable host/VM with a properly configured Docker daemon. Never mount the Docker socket or home directory into a sandbox.
5. The entire application is a **localhost MVP**, not production-ready auth/RBAC. Sandbox execution and PR publication intentionally remain **CLI-only**; the dashboard provides read-only evidence, never the execution button.
6. The default `demo` agent mode fabricates examples and reviewers; v0.5 refuses to verify or publish demo output. Use genuine model-backed jobs and independently assess quality.
7. The GitHub connector linked to ChatGPT and the local backend's `GITHUB_TOKEN` are different authentication mechanisms. Local code PR publication is disabled unless expressly configured and approved. Do not put tokens in the repository or browser.

## Usage

Start the app and create a new model-backed Coding Factory job. Copy its job ID from the UI. First inspect the execution plan (NO code execution):

```bash
python3 tools/verify_coding_job.py --job-id JOB_ID
```

Have Docker installed and pre-pull **specific digest-pinned** official Python and Node images (the examples below are placeholders, **not valid real digests**). The image references must exist locally; the runner uses `--pull never` and cannot silently fetch replacements. Source and verify the real sha256 digests yourself.

```bash
export ORBIT_SANDBOX_PYTHON_IMAGE='python:3.12-alpine@sha256:REPLACE_WITH_64_HEX_DIGEST'
export ORBIT_SANDBOX_NODE_IMAGE='node:22-alpine@sha256:REPLACE_WITH_64_HEX_DIGEST'

python3 tools/verify_coding_job.py --job-id JOB_ID \
  --execute --confirm 'RUN SANDBOX JOB_ID'
```

Check the verification report in the Coding Factory dashboard. If **both** lanes pass with executed tests and you independently approve the candidate, preview a draft PR:

```bash
python3 tools/publish_verified_code.py --job-id JOB_ID \
  --repo sathujt-coder/orbit-ai-studio
```

Then explicitly authorize publishing a **draft PR** (requires a local scoped short-lived token):

```bash
export GITHUB_TOKEN='your_expiring_github_app_token'
export ORBIT_GITHUB_WRITES=1
python3 tools/publish_verified_code.py --job-id JOB_ID \
  --repo sathujt-coder/orbit-ai-studio \
  --apply --confirm 'CREATE CODE PR JOB_ID'
```

No CLI command auto-merges, deploys, publishes to Apple/Google stores, or starts ongoing background jobs.
