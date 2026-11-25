const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {login,headers,ORIGIN}=require('./auth-helper.cjs');

test('P6.2a planning WBS, approval, RBAC and stale PRD via real Chromium/HTTP',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const owner=await browser.newPage(),reviewer=await browser.newPage(),viewer=await browser.newPage(),dev=await browser.newPage();
  const csrf=await login(owner),rc=await login(reviewer,'ci-reviewer'),vc=await login(viewer,'ci-viewer'),dc=await login(dev,'ci-developer');
  const post=(page,token,path,data)=>page.request.post(ORIGIN+path,{headers:headers(token),data});
  const get=async(page,path)=>{const r=await page.request.get(ORIGIN+path);assert.equal(r.status(),200);return r.json()};
  const made=await post(owner,csrf,'/api/projects',{name:'Planning test',idea:'Save links securely',platform:'Web app'});
  assert.equal(made.status(),201);const pid=(await made.json()).project_id;
  const privateProject=await post(owner,csrf,'/api/projects',{name:'Private planning',idea:'Private',platform:'Web app'});
  const other=(await privateProject.json()).project_id;
  for(const [user,role] of [['ci-reviewer','reviewer'],['ci-viewer','viewer'],['ci-developer','developer']])
    assert.equal((await post(owner,csrf,'/api/projects/'+pid+'/members',{user,role})).status(),200);
  const rp='/api/projects/'+pid+'/requirements',pp='/api/projects/'+pid+'/planning';
  assert.equal((await viewer.request.get(ORIGIN+'/api/projects/'+other+'/planning')).status(),403);
  assert.equal((await get(owner,pp)).input_ready,false);
  assert.equal((await post(owner,csrf,pp+'/seed',{expected_version:0,requirements_version:1,requirements_digest:'bad',confirmation:'CREATE PLAN DRAFT'})).status(),400);
  const doc={problem:'Save useful links',goals:['Retrieve links'],users:['Readers'],scope:['Web'],out_of_scope:['Mobile'],assumptions:[],open_questions:[],
   requirements:[{id:'REQ-1',kind:'functional',description:'Save URL',priority:'must',acceptance:['Saved URL listed']},{id:'REQ-2',kind:'nonfunctional',description:'Project isolation',priority:'must',acceptance:['Other project cannot read links']}],
   stories:[{id:'US-1',actor:'Reader',goal:'Save links securely',benefit:'Find links later',requirements:['REQ-1','REQ-2']}]};
  let saved=await post(owner,csrf,rp,{expected_version:0,document:doc});assert.equal(saved.status(),200);
  let req=(await saved.json()).current;
  const seed={expected_version:0,requirements_version:req.version,requirements_digest:req.digest,confirmation:'CREATE PLAN DRAFT'};
  assert.equal((await post(owner,csrf,pp+'/seed',seed)).status(),400);
  assert.equal((await post(reviewer,rc,rp+'/approve',{version:req.version,digest:req.digest,confirmation:'APPROVE PRODUCT REQUIREMENTS'})).status(),200);
  assert.equal((await post(viewer,vc,pp+'/seed',seed)).status(),403);
  assert.equal((await post(reviewer,rc,pp+'/seed',seed)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),pp+'/seed',seed)).status(),403);
  owner.on('dialog',d=>d.accept());
  await owner.goto(ORIGIN+'/planning.html');await owner.locator('#panel').waitFor({state:'visible'});
  await owner.locator('#project').selectOption(pid);
  await owner.waitForFunction(()=>!document.querySelector('#seed').disabled);
  const discovery={requirements_version:req.version,requirements_digest:req.digest,confirmation:'RUN AI PLANNING'};
  assert.equal((await post(viewer,vc,pp+'/discover',discovery)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),pp+'/discover',discovery)).status(),403);
  await owner.locator('#discover').click();
  await owner.waitForFunction(()=>document.querySelector('#discovery-status').textContent.includes('succeeded'),null,{timeout:30000});
  const proposed=await get(owner,pp);assert.equal(proposed.discovery.ready,true);
  assert.deepEqual(Object.keys(proposed.discovery.evidence.proposals).sort(),['A','B']);
  assert.equal(proposed.current,null);assert.equal(proposed.execution_ready,false);
  await owner.locator('#seed').click();await owner.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('Plan v1'));
  let data=await get(owner,pp);assert.equal(data.execution_ready,false);assert.equal(data.analysis.task_count,4);
  assert.equal(await owner.locator('#tasks tr').count(),4);
  const approval={version:1,digest:data.current.digest,requirements_version:req.version,requirements_digest:req.digest,confirmation:'APPROVE PROJECT PLAN'};
  assert.equal((await post(reviewer,rc,pp+'/approve',approval)).status(),400);
  let estimated=data.current.document;for(const task of estimated.tasks)task.effort_minutes=15;
  await owner.locator('#document').fill(JSON.stringify(estimated));
  await owner.locator('#save').click();await owner.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('Plan v2'));
  data=await get(owner,pp);assert.equal(data.analysis.total_effort_minutes,60);
  const ready={...approval,version:2,digest:data.current.digest};
  assert.equal((await post(dev,dc,pp+'/approve',ready)).status(),403);
  reviewer.on('dialog',d=>d.accept());
  await reviewer.goto(ORIGIN+'/planning.html');await reviewer.locator('#panel').waitFor({state:'visible'});
  await reviewer.locator('#project').selectOption(pid);await reviewer.waitForFunction(()=>!document.querySelector('#approve').disabled);
  assert.equal(await reviewer.locator('#save').isDisabled(),true);
  await reviewer.locator('#approve').click();await reviewer.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('READY'));
  assert.equal((await get(owner,pp)).execution_ready,true);
  assert.equal((await post(owner,csrf,rp,{expected_version:1,document:doc})).status(),200);
  await owner.locator('#reload').click();await owner.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('STALE'));
  assert.equal((await get(owner,pp)).execution_ready,false);
  assert.equal(await owner.locator('#seed').isDisabled(),true);
  assert.equal((await post(owner,csrf,pp+'/seed',{...seed,expected_version:2})).status(),400);
 }finally{await browser.close()}
});