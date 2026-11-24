const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {login,headers,ORIGIN}=require('./auth-helper.cjs');
test('P6.1 real Chromium and HTTP with synthetic inference: queue, adoption, approval, RBAC and stale guards',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const owner=await browser.newPage(),viewer=await browser.newPage(),reviewer=await browser.newPage(),developer=await browser.newPage();
  const csrf=await login(owner),vc=await login(viewer,'ci-viewer'),rc=await login(reviewer,'ci-reviewer'),dc=await login(developer,'ci-developer');
  const post=(page,token,path,data)=>page.request.post(ORIGIN+path,{headers:headers(token),data});
  const get=async(page,path)=>{const r=await page.request.get(ORIGIN+path);assert.equal(r.status(),200);return r.json()};
  const make=async(name,idea='Save and list links in isolated projects')=>{const r=await post(owner,csrf,'/api/projects',{name,idea,platform:'Web app'});assert.equal(r.status(),201);return (await r.json()).project_id};
  const pid=await make('Requirements browser fixture'),other=await make('Other private project');
  const path='/api/projects/'+pid+'/requirements';
  for(const [user,role] of [['ci-viewer','viewer'],['ci-reviewer','reviewer'],['ci-developer','developer']])
   assert.equal((await post(owner,csrf,'/api/projects/'+pid+'/members',{user,role})).status(),200);
  assert.equal((await viewer.request.get(ORIGIN+'/api/projects/'+other+'/requirements')).status(),403);
  assert.equal((await post(viewer,vc,path+'/discover',{confirmation:'RUN AI REQUIREMENTS'})).status(),403);
  assert.equal((await post(reviewer,rc,path+'/discover',{confirmation:'RUN AI REQUIREMENTS'})).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),path+'/discover',{confirmation:'RUN AI REQUIREMENTS'})).status(),403);
  assert.equal((await post(owner,csrf,path+'/discover',{confirmation:'wrong'})).status(),400);
  await owner.goto(ORIGIN+'/requirements.html');await owner.locator('#panel').waitFor({state:'visible'});
  await owner.locator('#project').selectOption(pid);await owner.locator('#panel').waitFor({state:'visible'});
  await owner.waitForFunction(()=>!document.querySelector('#discover').disabled);
  owner.on('dialog',d=>d.accept());
  await owner.locator('#discover').click();
  await owner.waitForFunction(()=>document.querySelector('#discovery-status').textContent.includes('succeeded'),null,{timeout:30000});
  let data=await get(owner,path);assert.equal(data.planning_ready,false);assert.equal(data.current,null);assert.equal(data.discovery.can_adopt,true);
  assert.equal(data.discovery.evidence.collaboration.research_mode,'input_analysis_only');
  assert.ok((await get(owner,'/api/projects/'+pid+'/queue')).tasks.some(t=>t.id===data.discovery.queue_id&&t.kind==='requirements'&&t.status==='succeeded'));
  const adopt={queue_id:data.discovery.queue_id,digest:data.discovery.digest,expected_version:0,confirmation:'ADOPT AI REQUIREMENTS'};
  assert.equal((await post(viewer,vc,path+'/adopt',adopt)).status(),403);
  assert.equal((await post(owner,csrf,path+'/adopt',{...adopt,digest:'wrong'})).status(),400);
  const original=await owner.locator('#document').inputValue();
  await owner.locator('#document').fill(original+' ');
  await owner.locator('#adopt').click();
  await owner.waitForFunction(()=>document.querySelector('#status').textContent.includes('chỉnh sửa chưa lưu'));
  await owner.locator('#document').fill(original);
  await owner.locator('#adopt').click();
  await owner.waitForFunction(()=>document.querySelector('#version').textContent.includes('Version 1'));
  data=await get(owner,path);assert.equal(data.current.source,'ai_adopted');assert.equal(data.planning_ready,false);
  assert.equal((await post(owner,csrf,path+'/adopt',adopt)).status(),400);
  const approval={version:1,digest:data.current.digest,confirmation:'APPROVE PRODUCT REQUIREMENTS'};
  assert.equal((await post(developer,dc,path+'/approve',approval)).status(),403);
  assert.equal((await post(reviewer,rc,path+'/approve',{...approval,digest:'wrong'})).status(),400);
  await reviewer.goto(ORIGIN+'/requirements.html');await reviewer.locator('#panel').waitFor({state:'visible'});
  assert.equal(await reviewer.locator('#save').isDisabled(),true);assert.equal(await reviewer.locator('#discover').isDisabled(),true);
  reviewer.on('dialog',d=>d.accept());await reviewer.locator('#approve').click();
  await reviewer.waitForFunction(()=>document.querySelector('#version').textContent.includes('Đã duyệt'));
  data=await get(owner,path);assert.equal(data.planning_ready,true);assert.equal(data.current.approved_by,'ci-reviewer');
  await owner.locator('#reload').click();await owner.waitForFunction(()=>document.querySelector('#version').textContent.includes('Đã duyệt'));
  await owner.locator('#save').click();await owner.waitForFunction(()=>document.querySelector('#version').textContent.includes('Version 2'));
  data=await get(owner,path);assert.equal(data.planning_ready,false);
  assert.equal((await post(reviewer,rc,path+'/approve',approval)).status(),400);
  // Stale discovery: another revision is saved after discovery begins.
  const start=await post(owner,csrf,path+'/discover',{confirmation:'RUN AI REQUIREMENTS'});assert.equal(start.status(),202);
  await owner.waitForFunction(()=>document.querySelector('#discovery-status').textContent.includes('succeeded'),null,{timeout:30000});
  const id=(await start.json()).queue_id;
  let latest;
  for(let i=0;i<100;i++){latest=await get(owner,path);if(latest.discovery.queue_id===id&&latest.discovery.status==='succeeded')break;await new Promise(r=>setTimeout(r,100))}
  assert.equal(latest.discovery.queue_id,id);assert.equal(latest.discovery.status,'succeeded');
  assert.equal((await post(owner,csrf,path,{expected_version:2,document:latest.current.document})).status(),200);
  assert.equal((await post(owner,csrf,path+'/adopt',{queue_id:id,digest:latest.discovery.digest,expected_version:2,confirmation:'ADOPT AI REQUIREMENTS'})).status(),400);
  const blocked=await make('Blocked fixture','BLOCK_FIXTURE: Save and list links');
  const bp='/api/projects/'+blocked+'/requirements';assert.equal((await post(owner,csrf,bp+'/discover',{confirmation:'RUN AI REQUIREMENTS'})).status(),202);
  let b;
  for(let i=0;i<100;i++){b=await get(owner,bp);if(b.discovery?.status==='dead')break;await new Promise(r=>setTimeout(r,100))}
  assert.equal(b.discovery.status,'dead');assert.equal(b.discovery.can_adopt,false);assert.equal(b.current,null);
  assert.equal((await post(owner,csrf,bp+'/adopt',{queue_id:b.discovery.queue_id,digest:b.discovery.digest,expected_version:0,confirmation:'ADOPT AI REQUIREMENTS'})).status(),400);
 }finally{await browser.close()}
});
