"""Isolated browser fixture: real HTTP, queue and storage; synthetic model transport.
Never use as a production server or as real-AI evidence.
"""
import json
import os
import sys
from pathlib import Path
if os.environ.get('ORBIT_REQUIREMENTS_BROWSER_FIXTURE')!='1':
    raise SystemExit('Explicit isolated browser fixture opt-in required')
root=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'backend'))
sys.path.insert(0,str(root/'tests'))
from test_requirements_discovery import model_document
import model_provider as mp
import requirements_discovery as discovery
import planning_discovery as planning
import planning_review as review
import coding_factory as coding

def fixture_chat(lane,system,user,*,usage_observer=None,schema=None,**kwargs):
    # Coding prompts are text, unlike planning JSON packets. Fixed trusted
    # source only; no actual model transport or generated-code execution.
    if schema is coding.PROPOSAL_SCHEMA or schema is coding.REVIEW_SCHEMA:
        if schema is coding.PROPOSAL_SCHEMA:
            result=dict(summary='Synthetic coding fixture '+lane.lane,files=[dict(path='main.py',content='def add(a,b):\n    return a+b\n'),dict(path='test_main.py',content='import unittest\nfrom main import add\nclass T(unittest.TestCase):\n    def test_add(self):\n        self.assertEqual(add(2,3),5)\n')])
        else:result=dict(verdict='APPROVE',score=90,feedback='Synthetic fixture review only')
        if usage_observer:usage_observer(dict(input_tokens=20,output_tokens=30,total_tokens=50,coverage='complete',source='fixture',status='ok',elapsed_ms=1))
        return json.dumps(result)
    data=json.loads(user)
    idea=data.get('idea','')
    if schema is discovery.RESEARCH_SCHEMA:
        result=dict(audience=['Readers'],needs=['Save links'],hypotheses=[],unknowns=[])
    elif schema is discovery.BA_SCHEMA:
        result=dict(workflows=['Save and list'],business_rules=['Project access'],edge_cases=['Denied read'],unknowns=[])
    elif schema in (discovery.REVIEW_SCHEMA,discovery.BRIEF_REVIEW_SCHEMA):
        result=dict(blocking=['Missing scope'] if 'BLOCK_FIXTURE' in idea and 'synthesized document' in system else [],feedback=['Synthetic browser fixture review'])
    elif schema is review.SCHEMA:
        assert data['reviewer']=='PM-'+lane.lane and data['author']!=data['reviewer'] and 'proposals' not in data
        result=dict(verdict='APPROVE',score=90,feedback='Synthetic fixture reviewed five dimensions',checks={k:True for k in review.DIMENSIONS})
    elif schema is planning.SCHEMA:
        result=dict(objective='Fixture plan',work=[dict(requirement=r['id'],implement='Implement '+r['description'],verify='Verify '+r['acceptance'][0]) for r in data['document']['requirements']])
    elif isinstance(schema,dict) and data.get('targets') and data.get('protocol')=='orbit.wbs-isolated-context.v1':
        # Synthetic browser-only responses. Real offline acceptance uses native Ollama.
        details={
            'D-1.1':dict(action='Persist URL with the authorized project identifier',output='Project scoped URL write handler',evidence='Database write test record'),
            'D-1.2':dict(action='Test saved URL retrieval in the project list',output='URL retrieval integration test',evidence='Returned list includes saved URL'),
            'D-2.1':dict(action='Filter link reads by authenticated project membership',output='Membership access guard for link queries',evidence='Authorization code review checklist'),
            'D-2.2':dict(action='Test another project member requesting a foreign URL',output='Cross project denial integration test',evidence='Denied response without link payload')}
        result={key:details[key.rsplit('.',1)[0]][key.rsplit('.',1)[1]] for key in schema['required']}
        # Only the explicitly marked fixture's B lane fails; never use live transport.
        if lane.lane=='B' and any('fixture blocked lane' in x.lower() for x in data.get('forbidden',[])):
            result={}
    elif schema is discovery.DOCUMENT_SCHEMA:
        result=model_document()
    else:
        raise RuntimeError('Unexpected fixture inference; no real provider permitted')
    if usage_observer:usage_observer(dict(input_tokens=20,output_tokens=30,total_tokens=50,coverage='complete',source='fixture',status='ok',elapsed_ms=1))
    return json.dumps(result)

if __name__=='__main__':
    mp.chat=fixture_chat
    import server
    import auth_store
    server.init_db()
    with server.db() as c:
        for user in ('ci-browser-user','ci-viewer','ci-reviewer','ci-developer'):
            auth_store.create_user(c,user,'local-ci-fixture-password')
    server.main()
