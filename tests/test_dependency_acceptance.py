import copy
import hashlib
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import dependency_acceptance as gate

class DependencyAcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.identity = dict(commit='a'*40, run_id='123', attempt='1')
        self.report = dict(schema='orbit.dependency-browser-evidence.v1', milestone='P6.3c.1e',
            source_commit=self.identity['commit'], run_id='123', run_attempt='1',
            transport='isolated_synthetic_inference_and_sandbox_fixture',
            checkpoints={k: True for k in gate.CHECKPOINTS}, **{k: False for k in gate.FLAGS})

    def raw(self, data=None):
        return json.dumps(self.report if data is None else data).encode()

    def test_exact_current_evidence(self):
        raw = self.raw()
        self.assertEqual(gate.validate(raw, **self.identity), hashlib.sha256(raw).hexdigest())

    def test_missing_unknown_and_false_checkpoints(self):
        for variant in ('missing', 'unknown', 'false', 'integer'):
            with self.subTest(variant=variant):
                data = copy.deepcopy(self.report)
                k = next(iter(gate.CHECKPOINTS))
                if variant == 'missing': del data['checkpoints'][k]
                elif variant == 'unknown': data['checkpoints']['unknown'] = True
                else: data['checkpoints'][k] = False if variant == 'false' else 1
                with self.assertRaises(ValueError): gate.validate(self.raw(data), **self.identity)

    def test_stale_commit_run_attempt_or_wrong_scope(self):
        for key, value in [('source_commit','b'*40), ('run_id','124'), ('run_attempt','2'),
                           ('transport','real_ai'), ('milestone','P6.3c.1d.1')]:
            with self.subTest(key=key):
                with self.assertRaises(ValueError):
                    gate.validate(self.raw({**self.report, key:value}), **self.identity)

    def test_authority_flags_fail_closed(self):
        for key in gate.FLAGS:
            for value in (True, 0, None):
                with self.subTest(key=key, value=value):
                    with self.assertRaises(ValueError):
                        gate.validate(self.raw({**self.report,key:value}), **self.identity)

    def test_duplicate_or_extra_fields(self):
        duplicate = self.raw()[:-1] + b', "execution_authorized": false}'
        with self.assertRaises(ValueError): gate.validate(duplicate, **self.identity)
        with self.assertRaises(ValueError):
            gate.validate(self.raw({**self.report,'extra':True}), **self.identity)
