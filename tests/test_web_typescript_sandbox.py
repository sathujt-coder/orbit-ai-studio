import sys
from pathlib import Path
import subprocess
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from coding_factory import validate_proposal
from test_verification_factory import job
import web_typescript_sandbox as web

IMAGE='node-ts-toolchain@sha256:'+'a'*64

def proposal(source='export function add(a:number,b:number):number{return a+b}'):
    return validate_proposal({'summary':'Web TS candidate','files':[
      {'path':'tsconfig.json','content':'{"compilerOptions":{"strict":true,"noEmit":true}}'},
      {'path':'src/add.ts','content':source},
      {'path':'src/add.test.ts','content':'import {test} from "node:test"; test("add",()=>{});'}]})

class FakeRunner:
    def __init__(self): self.calls=[]
    def __call__(self,argv,**kw):
        self.calls.append(argv)
        output='# tests 2\n' if 'tsx' in argv else ''
        return subprocess.CompletedProcess(argv,0,output,'')

class WebSandboxTests(unittest.TestCase):
    def test_both_lanes_run_offline(self):
        fake=FakeRunner()
        r=web.verify_web(job(proposal(),proposal()),image=IMAGE,approval='RUN WEB SANDBOX job-abc',runner=fake)
        self.assertEqual(r['gate'],'PASS')
        self.assertEqual(len(fake.calls),4)
        self.assertTrue(all('--network' in a and a[a.index('--network')+1]=='none' for a in fake.calls))
        self.assertTrue(all('--read-only' in a for a in fake.calls))

    def test_requires_human_approval(self):
        f=FakeRunner()
        with self.assertRaises(PermissionError): web.verify_web(job(proposal(),proposal()),image=IMAGE,approval='yes',runner=f)
        self.assertEqual(f.calls,[])

    def test_missing_test_blocks_without_docker(self):
        p=validate_proposal({'files':[{'path':'tsconfig.json','content':'{}'},{'path':'src/a.ts','content':'export const a=1;'}]})
        f=FakeRunner()
        r=web.verify_web(job(p,p),image=IMAGE,approval='RUN WEB SANDBOX job-abc',runner=f)
        self.assertEqual(r['gate'],'BLOCK');self.assertEqual(f.calls,[])

    def test_react_dependency_blocks(self):
        p=proposal('import React from "react"; export const A = () => 1;')
        self.assertIn('REACT_DEPENDENCIES_NOT_AUDITED',web.plan_web(p)['blockers'])

    def test_package_install_blocks(self):
        p=proposal();p['files'].append({'path':'package.json','content':'{}','sha256':'x'})
        self.assertIn('DEPENDENCY_INSTALL_NOT_SUPPORTED',web.plan_web(p)['blockers'])

    def test_unpinned_image_blocks(self):
        with self.assertRaises(ValueError):
            web.verify_web(job(proposal(),proposal()),image='node:latest',approval='RUN WEB SANDBOX job-abc',runner=FakeRunner())

    def test_privileged_code_blocks(self):
        p=proposal('import {exec} from "child_process";')
        self.assertIn('PRIVILEGED_CODE_PATTERN',web.plan_web(p)['blockers'])

if __name__=='__main__':unittest.main()
