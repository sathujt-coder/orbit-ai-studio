import json
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import dependency_queue as dq
import engineering_contract as ec
import studio_coding as sc
import wbs_dependency_extension as ext
import project_planning as pp

class EffectiveDependencyTests(unittest.TestCase):
    def test_legacy_root_cannot_bypass_overlay(self):
        snap={'package':{'id':'B','kind':'implement','depends_on':[]}}
        with patch.object(sc,'exact_package',return_value=snap),patch.object(ext,'predecessors',return_value=['A']):
            with self.assertRaisesRegex(ValueError,'Dependent'):
                sc.checked_package(None,'p',1,'B','b')
            with patch.object(dq,'checked_package',side_effect=ValueError('Missing pinned prerequisite evidence')):
                with self.assertRaisesRegex(ValueError,'Missing pinned'):
                    sc.checked_job_package(None,'p',dict(adoption_version=1,package_id='B',binding_digest='b'))
    def test_invalid_overlay_no_fallback(self):
        c=sqlite3.connect(':memory:');c.row_factory=sqlite3.Row;self.addCleanup(c.close)
        ext.ensure_schema(c)
        c.execute('INSERT INTO wbs_dependency_extensions VALUES(?,?,?,?,?,?,?)',('p',1,1,'{}','bad','owner','t'))
        with patch.object(ext,'base',return_value=({'version':1},{})):
            with self.assertRaises(ValueError):ext.predecessors(c,'p',1,{'id':'B','depends_on':[]})
    def test_transitive_receipt_revalidation(self):
        # Exercise recursive production queue source traversal, isolate QA/sandbox
        # transport with fixture completion sources and a pinned intermediate job.
        contracts={p:dict(project_id='p',adoption_version=1,package_id=p,binding_digest=p,graph_digest='g',
            kind='implement',spec_digest='s',predecessors=deps,
            structural_eligibility='DEPENDENT_IMPLEMENTATION' if deps else 'ROOT_IMPLEMENTATION',
            reasons=['PREREQUISITE_EVIDENCE_REQUIRED'] if deps else []) for p,deps in [('A',[]),('B',['A']),('C',['B'])]}
        decision=dict(selected='A',selected_digest='candidate',rationale='Reviewed fixture dependency.',decided_at='t')
        sources={p:dict(project_id='p',job_id=p,package_id=p,adoption_version=1,graph_digest='g',report_id='r') for p in 'AB'}
        rows={}
        def save(p):
            snap=dict(source=sources[p],decision=decision)
            rows[p]=dict(job_id=p,version=1,digest=pp.digest(snap),snapshot=json.dumps(snap),actor='owner')
        save('A')
        def completion(c,pid,jid):
            if jid=='B':
                current=dq.source(c,pid,1,'B','B')
                if pp.digest(current)!=sources['B']['dependency_source_digest']:
                    raise ValueError('Stale intermediate pin')
            return sources[jid]
        with patch.object(ec,'source',side_effect=lambda c,pid,p:contracts[p]),patch.object(ec,'require_confirmed',return_value={'version':1}),patch.object(dq.dc,'latest',side_effect=lambda c,pid,v,p:rows.get(p)),patch.object(dq.dc,'source',side_effect=completion),patch.object(dq.dc,'selection',return_value=decision):
            with self.assertRaisesRegex(ValueError,'Missing prerequisite'):dq.source(None,'p',1,'C','C')
            sources['B']['dependency_source_digest']=pp.digest(dq.source(None,'p',1,'B','B'))
            save('B')
            self.assertEqual(dq.source(None,'p',1,'C','C')['prerequisites'][0]['package_id'],'B')
            sources['A']['report_id']='changed'
            with self.assertRaisesRegex(ValueError,'Stale prerequisite'):dq.source(None,'p',1,'C','C')
