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

def fixture_chat(lane,system,user,*,usage_observer=None,schema=None,**kwargs):
    data=json.loads(user)
    idea=data.get('idea','')
    if schema is discovery.RESEARCH_SCHEMA:
        result=dict(audience=['Readers'],needs=['Save links'],hypotheses=[],unknowns=[])
    elif schema is discovery.BA_SCHEMA:
        result=dict(workflows=['Save and list'],business_rules=['Project access'],edge_cases=['Denied read'],unknowns=[])
    elif schema in (discovery.REVIEW_SCHEMA,discovery.BRIEF_REVIEW_SCHEMA):
        result=dict(blocking=['Missing scope'] if 'BLOCK_FIXTURE' in idea and 'synthesized document' in system else [],feedback=['Synthetic browser fixture review'])
    elif schema is planning.SCHEMA:
        result=dict(objective='Fixture plan',work=[dict(requirement=r['id'],implement='Implement '+r['description'],verify='Verify '+r['acceptance'][0]) for r in data['document']['requirements']])
    elif isinstance(schema,dict) and data.get('targets') and 'used_details' in data:
        # Synthetic browser-only responses. Real offline acceptance uses native Ollama.
        details={
            'D-1.1':dict(action='Persist URL with the authorized project identifier',output='Project scoped URL write handler',evidence='Database write test record'),
            'D-1.2':dict(action='Test saved URL retrieval in the project list',output='URL retrieval integration test',evidence='Returned list includes saved URL'),
            'D-2.1':dict(action='Filter link reads by authenticated project membership',output='Membership access guard for link queries',evidence='Authorization code review checklist'),
            'D-2.2':dict(action='Test another project member requesting a foreign URL',output='Cross project denial integration test',evidence='Denied response without link payload')}
        result={key:details[key.rsplit('.',1)[0]][key.rsplit('.',1)[1]] for key in schema['required']}
    elif schema is discovery.DOCUMENT_SCHEMA:
        result=model_document()
    else:
        raise RuntimeError('Unexpected fixture inference; no real provider permitted')
    if usage_observer:usage_observer(dict(input_tokens=20,output_tokens=30,total_tokens=50,coverage='complete',source='fixture',status='ok',elapsed_ms=1))
    return json.dumps(result)

mp.chat=fixture_chat
import server
import auth_store
server.init_db()
with server.db() as c:
    for user in ('ci-browser-user','ci-viewer','ci-reviewer','ci-developer'):
        auth_store.create_user(c,user,'local-ci-fixture-password')
server.main()
