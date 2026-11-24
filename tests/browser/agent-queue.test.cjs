const {test}=require('node:test');const assert=require('node:assert/strict');const {chromium}=require('playwright');const {login,headers,ORIGIN}=require('./auth-helper.cjs');
test('persistent queue UI executes pipeline, history and coding dependency',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
 const owner=await browser.newPage(),viewer=await browser.newPage();const csrf=await login(owner);const vc=await login(viewer,'ci-viewer');
 const made=await owner.request.post(ORIGIN+'/api/projects',{headers:headers(csrf),data:{name:'Queue fixture',idea:'Persistent queue project fixture',platform:'Web app'}});
 assert.equal(made.status(),201);const pid=(await made.json()).project_id;
 const path=ORIGIN+'/api/projects/'+pid+'/queue';
 assert.equal((await viewer.request.get(path)).status(),403);
 await owner.goto(ORIGIN+'/queue.html');await owner.locator('#filters').waitFor({state:'visible'});await owner.locator('#project').selectOption(pid);await owner.locator('#submit-panel').waitFor({state:'visible'});
 await owner.locator('#priority').fill('9');await owner.getByRole('button',{name:'Đưa vào hàng đợi'}).click();
 await owner.waitForFunction(()=>document.querySelector('#tasks').textContent.includes('succeeded'),null,{timeout:20000});
 const first=(await (await owner.request.get(path)).json()).tasks[0];assert.equal(first.status,'succeeded');assert.equal(first.priority,9);
 await owner.getByRole('button',{name:'History'}).first().click();await owner.getByText('claimed',{exact:false}).waitFor();
 const code=await owner.request.post(ORIGIN+'/api/coding/start',{headers:headers(csrf),data:{project_id:pid,spec:'Implement a demo queue dependent web feature',dependency_id:first.id,priority:7}});
 assert.equal(code.status(),202);const {queue_id,job_id}=await code.json();
 await owner.waitForFunction(async({pid,id})=>{const r=await fetch('/api/projects/'+pid+'/queue');const d=await r.json();return d.tasks.find(t=>t.id===id)?.status==='succeeded'},{pid,id:queue_id},{timeout:20000});
 const job=await (await owner.request.get(ORIGIN+'/api/coding/'+job_id)).json();assert.equal(job.status,'ready');
 assert.equal((await viewer.request.post(path+'/'+first.id+'/cancel',{headers:headers(vc),data:{}})).status(),403);
 }finally{await browser.close()}
});
