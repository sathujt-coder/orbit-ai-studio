import sqlite3
import unittest
from test_react_candidate_gate import proposal, Runner, IMAGE
from test_verification_factory import job
from react_candidate_gate import verify_react
from verification_factory import store_report
from quality_dashboard import quality_summary
class QualityDashboardTests(unittest.TestCase):
    def test_no_evidence(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row
            q=quality_summary(c,job(proposal(),proposal()))
            self.assertFalse(q['selection_ready'])
            self.assertFalse(q['production_approved'])
    def test_redacted_evidence(self):
        j=job(proposal(),proposal())
        report=verify_react(j,image=IMAGE,approval='RUN REACT SANDBOX job-abc',runner=Runner())
        with sqlite3.connect(':memory:') as c:
            c.row_factory=sqlite3.Row
            store_report(c,report)
            q=quality_summary(c,j)
            self.assertTrue(q['selection_ready'])
            self.assertNotIn('output',q['verification']['lanes']['A']['steps'][0])
