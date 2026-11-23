"""ORBIT v0.5 fail-closed sandbox and provenance acceptance tests."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
import coding_factory as cf
import verification_factory as vf

PY_IMG = 'python:3.12-alpine@sha256:' + 'a' * 64
JS_IMG = 'node:22-alpine@sha256:' + 'b' * 64


def proposal_py():
    return cf.validate_proposal({'summary': 'sample', 'files': [
        {'path': 'main.py', 'content': 'def add(a, b):\n    return a + b\n'},
        {'path': 'test_main.py', 'content': 'import unittest\nfrom main import add\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(1, 2), 3)\n'},
    ]})


def proposal_js():
    return cf.validate_proposal({'summary': 'sample', 'files': [
        {'path': 'main.js', 'content': 'export const add = (a,b)=>a+b;\n'},
        {'path': 'main.test.js', 'content': 'import {test} from "node:test";\nimport {strictEqual} from "node:assert";\nimport {add} from "./main.js";\ntest("sum",()=>strictEqual(add(1,2),3));\n'},
    ]})


def job(a=None, b=None):
    a = a or proposal_py()
    b = b or proposal_py()
    return {'id': 'job-abc', 'project_id': 'proj-1', 'status': 'ready',
            'proposal_a': a, 'proposal_b': b,
            'review_a': {'reviewer': 'A', 'author': 'B', 'verdict': 'APPROVE', 'score': 82},
            'review_b': {'reviewer': 'B', 'author': 'A', 'verdict': 'APPROVE', 'score': 90},
            'manifest': {'selected': 'A', 'mode': 'model', 'files':
                         [{'path': f['path'], 'sha256': f['sha256']} for f in a['files']]}}


class FakeDocker:
    def __init__(self, python_return=0, node_return=0, python_count=2, node_count=1):
        self.calls = []
        self.python_return = python_return
        self.node_return = node_return
        self.python_count = python_count
        self.node_count = node_count

    def __call__(self, argv, **kwargs):
        self.calls.append((argv, kwargs))
        if 'unittest' in argv:
            return subprocess.CompletedProcess(argv, self.python_return, '', f'Ran {self.python_count} tests in 0.002s\n\nOK\n')
        if '--test' in argv:
            return subprocess.CompletedProcess(argv, self.node_return, f'# tests {self.node_count}\n', '')
        return subprocess.CompletedProcess(argv, 0, '', '')


class ProvenanceTests(unittest.TestCase):
    def test_preview_does_not_execute(self):
        p = vf.preview_job(job())
        self.assertEqual(p['status'], 'awaiting_human_approval')
        self.assertEqual(set(p['lanes']), {'A', 'B'})

    def test_demo_is_not_verified(self):
        j = job()
        j['manifest']['mode'] = 'demo'
        with self.assertRaises(ValueError):
            vf.preview_job(j)

    def test_review_incomplete_or_wrong_direction_rejected(self):
        for edit in ({'reviewer': 'A', 'author': 'A'}, {'score': 79}, {'verdict': 'REQUEST_CHANGES'}, {'score': True}):
            j = job()
            j['review_b'].update(edit)
            with self.subTest(edit=edit), self.assertRaises(ValueError):
                vf.safe_job(j)

    def test_mutation_after_review_rejected(self):
        j = job()
        j['proposal_a']['files'][0]['content'] = 'print("changed")'
        with self.assertRaises(ValueError):
            vf.safe_job(j)

    def test_refuses_missing_tests(self):
        p = cf.validate_proposal({'files': [{'path': 'main.py', 'content': 'print(1)'}]})
        result = vf.preview_job(job(p, p))
        self.assertEqual(result['status'], 'blocked')
        self.assertIn('MISSING_PYTHON_TESTS', result['lanes']['A']['blocking_reasons'])

    def test_static_scan_blocks_dangerous_code_and_nonpython(self):
        p = cf.validate_proposal({'files': [
            {'path': 'main.py', 'content': 'import subprocess\nsubprocess.run(["id"])'},
            {'path': 'test_main.py', 'content': 'import unittest\n'},
            {'path': 'src/main.dart', 'content': 'void main(){}'},
        ]})
        result = vf.preview_job(job(p, p))
        self.assertEqual(result['status'], 'blocked')
        codes = {f['code'] for f in result['lanes']['A']['findings']}
        self.assertIn('UNSUPPORTED_FORMAT', codes)
        self.assertIn('DANGEROUS_IMPORT', codes)


class SandboxTests(unittest.TestCase):
    def test_approval_is_required_even_with_good_code(self):
        mock = FakeDocker()
        with self.assertRaises(PermissionError):
            vf.verify_job(job(), python_image=PY_IMG, runner=mock)
        self.assertEqual(mock.calls, [])

    def test_image_digest_required(self):
        for image in ('python:3.12-alpine', '', 'python@sha256:abc', 'evil/../image@sha256:' + 'a'*64):
            with self.subTest(image=image), self.assertRaises(ValueError):
                vf.pinned_image(image)

    def test_good_python_runs_two_isolated_lanes(self):
        mock = FakeDocker()
        result = vf.verify_job(job(), python_image=PY_IMG, runner=mock,
                               approval='RUN SANDBOX job-abc')
        self.assertEqual(result['gate'], 'PASS')
        self.assertEqual(result['verdict'], 'passed')
        self.assertEqual(len(mock.calls), 2)
        self.assertEqual(result['lanes']['B']['steps'][0]['test_count'], 2)
        first, second = mock.calls[0][0], mock.calls[1][0]
        self.assertNotEqual(first[first.index('--name') + 1], second[second.index('--name') + 1])
        self.assertIn('--network', first)
        self.assertEqual(first[first.index('--network') + 1], 'none')
        for expected in ('--read-only', '--cap-drop', '--pids-limit', '--memory', '--cpus', '--user', '--mount', '--pull', '--security-opt'):
            self.assertIn(expected, first)
        self.assertIn('readonly', first[first.index('--mount') + 1])
        self.assertEqual(first[0], 'docker')
        self.assertNotIn('shell', mock.calls[0][1])

    def test_javascript_syntax_and_node_test(self):
        mock = FakeDocker()
        out = vf.verify_job(job(proposal_js(), proposal_js()), node_image=JS_IMG,
                            runner=mock, approval='RUN SANDBOX job-abc')
        self.assertEqual(out['gate'], 'PASS')
        self.assertEqual(len(mock.calls), 6)  # two node --check, one --test, for two agents
        self.assertTrue(all(step['passed'] for step in out['lanes']['A']['steps']))

    def test_failure_and_zero_tests_block_quality_gate(self):
        for opts in ({'python_return': 1}, {'python_count': 0}):
            fake = FakeDocker(**opts)
            out = vf.verify_job(job(), python_image=PY_IMG, runner=fake,
                                approval='RUN SANDBOX job-abc')
            self.assertEqual(out['gate'], 'BLOCK')
            self.assertEqual(out['verdict'], 'failed')

    def test_missing_docker_fail_closed(self):
        def unavailable(*args, **kwargs):
            raise FileNotFoundError('docker not installed')
        out = vf.verify_job(job(), python_image=PY_IMG, runner=unavailable,
                            approval='RUN SANDBOX job-abc')
        self.assertEqual(out['verdict'], 'not_verified')
        self.assertEqual(out['gate'], 'BLOCK')
        self.assertFalse(out['lanes']['A']['steps'][0]['executed'])

    def test_static_block_stops_before_docker(self):
        p = cf.validate_proposal({'files': [
            {'path': 'main.py', 'content': 'eval("1+1")'},
            {'path': 'test_main.py', 'content': 'def test_x(): pass'},
        ]})
        fake = FakeDocker()
        out = vf.verify_job(job(p, p), approval='RUN SANDBOX job-abc', runner=fake)
        self.assertEqual(out['verdict'], 'blocked')
        self.assertEqual(fake.calls, [])

    def test_reports_are_append_only_and_readable(self):
        with sqlite3.connect(':memory:') as conn:
            conn.row_factory = sqlite3.Row
            result = vf.verify_job(job(), python_image=PY_IMG, runner=FakeDocker(),
                                   approval='RUN SANDBOX job-abc')
            one = vf.store_report(conn, result)
            two = vf.store_report(conn, result)
            self.assertNotEqual(one, two)
            data = vf.list_reports(conn, 'job-abc')
            self.assertEqual(len(data), 2)
            self.assertEqual(data[0]['report']['gate'], 'PASS')
            self.assertEqual(vf.list_reports(conn, 'other-job'), [])


if __name__ == '__main__':
    unittest.main()
