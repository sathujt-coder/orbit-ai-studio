"""Run focused detection regressions and emit commit-bound evidence."""
import hashlib
import json
import os
import sys
import unittest
from pathlib import Path

root=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(root/'tests'))
sys.path.insert(0,str(root/'backend'))
from test_automated_defect_detection import DetectionTests
suite=unittest.defaultTestLoader.loadTestsFromTestCase(DetectionTests)
result=unittest.TextTestRunner(verbosity=2).run(suite)
passed=result.wasSuccessful() and result.testsRun==8 and not result.skipped
report=dict(schema='orbit.automated-defect-detection-acceptance.v1',
            source_commit=os.environ['GITHUB_SHA'],run_id=os.environ['GITHUB_RUN_ID'],
            run_attempt=os.environ['GITHUB_RUN_ATTEMPT'],tests=result.testsRun,
            failures=len(result.failures),errors=len(result.errors),
            gate='PASS' if passed else 'BLOCK',execution_authorized=False,
            production_release_authorized=False,automatic_dispatch=False)
raw=json.dumps(report,sort_keys=True,separators=(',',':')).encode()
Path('engineering-defect-detection-evidence.json').write_bytes(raw)
if passed:
    with open(os.environ['GITHUB_OUTPUT'],'a') as f:
        f.write('evidence_sha256='+hashlib.sha256(raw).hexdigest()+'\n')
sys.exit(0 if passed else 1)
