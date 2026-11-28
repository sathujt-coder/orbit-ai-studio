import copy,sqlite3,sys,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import regression_priority as p
import acceptance_runner as r
import auth_store

class PriorityTests(unittest.TestCase):
    def setUp(self):
        self.source=dict(project_id='p',job_id='j',plan_digest='p1',source_digest='s1',assertion_contract_digest='a1',
                         sandbox_digest='b1',selected='B',git=dict(parent='base',commit='candidate'))
        self.cases=[dict(id=i,criterion_id='AC',kind=k,execution=dict(runtime='python',module='main',function='f',
                    arguments=[],assertion=dict(operator='equals',value=1))) for i,k in [('P','POSITIVE'),('N','NEGATIVE'),('B','BOUNDARY')]]
        self.targets=[dict(path='main.py',module_sha256='a'*64) for _ in self.cases]
        self.rows=[dict(case_id=x['id'],criterion_id='AC',kind=x['kind'],assertion_digest=p.pp.digest(x['execution']),
                   **t,required=True,impacted=i!=0,reason='DIRECT_CHANGE' if i!=0 else 'NO_STATIC_IMPACT_DETECTED')
                   for i,(x,t) in enumerate(zip(self.cases,self.targets))]
        self.v=dict(schema='orbit.impacted-test-mapping.v1',state='IMPACTED_TEST_MAPPING_READY',
                    project_id='p',job_id='j',source=dict(runner_source=self.source),
                    mappings={'baseline_to_B':dict(cases=self.rows,case_count=3,required_count=3,impacted_count=2,
                        to_commit='candidate',full_regression_required=True)},
                    full_regression_required=True,selective_execution_authorized=False,**p.FLAGS)
        self.rehash()
    def rehash(self):self.v['evidence_digest']=p.pp.digest({k:v for k,v in self.v.items() if k!='evidence_digest'})
    def schedule(self):return p.schedule(self.v,self.source,self.cases,self.targets,'baseline_to_B',self.v['evidence_digest'])
    def test_mixed_priority_all_required(self):
        s=self.schedule();self.assertEqual(s['execution_order'],['N','B','P']);self.assertEqual(s['required_count'],3)
    def test_no_impact_preserves_order(self):
        for x in self.rows:x.update(impacted=False,reason='NO_STATIC_IMPACT_DETECTED')
        self.v['mappings']['baseline_to_B']['impacted_count']=0;self.rehash()
        self.assertEqual(self.schedule()['execution_order'],['P','N','B'])
    def test_wrong_digest_or_comparison(self):
        for name,digest in [('A_to_B',self.v['evidence_digest']),('baseline_to_B','old')]:
            with self.assertRaises(ValueError):p.schedule(self.v,self.source,self.cases,self.targets,name,digest)
    def test_waiver_missing_duplicate_or_wrong_binding(self):
        for mutate in (lambda v:v[0].update(required=False),lambda v:v.pop(),lambda v:v[0].update(case_id='N'),
                       lambda v:v[0].update(module_sha256='bad'),lambda v:v[0].update(assertion_digest='bad')):
            old=copy.deepcopy(self.rows);mutate(self.rows);self.rehash()
            with self.assertRaises(ValueError):self.schedule()
            self.rows[:]=old;self.rehash()
    def test_timeout_cannot_be_pass(self):
        s=self.schedule();report=dict(source=self.source,gate='BLOCK',results=[
            dict(case_id='P',status='NOT_EXECUTED',executed=False,reason='TOTAL_TIMEOUT'),
            dict(case_id='N',status='PASS',executed=True),
            dict(case_id='B',status='NOT_EXECUTED',executed=False,reason='TOTAL_TIMEOUT')])
        e=p.evidence(s,['N'],report);self.assertEqual(e['unattempted_order'],['B','P'])
        report['gate']='PASS'
        with self.assertRaises(ValueError):p.evidence(s,['N'],report)
    def test_attempt_order_and_missing_results_rejected(self):
        s=self.schedule();report=dict(source=self.source,gate='PASS',results=[dict(case_id=i,status='PASS',executed=True) for i in ('P','N','B')])
        with self.assertRaises(ValueError):p.evidence(s,['P','N','B'],report)
        report['results'].pop()
        with self.assertRaises(ValueError):p.evidence(s,['N','B','P'],report)
    def run_fixture(self,stale=False):
        c=sqlite3.connect(':memory:');self.addCleanup(c.close);c.row_factory=sqlite3.Row
        auth_store.ensure_schema(c)
        c.execute("INSERT INTO auth_users(id,password_hash) VALUES('reviewer','fixture')")
        c.execute("INSERT INTO auth_memberships VALUES('reviewer','p','reviewer')")
        c.commit();r.restrict_cli_database(c)
        calls=[]
        def execute(root,image,case,meta,timeout):
            self.assertFalse(c.in_transaction);calls.append(case['id'])
            return dict(case_id=case['id'],status='FAIL' if case['id']=='N' else 'PASS',executed=True)
        first=self.schedule();second=dict(first,mapping_digest='changed') if stale else first
        with patch.object(r,'current',return_value=(self.source,self.cases,{},self.targets)), \
             patch.object(p,'current',side_effect=[first,second]), \
             patch.object(r.sb,'materialize',return_value=(Path('/unused'),self.source['git'])), \
             patch.object(r,'execute_case',side_effect=execute):
            def run():return r.run(c,None,'p','j','reviewer','p1','s1','a1','b1','RUN ACCEPTANCE ASSERTIONS j',
                                   image='python@sha256:'+'0'*64,priority_comparison='baseline_to_B',priority_mapping_digest=self.v['evidence_digest'])
            if stale:
                with self.assertRaises(ValueError):run()
            else:
                v=run();self.assertEqual(v['report']['gate'],'BLOCK')
                self.assertEqual([x['case_id'] for x in v['report']['results']],['P','N','B'])
                self.assertEqual(v['priority']['attempted_order'],['N','B','P'])
                self.assertEqual(v['priority_digest'],p.pp.digest(v['priority']))
        self.assertEqual(calls,['N','B','P'])
    def test_actual_runner_order_and_failure_continues(self):self.run_fixture()
    def test_post_execution_stale_schedule_rejected(self):self.run_fixture(stale=True)
    def test_partial_priority_opt_in_rejected(self):
        with self.assertRaises(ValueError):
            r.run(None,None,'p','j','reviewer','p1','s1','a1','b1','RUN ACCEPTANCE ASSERTIONS j',
                  image=None,priority_comparison='baseline_to_B')
if __name__=='__main__':unittest.main()
