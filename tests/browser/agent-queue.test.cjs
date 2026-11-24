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
 // Poll via one HTTP client with explicit no-cache and assert a single database
 // snapshot first. A succeeded queue with a non-ready coding row is a hard failure.
 let snapshot=null;
 const deadline=Date.now()+20000;
 while(Date.now()<deadline){
  const r=await owner.request.get(path+'?check='+Date.now(),{headers:{'Cache-Control':'no-cache'}});
  assert.equal(r.status(),200);
  const d=await r.json();snapshot=d.tasks.find(t=>t.id===queue_id);
  if(snapshot?.status==='succeeded'){assert.equal(snapshot.coding_job_id,job_id);assert.equal(snapshot.coding_status,'ready');break}
  assert.ok(!['dead','cancelled','interrupted'].includes(snapshot?.status),JSON.stringify(snapshot));
  await new Promise(resolve=>setTimeout(resolve,100));
 }
 assert.equal(snapshot?.status,'succeeded',JSON.stringify(snapshot));
 const response=await owner.request.get(ORIGIN+'/api/coding/'+job_id+'?check='+Date.now(),{headers:{'Cache-Control':'no-cache'}});
 assert.equal(response.status(),200);
 const job=await response.json();assert.equal(job.id,job_id);assert.equal(job.status,'ready',JSON.stringify({queue:snapshot.status,coding:job.status,id:job.id}));
 assert.equal((await viewer.request.post(path+'/'+first.id+'/cancel',{headers:headers(vc),data:{}})).status(),403);
 }finally{await browser.close()}
});
