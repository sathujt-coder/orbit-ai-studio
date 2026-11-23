"""Execute real Docker TypeScript/TSX tests for both DEV lanes.

This fixture is handwritten and trusted. It is NOT an AI-generated feature.
The Docker image is built in CI, then referenced by its immutable local ID.
"""
from pathlib import Path
import json
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'backend'))
from coding_factory import validate_proposal
from web_typescript_sandbox import verify_web
from test_verification_factory import job

def proposal(offset):
    return validate_proposal({'summary':'Independent Web candidate', 'files':[
        {'path':'tsconfig.json','content':json.dumps({'compilerOptions':{
            'strict':True,'noEmit':True,'target':'ES2022','module':'ESNext',
            'moduleResolution':'Bundler','allowImportingTsExtensions':True,'types':[]}})},
        {'path':'src/math.ts','content':f'export function add(a: number, b: number): number {{ return a + b + {offset}; }}\n'},
        {'path':'src/math.test.ts','content':
         '// @ts-ignore: node built-in types are not included in the offline fixture\n'
         'import { test } from "node:test";\n'
         '// @ts-ignore: node built-in types are not included in the offline fixture\n'
         'import { strictEqual } from "node:assert";\n'
         'import { add } from "./math.ts";\n'
         f'test("candidate arithmetic", () => strictEqual(add(1, 2), {3+offset}));\n'}
    ]})

def main():
    image=subprocess.check_output(['docker','image','inspect','--format','{{.Id}}','orbit-web-ts:ci'],text=True).strip()
    result=verify_web(job(proposal(0),proposal(1)),image=image,
                      approval='RUN WEB SANDBOX job-abc',timeout=50)
    safe={'gate':result['gate'],'verdict':result['verdict'],
          'lanes':{k:{'status':v['status'],
                       'steps':[{'step':t['step'],'passed':t['passed'],'test_count':t.get('test_count'),
                                 'output':t.get('output','')[-500:]} for t in v['steps']]}
                   for k,v in result['lanes'].items()}}
    print(json.dumps(safe,indent=2))
    if result['gate']!='PASS':
        raise SystemExit('Real Docker TypeScript smoke test failed')
if __name__=='__main__':main()
