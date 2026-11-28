"""Strict, CI-only dependency acceptance evidence validation; no execution authority."""
import hashlib
import json
import os
import re
import sys
from pathlib import Path

CHECKPOINTS = frozenset(["missing_prerequisite_rejected","qa_form_preserved","root_qa_receipt","fresh_qa_before_old_poll","stale_poll_rejected","rollback_dependency_pin","rollback_dependency_audit","stale_dispatch_zero_calls","dependent_dispatch_and_pin","dependent_qa_receipt","dependent_completion_receipt","upstream_stale_propagation","owner_navigation_bootstrap","same_session_and_adoption","recovery_stable_frames","legacy_reload_and_digest","reviewer_navigation_bootstrap","legacy_approval_and_prd_stale"])
FLAGS = ('automatic_dispatch', 'execution_authorized', 'merge_authorized', 'production_release_authorized')
FIELDS = frozenset(('schema', 'milestone', 'source_commit', 'run_id', 'run_attempt', 'transport', 'checkpoints', *FLAGS))

def unique_object(pairs):
    out = {}
    for key, value in pairs:
        if key in out:
            raise ValueError('Duplicate evidence key: ' + key)
        out[key] = value
    return out

def validate(raw, *, commit, run_id, attempt):
    if not re.fullmatch(r'[0-9a-f]{40}', commit) or not re.fullmatch(r'[1-9][0-9]*', run_id) or not re.fullmatch(r'[1-9][0-9]*', attempt):
        raise ValueError('Invalid expected CI identity')
    data = json.loads(raw, object_pairs_hook=unique_object)
    if not isinstance(data, dict) or set(data) != FIELDS:
        raise ValueError('Unexpected evidence fields')
    expected = dict(schema='orbit.dependency-browser-evidence.v1', milestone='P6.3c.1e',
                    source_commit=commit, run_id=run_id, run_attempt=attempt,
                    transport='isolated_synthetic_inference_and_sandbox_fixture')
    if any(data[key] != value for key, value in expected.items()):
        raise ValueError('Evidence scope or CI identity mismatch')
    if any(data[key] is not False for key in FLAGS):
        raise ValueError('Evidence must not grant execution or release authority')
    checks = data['checkpoints']
    if not isinstance(checks, dict) or set(checks) != CHECKPOINTS or any(v is not True for v in checks.values()):
        raise ValueError('Missing, unknown or failed dependency checkpoint')
    return hashlib.sha256(raw).hexdigest()

def main():
    raw = Path(sys.argv[1]).read_bytes()
    digest = validate(raw, commit=os.environ['GITHUB_SHA'], run_id=os.environ['GITHUB_RUN_ID'], attempt=os.environ['GITHUB_RUN_ATTEMPT'])
    print(f'Dependency integration evidence verified: {len(CHECKPOINTS)}/{len(CHECKPOINTS)} checkpoints; sha256={digest}')
    with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as out:
        out.write(f'evidence_sha256={digest}\n')

if __name__ == '__main__':
    main()
