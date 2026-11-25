"""P6.2e deterministic graph regression; no model calls."""
import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import dependency_graph as g

def node(tid,minutes,*deps):
    return dict(id=tid,effort_minutes=minutes,depends_on=list(deps))

class DependencyGraphTests(unittest.TestCase):
    def test_diamond_with_tied_critical_paths_and_shorter_branch(self):
        nodes=[node('A',2),node('B',5,'A'),node('C',5,'A'),node('D',1,'A'),
               node('E',3,'B','C','D'),node('F',4)]
        graph=g.analyze(nodes)
        self.assertEqual(graph['critical_path_minutes'],10)
        self.assertEqual(graph['critical_path'],['A','B','E'])
        self.assertEqual(graph['critical_nodes'],['A','B','C','E'])
        self.assertEqual({(e['source'],e['target']) for e in graph['critical_edges']},
                         {('A','B'),('A','C'),('B','E'),('C','E')})
        rows={n['id']:n for n in graph['nodes']}
        self.assertEqual(rows['D']['total_float_minutes'],4)
        self.assertEqual(rows['F']['total_float_minutes'],6)
        self.assertEqual(rows['E']['earliest_start_minutes'],7)
        self.assertEqual(rows['C']['latest_finish_minutes'],7)
        self.assertEqual(graph['layers'],[['A','F'],['B','C','D'],['E']])
        self.assertFalse(graph['schedule_committed'])

    def test_zero_float_nodes_do_not_imply_every_edge_is_critical(self):
        graph=g.analyze([node('A',2),node('B',3,'A'),node('C',4,'A','B')])
        self.assertEqual(graph['critical_path'],['A','B','C'])
        self.assertNotIn(dict(source='A',target='C'),graph['critical_edges'])

    def test_missing_estimates_suppress_all_timing(self):
        graph=g.analyze([node('A',None),node('B',3,'A'),node('C',4)])
        self.assertFalse(graph['timing_ready'])
        self.assertEqual(graph['unestimated_nodes'],['A'])
        self.assertEqual(graph['execution_order'],['A','C','B'])
        for key in ('critical_path_minutes','critical_path','critical_nodes','critical_edges'):
            self.assertIsNone(graph[key])
        for n in graph['nodes']:
            for key in ('earliest_start_minutes','earliest_finish_minutes','latest_start_minutes',
                        'latest_finish_minutes','total_float_minutes','critical'):
                self.assertIsNone(n[key])

    def test_deterministic_without_mutation(self):
        nodes=[node('A',3),node('B',3),node('C',2,'B','A')]
        original=copy.deepcopy(nodes)
        self.assertEqual(g.analyze(nodes),g.analyze(list(reversed(nodes))))
        self.assertEqual(nodes,original)

    def test_disconnected_equal_sinks_and_single_node(self):
        graph=g.analyze([node('A',2),node('B',2)])
        self.assertEqual(graph['critical_nodes'],['A','B'])
        self.assertEqual(graph['critical_path'],['A'])
        self.assertEqual(graph['critical_edges'],[])
        self.assertEqual(g.analyze([node('X',7)])['critical_path_minutes'],7)

    def test_malformed_graphs_rejected(self):
        for nodes in ([],[node('A',1,'B')],[node('A',1,'A')],
                      [node('A',1,'B'),node('B',2,'A')],
                      [node('A',1),node('A',2)],
                      [node('A',1),node('B',1,'A','A')],
                      [node('A',True)],[node('A',0)],[node('A',60001)],
                      [node(str(i),1) for i in range(151)]):
            with self.subTest(nodes=nodes[:3]):
                with self.assertRaises(ValueError):g.analyze(nodes)

    def test_dense_tied_graph_does_not_enumerate_paths(self):
        nodes=[];previous=[]
        for layer in range(50):
            current=['%02d-%s'%(layer,k) for k in 'ABC']
            nodes.extend(node(tid,1,*previous) for tid in current)
            previous=current
        graph=g.analyze(nodes)
        self.assertEqual(graph['node_count'],150)
        self.assertEqual(graph['critical_path_minutes'],50)
        self.assertEqual(len(graph['critical_nodes']),150)
        self.assertEqual(len(graph['critical_edges']),49*9)
        self.assertEqual(len(graph['critical_path']),50)
