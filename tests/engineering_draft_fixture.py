"""Isolated GitHub API contract fixture: never sends network requests."""
import base64
from engineering_draft import DraftClient, ws

class FakeRemote(DraftClient):
    def __init__(self,repo='example/orbit',base='main',base_sha='a'*40):
        self.repo,self.base,self.base_sha=repo,base,base_sha
        self.calls=[];self.entries=[];self.tree='b'*40;self.head='d'*40
    def request(self,method,route,payload=None):
        self.calls.append((method,route,payload))
        if method=='GET' and '/branches/' in route:return {'commit':{'sha':self.base_sha}}
        if method=='GET' and '/git/commits/' in route:return {'sha':self.base_sha,'tree':{'sha':self.tree}}
        if method=='GET' and '/git/trees/' in route:
            original=[dict(path='README.md',mode='100644',type='blob',sha='e'*40)]
            return dict(truncated=False,tree=original+(self.entries if '/git/trees/'+'c'*40 in route else []))
        if method=='POST' and route.endswith('/git/blobs'):
            return dict(sha=ws.object_id('blob',base64.b64decode(payload['content'])))
        if method=='POST' and route.endswith('/git/trees'):
            assert payload['base_tree']==self.tree
            self.entries=payload['tree'];return dict(sha='c'*40)
        if method=='POST' and route.endswith('/git/commits'):
            assert payload['parents']==[self.base_sha]
            return dict(sha=self.head,tree={'sha':payload['tree']},parents=[{'sha':self.base_sha}])
        if method=='POST' and route.endswith('/git/refs'):
            return dict(ref=payload['ref'],object={'sha':payload['sha']})
        if method=='POST' and route.endswith('/pulls'):
            assert payload['draft'] is True
            return dict(number=7,draft=True,state='open',merged_at=None,
                head=dict(ref=payload['head'],sha=self.head,repo={'full_name':self.repo}),
                base=dict(ref=payload['base'],sha=self.base_sha,repo={'full_name':self.repo}),
                html_url='https://github.com/'+self.repo+'/pull/7')
        raise AssertionError('Unexpected remote call '+method+' '+route)
