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
  // P6.2c: exact-source WBS drafts, partial detail and explicit save.
  const wb={...proposed.wbs.sources.A,expected_version:0,confirmation:'CREATE WBS DRAFT'};
  assert.equal((await post(viewer,vc,pp+'/wbs/seed',wb)).status(),403);
  assert.equal((await post(reviewer,rc,pp+'/wbs/seed',wb)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),pp+'/wbs/seed',wb)).status(),403);
  assert.equal((await post(owner,csrf,pp+'/wbs/seed',{...wb,proposal_digest:'wrong'})).status(),400);
  await owner.locator('#wbs-seed').click();
  await owner.waitForFunction(()=>document.querySelector('#wbs-status').textContent.includes('WBS v1'));
  let wbs=(await get(owner,pp)).wbs;
  assert.equal(wbs.analysis.deliverable_count,2);assert.equal(wbs.analysis.package_count,4);
  assert.equal(wbs.decomposition_ready,false);
  assert.equal(wbs.dependency_graph.node_count,4);
  assert.equal(wbs.dependency_graph.timing_ready,false);
  await owner.locator('#graph-source').selectOption('wbs');
  await owner.waitForFunction(()=>document.querySelector('#graph-status').textContent.includes('STRUCTURE ONLY'));
  assert.equal(await owner.locator('#graph-nodes tr').count(),4);
  assert.equal(await owner.locator('#graph-layers li').count(),2);
  assert.equal(await owner.locator('#wbs-tree details').count(),2);
  // P6.2d: exercise real HTTP/queue with isolated synthetic provider only.
  const decomposition={wbs_version:wbs.current.version,wbs_digest:wbs.current.digest,confirmation:'RUN AI DECOMPOSITION'};
  assert.equal((await post(viewer,vc,pp+'/wbs/decompose',decomposition)).status(),403);
  assert.equal((await post(reviewer,rc,pp+'/wbs/decompose',decomposition)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),pp+'/wbs/decompose',decomposition)).status(),403);
  assert.equal((await post(owner,csrf,pp+'/wbs/decompose',{...decomposition,wbs_digest:'wrong'})).status(),400);
  await owner.locator('#wbs-decompose').click();
  await owner.waitForFunction(()=>document.querySelector('#decomposition-status').textContent.includes('READY FOR REVIEW'),null,{timeout:30000});
  const generated=await get(owner,pp);
  assert.equal(generated.decomposition.ready,true);
  assert.equal(generated.decomposition.evidence.call_count,2);
  assert.equal(generated.wbs.current.digest,wbs.current.digest);
  assert.equal(generated.wbs.decomposition_ready,false);
  assert.equal(generated.current,null);
  const details=[
    ['Persist URL with the authorized project identifier','Project scoped URL write handler','Database write test record'],
    ['Test saved URL retrieval in the project list','URL retrieval integration test','Returned list includes saved URL'],
    ['Filter link reads by authenticated project membership','Membership access guard for link queries','Authorization code review checklist'],
    ['Test another project member requesting a foreign URL','Cross project denial integration test','Denied response without link payload']
  ];
  let wd=wbs.current.document;
  wd.deliverables.flatMap(d=>d.packages).forEach((p,i)=>{[p.action,p.output,p.evidence]=details[i]});
  await owner.locator('#wbs-document').fill(JSON.stringify(wd));
  await owner.locator('#wbs-save').click();
  await owner.waitForFunction(()=>document.querySelector('#wbs-status').textContent.includes('DETAIL READY · WBS v2'));
  assert.equal((await get(owner,pp)).wbs.decomposition_ready,true);
  assert.equal((await get(owner,pp)).decomposition.stale,true);
  assert.equal((await get(owner,pp)).decomposition.ready,false);
  assert.equal((await get(owner,pp)).current,null);
  // P6.2f/g: real Chromium editor and HTTP persistence, no real inference claim.
  wbs=(await get(owner,pp)).wbs;
  const estimates=JSON.parse(await owner.locator('#estimate-document').inputValue());
  for(const item of estimates.packages){item.effort_minutes=15;item.role='Dev'}
  const eb={expected_version:0,wbs_version:wbs.current.version,wbs_digest:wbs.current.digest,document:estimates,confirmation:'SAVE RESOURCE ESTIMATES'};
  assert.equal((await post(viewer,vc,pp+'/wbs/estimates',eb)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),pp+'/wbs/estimates',eb)).status(),403);
  assert.equal((await post(owner,csrf,pp+'/wbs/estimates',{...eb,wbs_digest:'wrong'})).status(),400);
  await owner.locator('#estimate-document').fill(JSON.stringify(estimates));
  await owner.locator('#estimate-save').click();
  await owner.waitForFunction(()=>document.querySelector('#estimate-state').textContent.includes('ESTIMATES READY'));
  wbs=(await get(owner,pp)).wbs;
  assert.equal(wbs.resource_estimates.analysis.total_effort_minutes,60);
  assert.equal(wbs.dependency_graph.critical_path_minutes,30);
  assert.equal((await post(owner,csrf,pp+'/wbs/estimates',eb)).status(),400);
  const sd=JSON.parse(await owner.locator('#schedule-document').inputValue());
  sd.sprints=[{id:'S1',start:'2026-12-01',end:'2026-12-07',capacity:{Dev:60}}];
  for(const item of sd.assignments)item.sprint='S1';
  sd.milestones=[{id:'M1',title:'Release draft',sprint:'S1',packages:sd.assignments.map(x=>x.id)}];
  const sb={...wbs.sprint_schedule.source,expected_version:0,document:sd,confirmation:'SAVE SPRINT SCHEDULE'};
  assert.equal((await post(viewer,vc,pp+'/wbs/schedule',sb)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),pp+'/wbs/schedule',sb)).status(),403);
  await owner.locator('#schedule-document').fill(JSON.stringify(sd));
  await owner.locator('#schedule-save').click();
  await owner.waitForFunction(()=>document.querySelector('#schedule-state').textContent.includes('SCHEDULE CHECKS PASS'));
  wbs=(await get(owner,pp)).wbs;
  assert.equal(wbs.sprint_schedule.analysis.ready,true);
  assert.equal(wbs.sprint_schedule.analysis.execution_authorized,false);
  assert.equal((await post(owner,csrf,pp+'/wbs/schedule',sb)).status(),400);
  await owner.locator('#reload').click();
  await owner.waitForFunction(()=>document.querySelector('#schedule-state').textContent.includes('SCHEDULE CHECKS PASS'));
  assert.deepEqual(JSON.parse(await owner.locator('#schedule-document').inputValue()),wbs.sprint_schedule.current.document);
  const rb={bundle_digest:wbs.cross_review.bundle_digest,confirmation:'RUN PM CROSS REVIEW'};
  assert.equal(wbs.cross_review.input_ready,true);
  assert.equal((await post(viewer,vc,pp+'/wbs/review',rb)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),pp+'/wbs/review',rb)).status(),403);
  assert.equal((await post(owner,csrf,pp+'/wbs/review',{...rb,bundle_digest:'bad'})).status(),400);
  await owner.locator('#review-run').click();
  await owner.waitForFunction(()=>document.querySelector('#review-state').textContent.includes('CROSS REVIEW PASS'),null,{timeout:30000});
  const reviewed=(await get(owner,pp)).wbs.cross_review;
  assert.equal(reviewed.quality_ready,true);assert.equal(reviewed.execution_authorized,false);
  assert.deepEqual(Object.keys(reviewed.latest.evidence.reviews).sort(),['A','B']);
  const adoption=(await get(owner,pp)).wbs.adoption;
  assert.equal(adoption.can_adopt,true);assert.equal(adoption.current,null);
  const ab={...adoption.binding,expected_version:0,confirmation:'APPROVE AND ADOPT PLANNING BUNDLE'};
  assert.equal((await post(dev,dc,pp+'/wbs/adopt',ab)).status(),403);
  assert.equal((await post(viewer,vc,pp+'/wbs/adopt',ab)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),pp+'/wbs/adopt',ab)).status(),403);
  assert.equal((await post(owner,csrf,pp+'/wbs/adopt',{...ab,evidence_digest:'bad'})).status(),400);
  await owner.locator('#adopt-bundle').click();
  await owner.waitForFunction(()=>document.querySelector('#adoption-state').textContent.includes('ADOPTED'));
  const adopted=(await get(owner,pp)).wbs.adoption;
  assert.equal(adopted.current.version,1);assert.equal(adopted.execution_authorized,false);
  assert.equal(adopted.current.bundle_digest,ab.bundle_digest);
  assert.equal((await post(owner,csrf,pp+'/wbs/adopt',{...ab,expected_version:1})).status(),400);
  // SG.6f: use the actual adopted bundle, not a mocked adoption view.
  const wp=adopted.current.snapshot.bundle.wbs.document.deliverables.flatMap(d=>d.packages).find(p=>p.kind==='implement'&&p.depends_on.length===0);
  assert.ok(wp);
  const base='/api/projects/'+pid+'/studio/work-packages/';
  const bindingBody={adoption_version:adopted.current.version,bundle_digest:adopted.current.bundle_digest,package_id:wp.id,confirmation:'BIND ADOPTED WORK PACKAGE'};
  for(const [page,token] of [[viewer,vc],[reviewer,rc]])assert.equal((await post(page,token,base+'bind',bindingBody)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),base+'bind',bindingBody)).status(),403);
  assert.equal((await post(owner,csrf,base+'bind',{...bindingBody,bundle_digest:'wrong'})).status(),400);
  const studio=await browser.newPage();const sc=await login(studio);
  await studio.addInitScript(({origin,id})=>{if(location.origin===origin)localStorage.setItem('orbit-project',id)},{origin:ORIGIN,id:pid});
  await studio.goto(ORIGIN+'/');
  await studio.locator('#studioLine[data-project-id="'+pid+'"][data-ready="true"]').waitFor();
  const card=studio.locator('#studioWorkflow [data-package-id="'+wp.id+'"]');
  const bindForm=card.locator('form[data-studio-action="bind"]');
  await bindForm.locator('input[name=confirmation]').fill('wrong');
  await bindForm.locator('button[type=submit]').click();
  assert.match(await bindForm.locator('[role=status]').textContent(),/không khớp/);
  await bindForm.locator('input[name=confirmation]').fill(bindingBody.confirmation);
  await bindForm.locator('button[type=submit]').click();
  const queueForm=card.locator('form[data-studio-action="coding"]');
  await queueForm.waitFor({timeout:15000});
  let unified=(await get(owner,'/api/projects/'+pid+'/state')).workflow;
  const bound=unified.work_packages.bindings.find(b=>b.package_id===wp.id);
  assert.equal(bound.state,'BOUND');
  const queueBody={adoption_version:1,package_id:wp.id,binding_digest:bound.digest,confirmation:'QUEUE ADOPTED WORK PACKAGE'};
  assert.equal((await post(viewer,vc,base+'coding',queueBody)).status(),403);
  assert.equal((await post(reviewer,rc,base+'coding',queueBody)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),base+'coding',queueBody)).status(),403);
  assert.equal((await post(owner,csrf,base+'coding',{...queueBody,binding_digest:'wrong'})).status(),400);
  await queueForm.locator('input[name=confirmation]').fill(queueBody.confirmation);
  await queueForm.locator('button[type=submit]').click();
  let boundJob;
  const deadline=Date.now()+30000;
  while(Date.now()<deadline){
   unified=(await get(owner,'/api/projects/'+pid+'/state')).workflow;
   boundJob=unified.coding_jobs.find(j=>j.source_binding?.package_id===wp.id);
   if(boundJob?.queue?.status==='succeeded')break;
   if(boundJob?.queue?.status==='dead')assert.fail('Bound coding queue failed');
   await new Promise(r=>setTimeout(r,200));
  }
  assert.equal(boundJob?.queue?.status,'succeeded');
  assert.equal(boundJob.planning_binding,'BOUND');
  assert.equal(boundJob.qa.state,'BLOCK'); // No sandbox report from synthetic inference.
  assert.equal((await post(owner,csrf,base+'coding',queueBody)).status(),400);
  const qaBody={job_id:boundJob.job_id,source_digest:'missing',expected_version:0,criteria:[],confirmation:'ATTEST WORK PACKAGE QA'};
  assert.equal((await post(dev,dc,base+'qa',qaBody)).status(),403);
  assert.equal((await post(viewer,vc,base+'qa',qaBody)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),base+'qa',qaBody)).status(),403);
  assert.equal((await post(reviewer,rc,base+'qa',qaBody)).status(),400);
  assert.equal((await post(viewer,vc,'/api/projects/'+other+'/studio/work-packages/bind',bindingBody)).status(),403);
  await studio.close();
  await owner.locator('#seed').click();await owner.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('Plan v1'));
  let data=await get(owner,pp);assert.equal(data.execution_ready,false);assert.equal(data.analysis.task_count,4);
  assert.equal(await owner.locator('#tasks tr').count(),4);
  const approval={version:1,digest:data.current.digest,requirements_version:req.version,requirements_digest:req.digest,confirmation:'APPROVE PROJECT PLAN'};
  assert.equal((await post(reviewer,rc,pp+'/approve',approval)).status(),400);
  let estimated=data.current.document;for(const task of estimated.tasks)task.effort_minutes=15;
  await owner.locator('#document').fill(JSON.stringify(estimated));
  await owner.locator('#save').click();await owner.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('Plan v2'));
  data=await get(owner,pp);assert.equal(data.analysis.total_effort_minutes,60);
  assert.equal(data.analysis.dependency_graph.critical_path_minutes,30);
  assert.equal(data.analysis.dependency_graph.critical_nodes.length,4);
  await owner.locator('#graph-source').selectOption('plan');
  await owner.waitForFunction(()=>document.querySelector('#graph-status').textContent.includes('CPM READY · 30 phút'));
  assert.equal(await owner.locator('#graph-nodes tr').count(),4);
  assert.equal(await owner.locator('#graph-edges li').count(),2);
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
  assert.equal((await get(owner,pp)).analysis,null);
  assert.equal((await get(owner,pp)).wbs.dependency_graph,null);
  await owner.waitForFunction(()=>document.querySelector('#graph-status').textContent.includes('STALE'));
  assert.equal(await owner.locator('#graph-nodes tr').count(),0);
  assert.equal((await get(owner,pp)).wbs.stale,true);
  assert.equal((await get(owner,pp)).wbs.decomposition_ready,false);
  assert.equal(await owner.locator('#wbs-save').isDisabled(),true);
  assert.equal(await owner.locator('#estimate-save').isDisabled(),true);
  assert.equal(await owner.locator('#schedule-save').isDisabled(),true);
  assert.equal(await owner.locator('#review-run').isDisabled(),true);
  assert.equal(await owner.locator('#adopt-bundle').isDisabled(),true);
  const staleAdoption=(await get(owner,pp)).wbs.adoption;
  assert.equal(staleAdoption.stale,true);assert.equal(staleAdoption.current.digest,adopted.current.digest);
  assert.equal((await get(owner,pp)).wbs.cross_review.quality_ready,false);
  const staleStudio=(await get(owner,'/api/projects/'+pid+'/state')).workflow;
  assert.equal(staleStudio.coding_jobs.find(j=>j.job_id===boundJob.job_id).planning_binding,'STALE');
  assert.equal((await post(owner,csrf,base+'coding',queueBody)).status(),400);
  assert.equal((await get(owner,pp)).wbs.sprint_schedule.analysis,null);
  assert.equal(await owner.locator('#seed').isDisabled(),true);
  assert.equal((await post(owner,csrf,pp+'/seed',{...seed,expected_version:2})).status(),400);
 }finally{await browser.close()}
});

