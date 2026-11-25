"""Local source preflight. Does not execute generated AI code."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = (
    'backend/server.py', 'backend/coding_factory.py',
    'backend/project_planning.py', 'backend/planning_discovery.py', 'backend/planning_scope.py', 'backend/planning_jobs.py', 'web/planning.html', 'web/planning.js', 'tests/test_project_planning.py',
    'backend/verification_factory.py', 'backend/verified_pr.py',
    'backend/github_bridge.py', 'web/app.js', 'web/world3d.js',
    'web/index.html', 'tests/test_coding_factory.py',
    'tests/test_verification_factory.py', 'tests/test_verified_pr.py',
    'tools/verify_coding_job.py', 'tools/publish_verified_code.py',
    '.github/workflows/orbit-ci.yml',
)
missing = [file for file in REQUIRED if not (ROOT / file).is_file()]
if missing:
    print('Missing required source files:', *missing, sep='\n - ', file=sys.stderr)
    raise SystemExit(1)
print('ORBIT v0.5 source preflight: required files present')
