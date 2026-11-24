import unittest
import sqlite3
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from test_react_candidate_gate import proposal, Runner, IMAGE
from test_verification_factory import job
from react_candidate_gate import verify_react
from verification_factory import store_report,list_reports
from select_verified_candidate import bind_decision
from verified_pr import verified_bundle

class ReactPersistenceTests(unittest.TestCase):
    def test_roundtrip(self):
        j=job(proposal(),proposal())
        report=verify_react(j,image=IMAGE,approval='RUN REACT SANDBOX job-abc',runner=Runner())
        with sqlite3.connect(':memory:') as conn:
            conn.row_factory=sqlite3.Row
            ref=store_report(conn,report)
            entry=list_reports(conn,j['id'],1)[0]
            d=bind_decision(j,entry,selected='B',techlead='Human Lead',rationale='Both render checks passed for this candidate.',confirmation='SELECT DEV-B job-abc')
            self.assertEqual(d['verification_id'],ref)
            self.assertEqual(verified_bundle(j,entry['report'],decision=d)['selected'],'B')
    def test_failed_latest_blocks(self):
        j=job(proposal(),proposal())
        report=verify_react(j,image=IMAGE,approval='RUN REACT SANDBOX job-abc',runner=Runner(code=1))
        with sqlite3.connect(':memory:') as conn:
            conn.row_factory=sqlite3.Row
            store_report(conn,report)
            with self.assertRaises(ValueError):
                bind_decision(j,list_reports(conn,j['id'],1)[0],selected='A',techlead='Human Lead',rationale='Both render checks passed for this candidate.',confirmation='SELECT DEV-A job-abc')
