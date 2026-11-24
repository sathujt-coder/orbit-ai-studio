const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {login,headers,ORIGIN}=require('./auth-helper.cjs');
test('HTTP denies anonymous access, cross-project reads, role escalation and missing CSRF',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const owner=await browser.newPage(),viewer=await browser.newPage(),anon=await browser.newPage();
 assert.equal((await anon.request.get(ORIGIN+'/api/bootstrap')).status(),401);
 await anon.goto(ORIGIN+'/');assert.ok(anon.url().endsWith('/account.html'));
 const oc=await login(owner),vc=await login(viewer,'ci-viewer');
 const visible=(await (await viewer.request.get(ORIGIN+'/api/bootstrap')).json()).projects;
 assert.equal(visible.length,1);const shared=visible[0].id;
 const made=await owner.request.post(ORIGIN+'/api/projects',{headers:headers(oc),data:{name:'Private security project',idea:'Independent access isolation test',platform:'Web app'}});
 assert.equal(made.status(),201);const pid=(await made.json()).project_id;
 assert.equal((await viewer.request.get(ORIGIN+'/api/projects/'+pid+'/state')).status(),403);
 assert.equal((await viewer.request.post(ORIGIN+'/api/coding/start',{headers:headers(vc),data:{project_id:shared,spec:'Disallowed viewer coding operation'}})).status(),403);
 assert.equal((await viewer.request.post(ORIGIN+'/api/projects/'+shared+'/members',{headers:headers(vc),data:{user:'ci-viewer',role:'owner'}})).status(),403);
 assert.equal((await owner.request.post(ORIGIN+'/api/projects/'+shared+'/members',{headers:headers(oc),data:{user:'ci-viewer',role:'owner'}})).status(),403);
 assert.equal((await owner.request.post(ORIGIN+'/api/projects',{headers:{Origin:ORIGIN,'Content-Type':'application/json','X-ORBIT-UI':'1'},data:{name:'Denied',idea:'Missing CSRF token test'}})).status(),403);
 const audit=await (await owner.request.get(ORIGIN+'/api/projects/'+shared+'/audit')).json();
 assert.ok(audit.audit.some(x=>x.actor==='ci-viewer'&&x.outcome==='denied'));
 }finally{await browser.close()}
});