test('P6.2d.10 system acceptance — explicit recovery after synthetic lane failure',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const owner=await browser.newPage(),reviewer=await browser.newPage();
  const csrf=await login(owner),rc=await login(reviewer,'ci-reviewer');
  const post=(page,token,path,data)=>page.request.post(ORIGIN+path,{headers:headers(token),data});
  const made=await post(owner,csrf,'/api/projects',{name:'System acceptance fixture',idea:'Save links securely in projects',platform:'Web app'});
  assert.equal(made.status(),201);const pid=(await made.json()).project_id;
  assert.equal((await post(owner,csrf,'/api/projects/'+pid+'/members',{user:'ci-reviewer',role:'reviewer'})).status(),200);
  const rp='/api/projects/'+pid+'/requirements',pp='/api/projects/'+pid+'/planning',qp='/api/projects/'+pid+'/queue';
  const doc={problem:'Save useful links',goals:['Retrieve links'],users:['Readers'],scope:['Web'],out_of_scope:['Mobile','Fixture blocked lane'],assumptions:[],open_questions:[],
   requirements:[{id:'REQ-1',kind:'functional',description:'Save URL',priority:'must',acceptance:['Saved URL listed']},{id:'REQ-2',kind:'nonfunctional',description:'Project isolation',priority:'must',acceptance:['Other project cannot read links']}],
   stories:[{id:'US-1',actor:'Reader',goal:'Save links securely',benefit:'Find links later',requirements:['REQ-1','REQ-2']}]};
  const saved=await post(owner,csrf,rp,{expected_version:0,document:doc});
  assert.equal(saved.status(),200);const req=(await saved.json()).current;
  assert.equal((await post(reviewer,rc,rp+'/approve',{version:req.version,digest:req.digest,confirmation:'APPROVE PRODUCT REQUIREMENTS'})).status(),200);
  const get=async()=>{const r=await owner.request.get(ORIGIN+pp);assert.equal(r.status(),200);return r.json()};
  const wait=async(predicate)=>{
   const until=Date.now()+30000;
   while(Date.now()<until){const data=await get();if(predicate(data))return data;await new Promise(r=>setTimeout(r,250))}
   assert.fail('Planning fixture did not reach expected terminal state');
  };
  assert.equal((await post(owner,csrf,pp+'/discover',{requirements_version:req.version,requirements_digest:req.digest,confirmation:'RUN AI PLANNING'})).status(),202);
  let data=await wait(x=>x.discovery?.ready===true);
  const seed=async(lane,v)=>{
   const result=await post(owner,csrf,pp+'/wbs/seed',{...data.wbs.sources[lane],expected_version:v,confirmation:'CREATE WBS DRAFT'});
   assert.equal(result.status(),200);return (await result.json()).current;
  };
  const run=async(wbs)=>{
   const result=await post(owner,csrf,pp+'/wbs/decompose',{wbs_version:wbs.version,wbs_digest:wbs.digest,confirmation:'RUN AI DECOMPOSITION'});
   assert.equal(result.status(),202);return (await result.json()).queue_id;
  };
  const blocked=await seed('B',0),first=await run(blocked);
  data=await wait(x=>x.decomposition?.queue_id===first&&x.decomposition.status==='dead');
  assert.equal(data.decomposition.reason,'quality_gate');
  assert.equal(data.decomposition.ready,false);
  assert.equal(data.decomposition.workflow.next_action,'operator_review');
  assert.equal(data.decomposition.workflow.automatic_fallback,false);
  assert.equal(data.decomposition.evidence.call_count,2);
  assert.equal(data.wbs.current.digest,blocked.digest);
  assert.equal(data.current,null);
  assert.equal((await post(reviewer,rc,qp+'/'+first+'/retry',{confirmation:'RETRY QUEUE TASK'})).status(),403);
  assert.equal((await post(owner,csrf,qp+'/'+first+'/retry',{confirmation:'wrong'})).status(),400);
  const retry=await post(owner,csrf,qp+'/'+first+'/retry',{confirmation:'RETRY QUEUE TASK'});
  assert.equal(retry.status(),200);const second=(await retry.json()).queue_id;
  assert.notEqual(second,first);
  data=await wait(x=>x.decomposition?.queue_id===second&&x.decomposition.status==='dead');
  assert.equal(data.decomposition.reason,'quality_gate');
  assert.equal(data.wbs.current.digest,blocked.digest);
  const replacement=await seed('A',1),third=await run(replacement);
  data=await wait(x=>x.decomposition?.queue_id===third&&x.decomposition.status==='succeeded');
  assert.equal(data.decomposition.ready,true);
  assert.equal(data.decomposition.workflow.next_action,'human_review');
  assert.equal(data.decomposition.workflow.model_qualification,'not_assessed');
  assert.equal(data.decomposition.workflow.automatic_adoption,false);
  assert.equal(data.wbs.current.digest,replacement.digest);
  assert.equal(data.wbs.decomposition_ready,false);
  assert.equal(data.execution_ready,false);
 }finally{await browser.close()}
});
