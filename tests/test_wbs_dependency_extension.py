import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import wbs_dependency_extension as ext
import project_planning as pp

class ExtensionTests(unittest.TestCase):
    def setUp(self):
        packages=[dict(id='A',kind='implement',depends_on=[]),dict(id='B',kind='implement',depends_on=[]),dict(id='V',kind='verify',depends_on=['B'])]
        self.bundle=dict(wbs=dict(version=1,digest='w',document=dict(deliverables=[dict(packages=packages)])),
            estimates=dict(version=1,digest='e',document=dict(packages=[dict(id=p['id'],effort_minutes=15,role='Dev') for p in packages])),
            schedule=dict(version=1,digest='s',document=dict(sprints=[dict(id='S',start='2026-12-01',end='2026-12-07',capacity=dict(Dev=45))],assignments=[dict(id=p['id'],sprint='S') for p in packages],milestones=[dict(id='M',title='Done',sprint='S',packages=['A','B','V'])])),
            dependency_graph=dict(schema='original'))
        self.row=dict(version=1,digest='a',bundle_digest='b',review_id='r',evidence_digest='e')
        self.edge=dict(source='A',target='B',rationale='Reviewed implementation ordering requirement.')
    def test_additive_graph_and_immutable_base(self):
        before=copy.deepcopy(self.bundle)
        result=ext.build('p',self.row,self.bundle,[self.edge])
        self.assertEqual(result['effective_graph']['critical_path_minutes'],45)
        self.assertEqual(result['effective_graph']['edge_count'],2)
        self.assertEqual(result['review_scope'],'original_bundle_only')
        self.assertFalse(result['execution_authorized'])
        self.assertEqual(self.bundle,before)
    def test_cycle_duplicate_and_verify_rejection(self):
        for edges in ([self.edge,self.edge],[self.edge,dict(self.edge,source='B',target='A')],[dict(self.edge,source='V')],[dict(self.edge,target='unknown')]):
            with self.subTest(edges=edges),self.assertRaises(ValueError):ext.build('p',self.row,self.bundle,edges)
    def test_schedule_conflict(self):
        doc=self.bundle['schedule']['document']
        doc['sprints'].append(dict(id='T',start='2026-12-08',end='2026-12-14',capacity=dict(Dev=45)))
        doc['assignments'][0]['sprint']='T'
        doc['milestones'][0]['sprint']='T'
        with self.assertRaisesRegex(ValueError,'schedule'):ext.build('p',self.row,self.bundle,[self.edge])
