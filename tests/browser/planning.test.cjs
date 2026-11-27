const {test}=require('node:test');
const assert=require('node:assert/strict');
const {chromium}=require('playwright');
const {execFileSync}=require('node:child_process');
const evidenceFixture=(action,pid,id)=>execFileSync('python',['tests/browser/studio_evidence_fixture.py',action,pid,id],{stdio:'pipe'});
const {login,headers,ORIGIN}=require('./auth-helper.cjs');

// Track real browser navigation and bootstrap separately. Preserve the original
// 30-second navigation budget INCLUDING load, not a fresh timeout per phase.
// Never log cookies, headers, tokens or response bodies.
async function openPlanning(page,pid,requirementsDigest,role){
 const events=[],started=performance.now();
 const record=(event,path,detail)=>events.push({ms:Math.round(performance.now()-started),event,path,...detail});
 const pathOf=url=>{try{return new URL(url).pathname}catch{return 'unknown'}};
 const interesting=req=>['document','stylesheet','script','fetch','xhr'].includes(req.resourceType());
 const onRequest=req=>{if(interesting(req))record('request',pathOf(req.url()),{type:req.resourceType()})};
 const onResponse=res=>{const req=res.request();if(interesting(req))record('response',pathOf(res.url()),{type:req.resourceType(),status:res.status()})};
 const onFailed=req=>{if(interesting(req))record('failed',pathOf(req.url()),{type:req.resourceType(),error:req.failure()?.errorText||'unknown'})};
 const onFinished=req=>{if(interesting(req))record('finished',pathOf(req.url()),{type:req.resourceType()})};
 const onDom=()=>record('DOMContentLoaded','/planning.html',{});
 const onLoad=()=>record('load','/planning.html',{});
 const onCrash=()=>record('crash','/planning.html',{});
 const listeners=[['request',onRequest],['response',onResponse],['requestfailed',onFailed],['requestfinished',onFinished],
  ['domcontentloaded',onDom],['load',onLoad],['crash',onCrash]];
 for(const [event,handler] of listeners)page.on(event,handler);
 const remaining=()=>Math.max(1,30000-(performance.now()-started));
 const successful=path=>events.some(x=>x.event==='response'&&x.path===path&&x.status===200);
 try{
  const documentResponse=await page.goto(ORIGIN+'/planning.html',{waitUntil:'commit',timeout:remaining()});
  assert.ok(documentResponse,'Missing navigation document response');
  assert.equal(documentResponse.status(),200);
  assert.equal(documentResponse.url(),ORIGIN+'/planning.html');
  record('commit','/planning.html',{status:documentResponse.status()});
  await page.waitForLoadState('domcontentloaded',{timeout:remaining()});
  record('domcontentloaded-confirmed','/planning.html',{});
  await page.waitForLoadState('load',{timeout:remaining()});
  record('load-confirmed','/planning.html',{});
  assert.ok(performance.now()-started<=30000,'Navigation exceeded original 30-second budget');
  for(const asset of ['/styles.css','/auth.css','/usage.css','/planning.js']){
   assert.ok(successful(asset),'Missing successful static asset response: '+asset);
   assert.ok(!events.some(x=>x.event==='failed'&&x.path===asset),'Static asset request failed: '+asset);
  }
  // load is not application readiness: DOMContentLoaded launches async auth,
  // project bootstrap, and the planning GET. Keep the original UI waits.
  await page.locator('#panel').waitFor({state:'visible'});
  await page.locator('#project').selectOption(pid);
  await page.waitForFunction(({id,digest,role})=>{
   const $=id=>document.getElementById(id);
   return $('project').value===id&&!$('panel').hidden&&$('input-state').textContent.includes(digest)
    &&$('status').textContent==='Đã tải kế hoạch'&&!$('reload').disabled
    &&!(role==='owner'?$('seed'): $('approve')).disabled;
  },{id:pid,digest:requirementsDigest,role});
  for(const path of ['/api/auth/session','/api/bootstrap','/api/projects/'+pid+'/planning'])
   assert.ok(successful(path),'Missing successful bootstrap response: '+path);
  const ready=await page.evaluate(()=>({readyState:document.readyState,visibility:document.visibilityState,focused:document.hasFocus(),
   project:document.querySelector('#project').value,panelHidden:document.querySelector('#panel').hidden}));
  assert.equal(ready.readyState,'complete');
  assert.equal(ready.project,pid);
  assert.equal(ready.panelHidden,false);
  console.log('Planning navigation and bootstrap verified ('+role+'): '+JSON.stringify({ready,events}));
 }catch(err){
  console.error('Planning navigation lifecycle failure ('+role+'): '+JSON.stringify({url:pathOf(page.url()),closed:page.isClosed(),events}));
  throw err;
 }finally{for(const [event,handler] of listeners)page.off(event,handler)}
}

test('P6.2a planning WBS, approval, RBAC and stale PRD via real Chromium/HTTP',async()=>{
 const browser=await chromium.launch({headless:true});
 let recoveryBrowser;
 const evidence=Object.create(null);
 const checkpoint=id=>{assert.ok(!Object.hasOwn(evidence,id),'Duplicate acceptance checkpoint: '+id);evidence[id]=true};
 try{
  // Explicit context owns the session independently of a single page.
  const ownerContext=await browser.newContext();
  const owner=await ownerContext.newPage(),reviewer=await browser.newPage(),viewer=await browser.newPage(),dev=await browser.newPage();
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
  const extensionPath='/api/projects/'+pid+'/engineering/dependency-extension/approve';
  const roots=adopted.current.snapshot.bundle.wbs.document.deliverables.flatMap(d=>d.packages).filter(p=>p.kind==='implement');
  assert.equal(roots.length,2);
  const edge={source:roots[0].id,target:roots[1].id,rationale:'Implementation dependency reviewed by the synthetic human fixture.'};
  const ext={adoption_version:1,adoption_digest:adopted.current.digest,expected_version:0,edges:[edge],confirmation:'APPROVE WBS DEPENDENCY EXTENSION'};
  assert.equal((await post(dev,dc,extensionPath,ext)).status(),403);
  assert.equal((await post(viewer,vc,extensionPath,ext)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),extensionPath,ext)).status(),403);
  assert.equal((await post(owner,csrf,extensionPath,{...ext,adoption_digest:'bad'})).status(),400);
  assert.equal((await post(owner,csrf,extensionPath,{...ext,edges:[edge,{...edge,source:edge.target,target:edge.source}]})).status(),400);
  const approvedExt=await post(reviewer,rc,extensionPath,ext);assert.equal(approvedExt.status(),201);
  const extReceipt=await approvedExt.json();assert.equal(extReceipt.version,1);assert.equal(extReceipt.execution_authorized,false);
  assert.equal(extReceipt.snapshot.effective_graph.critical_path_minutes,45);
  assert.equal(extReceipt.snapshot.review_scope,'original_bundle_only');
  assert.equal((await post(owner,csrf,extensionPath,ext)).status(),400);
  assert.deepEqual((await get(owner,pp)).wbs.adoption.current,adopted.current);
  assert.equal((await get(owner,'/api/projects/'+pid+'/state')).dependency_extension.state,'APPROVED_ADVISORY');
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
  const eng=(await get(owner,'/api/projects/'+pid+'/state')).engineering;
  const contract=eng.contracts.find(x=>x.package_id===wp.id);
  assert.equal(contract.state,'AWAITING_CONFIRMATION');
  assert.equal(contract.source.structural_eligibility,'ROOT_IMPLEMENTATION');
  assert.equal(contract.source.binding_digest,bound.digest);
  assert.equal(contract.source.execution_authorized,false);
  const engineeringPath='/api/projects/'+pid+'/engineering/contracts/confirm';
  const ebdy={adoption_version:1,package_id:wp.id,expected_version:0,source_digest:contract.source_digest,confirmation:'CONFIRM ENGINEERING CONTRACT'};
  assert.equal((await post(dev,dc,engineeringPath,ebdy)).status(),403);
  assert.equal((await post(viewer,vc,engineeringPath,ebdy)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),engineeringPath,ebdy)).status(),403);
  assert.equal((await post(owner,csrf,engineeringPath,{...ebdy,source_digest:'wrong'})).status(),400);
  assert.equal((await post(owner,csrf,engineeringPath,{...ebdy,confirmation:'yes'})).status(),400);
  const confirmed=await post(reviewer,rc,engineeringPath,ebdy);assert.equal(confirmed.status(),201);
  assert.equal((await confirmed.json()).execution_authorized,false);
  assert.equal((await post(owner,csrf,engineeringPath,ebdy)).status(),400);
  const actual=(await get(owner,'/api/projects/'+pid+'/state')).engineering.contracts.find(x=>x.package_id===wp.id);
  assert.equal(actual.state,'CONFIRMED');assert.equal(actual.latest_version,1);
  const dependentBindingResponse=await post(owner,csrf,base+'bind',{...bindingBody,package_id:edge.target});
  assert.equal(dependentBindingResponse.status(),201);
  const dependentBinding=(await dependentBindingResponse.json()).digest;
  const blockedLegacy={adoption_version:1,package_id:edge.target,binding_digest:dependentBinding,confirmation:'QUEUE ADOPTED WORK PACKAGE'};
  const dependentPath='/api/projects/'+pid+'/engineering/dependent-coding';
  const legacyBypass=await post(owner,csrf,base+'coding',blockedLegacy);
  assert.equal(legacyBypass.status(),400);assert.match((await legacyBypass.json()).error,/Dependent/);
  const dependentContract=(await get(owner,'/api/projects/'+pid+'/state')).engineering.contracts.find(x=>x.package_id===edge.target);
  assert.equal(dependentContract.source.structural_eligibility,'DEPENDENT_IMPLEMENTATION');
  assert.deepEqual(dependentContract.source.predecessors,[wp.id]);
  assert.equal(dependentContract.source.extension_digest,extReceipt.digest);
  assert.equal((await post(reviewer,rc,engineeringPath,{...ebdy,package_id:edge.target,source_digest:dependentContract.source_digest})).status(),201);
  assert.equal((await get(owner,'/api/projects/'+pid+'/state')).dependency_queue.items.find(x=>x.package_id===edge.target).state,'BLOCK');
  const missingPrerequisite={adoption_version:1,package_id:edge.target,binding_digest:dependentBinding,source_digest:'missing',confirmation:'QUEUE DEPENDENT WORK PACKAGE'};
  const deniedDependency=await post(owner,csrf,dependentPath,missingPrerequisite);
  assert.equal(deniedDependency.status(),400,await deniedDependency.text());
  assert.match((await deniedDependency.json()).error,/Missing prerequisite completion receipt/);
  assert.equal((await get(owner,'/api/projects/'+pid+'/state')).workflow.coding_jobs.some(j=>j.source_binding?.package_id===edge.target),false);
  console.log('Dependent HTTP submission blocked before prerequisite completion');
  checkpoint('missing_prerequisite_rejected');
  const queueBody={adoption_version:1,package_id:wp.id,binding_digest:bound.digest,confirmation:'QUEUE ADOPTED WORK PACKAGE'};
  assert.equal((await post(viewer,vc,base+'coding',queueBody)).status(),403);
  assert.equal((await post(reviewer,rc,base+'coding',queueBody)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),base+'coding',queueBody)).status(),403);
  assert.equal((await post(owner,csrf,base+'coding',{...queueBody,binding_digest:'wrong'})).status(),400);
  evidenceFixture('fault-on',pid,wp.id);
  try{
   const failed=await post(owner,csrf,base+'coding',queueBody);
   assert.ok(failed.status()>=400);
  }finally{evidenceFixture('fault-off',pid,wp.id)}
  // Run the complete recovery chain on an isolated snapshot before the live
  // root UI workflow; do not replace or skip any existing assertions.
  const recoveryHttp=JSON.parse(evidenceFixture('bound-recovery-http',pid,wp.id).toString());
  const expectedRecovery=(kind,previous_status)=>({kind,previous_status,retry_http:202,rollback:true,model_calls:4,qa_http:201,completion_http:201,immutable_history:true});
  const {defect_continuity,...recoveryResults}=recoveryHttp;
  assert.deepEqual(recoveryResults,{root:expectedRecovery('root','cancelled'),dependent:expectedRecovery('dependent','interrupted'),recovered_root_prerequisite:true,upstream_stale:true});
  assert.ok(defect_continuity&&defect_continuity.quality.state==='QUALITY_EVIDENCE_PASS');
  require('node:fs').writeFileSync(process.env.ORBIT_ENGINEERING_WORKFLOW_EVIDENCE,JSON.stringify({
    schema:'orbit.engineering-workflow-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,transport:'synthetic_inference_real_git_docker_http',
    recovery:recoveryResults,continuity:defect_continuity,execution_authorized:false,merge_authorized:false,production_release_authorized:false
  }),{flag:'wx'});
  console.log('Root and dependent recovery HTTP E2E verified: HTTP 202/201/201, rollback, four calls each, immutable history, recovered root prerequisite, upstream stale');
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
  evidenceFixture('report',pid,boundJob.job_id);
  const qaForm=studio.locator('#studioWorkflow [data-qa-job="'+boundJob.job_id+'"] form[data-studio-action="qa"]');
  await qaForm.waitFor({timeout:15000});
  let currentQA=(await get(owner,'/api/projects/'+pid+'/state')).workflow.coding_jobs.find(j=>j.job_id===boundJob.job_id).qa;
  assert.equal(currentQA.state,'AWAITING_HUMAN_QA');
  assert.equal(currentQA.latest_version,0);
  for(const criterion of currentQA.source.acceptance){
   await qaForm.getByLabel('Verdict '+criterion.id,{exact:true}).selectOption('PASS');
   await qaForm.getByLabel('Rationale '+criterion.id,{exact:true}).fill('Synthetic acceptance fixture only; not real functional verification.');
  }
  await qaForm.locator('input[name=confirmation]').fill('ATTEST WORK PACKAGE QA');
  const stateUrl=ORIGIN+'/api/projects/'+pid+'/state';
  const qaUrl=ORIGIN+base+'qa';
  // Trigger a real read with an unrelated projection-only change; same source must preserve the form.
  await qaForm.evaluate(form=>{form.dataset.fixtureDraft='retained'});
  const projectionRoute=async route=>{
   const response=await route.fetch();
   const state=await response.json();
   state.workflow.queue.fixture_projection_marker='unrelated poll';
   await route.fulfill({response,json:state});
  };
  await studio.route(stateUrl,projectionRoute,{times:1});
  await studio.waitForFunction(()=>document.querySelector('#studioWorkflow').dataset.signature?.includes('unrelated poll'),null,{timeout:15000});
  assert.equal(await qaForm.getAttribute('data-fixture-draft'),'retained');
  assert.equal(await qaForm.locator('input[name=confirmation]').inputValue(),'ATTEST WORK PACKAGE QA');
  for(const criterion of currentQA.source.acceptance){
   assert.equal(await qaForm.getByLabel('Verdict '+criterion.id,{exact:true}).inputValue(),'PASS');
   assert.equal(await qaForm.getByLabel('Rationale '+criterion.id,{exact:true}).inputValue(),'Synthetic acceptance fixture only; not real functional verification.');
  }
  assert.equal(await qaForm.evaluate(form=>form.checkValidity()),true);
  console.log('QA form identity, confirmation, verdict and rationale preserved across unrelated polling');
  checkpoint('qa_form_preserved');
  // Observe actual consumption of the old JSON response, not just dispatch.
  // The next task runs after the application's await/JSON continuation.
  await studio.evaluate(()=>{
   const original=Response.prototype.json;
   window.__orbitFixtureStaleConsumed=false;
   Response.prototype.json=async function(...args){
    const data=await original.apply(this,args);
    if(this.headers.get('x-orbit-fixture-stale')==='1'){
     setTimeout(()=>{window.__orbitFixtureStaleConsumed=true},0);
    }
    return data;
   };
   window.__orbitRestoreFixtureJson=()=>{Response.prototype.json=original};
  });
  let releaseOld,markHeld,finishOld,started=false;
  const oldGate=new Promise(resolve=>{releaseOld=resolve});
  const held=new Promise(resolve=>{markHeld=resolve});
  const oldDone=new Promise(resolve=>{finishOld=resolve});
  const oldPoll=async route=>{
   started=true;
   let error=null;
   try{
    assert.equal(route.request().method(),'GET');
    const response=await route.fetch();
    assert.equal(response.status(),200);
    const state=await response.json();
    assert.equal(state.workflow.coding_jobs.find(j=>j.job_id===boundJob.job_id).qa.state,'AWAITING_HUMAN_QA');
    markHeld(null);
    await oldGate;
    // One explicit terminal operation. Do not reuse the APIResponse object.
    await route.fulfill({status:200,json:state,headers:{'content-type':'application/json','cache-control':'no-store','x-orbit-fixture-stale':'1'}});
   }catch(err){
    error=err;
    markHeld(err);
   }finally{finishOld(error)}
  };
  // Only the first request is intercepted; fresh reads use the real backend.
  await studio.route(stateUrl,oldPoll,{times:1});
  let timer;
  try{
   const captureError=await Promise.race([held,new Promise((_,reject)=>{timer=setTimeout(()=>reject(Error('No pre-submit poll captured')),15000)})]);
   if(captureError)throw captureError;
   clearTimeout(timer);
   const [qaResponse]=await Promise.all([
    studio.waitForResponse(r=>r.url()===qaUrl&&r.request().method()==='POST',{timeout:15000}),
    qaForm.locator('button[type=submit]').click()
   ]);
   assert.equal(qaResponse.status(),201,await qaResponse.text());
   const posted=qaResponse.request().postDataJSON(),receipt=await qaResponse.json();
   assert.equal(posted.source_digest,currentQA.source_digest);
   assert.equal(posted.expected_version,currentQA.latest_version);
   assert.equal(receipt.version,1);
   const persisted=JSON.parse(evidenceFixture('qa-receipt',pid,boundJob.job_id).toString());
   assert.equal(persisted.digest,receipt.digest);
   assert.equal(persisted.source_digest,posted.source_digest);
   assert.deepEqual(persisted.criteria,posted.criteria);
   console.log('QA HTTP 201; persisted receipt, source digest and exact criteria verified');
  checkpoint('root_qa_receipt');
   // Fresh committed state must render even while the old request is still held.
   await studio.waitForFunction(id=>document.querySelector('[data-qa-job="'+id+'"] h4')?.textContent.includes('HUMAN_QA_PASS'),boundJob.job_id,{timeout:15000});
   console.log('Fresh QA state rendered before releasing stale GET');
  checkpoint('fresh_qa_before_old_poll');
   releaseOld();
   const routeError=await oldDone;
   if(routeError)throw routeError;
   await studio.waitForFunction(()=>window.__orbitFixtureStaleConsumed===true,null,{timeout:15000});
   // Verify immediately after consumption, not after a later correcting poll.
   assert.match(await studio.locator('[data-qa-job="'+boundJob.job_id+'"] h4').textContent(),/HUMAN_QA_PASS/);
   console.log('Delayed stale GET consumed; QA state did not regress');
  checkpoint('stale_poll_rejected');
  }finally{
   clearTimeout(timer);
   releaseOld();
   try{
    // Never unregister/close while the captured handler is still fulfilling.
    if(started){const error=await oldDone;if(error)throw error}
    await studio.unroute(stateUrl,oldPoll);
    if(started){const error=await oldDone;if(error)throw error}
   }finally{await studio.evaluate(()=>{window.__orbitRestoreFixtureJson();delete window.__orbitRestoreFixtureJson;delete window.__orbitFixtureStaleConsumed})}
  }
  await studio.waitForFunction(id=>document.querySelector('[data-qa-job="'+id+'"] h4')?.textContent.includes('HUMAN_QA_PASS'),boundJob.job_id,{timeout:15000});
  currentQA=(await get(owner,'/api/projects/'+pid+'/state')).workflow.coding_jobs.find(j=>j.job_id===boundJob.job_id).qa;
  assert.equal(currentQA.receipt.version,1);
  assert.equal(currentQA.dependency_completed,false);
  assert.equal(currentQA.production_release_authorized,false);
  const completionPath='/api/projects/'+pid+'/engineering/completions/confirm';
  const completionState=async()=> (await get(owner,'/api/projects/'+pid+'/state')).dependency_completion.items.find(x=>x.job_id===boundJob.job_id);
  const candidate=await completionState();
  assert.equal(candidate.state,'AWAITING_CONFIRMATION');
  const cbdy={job_id:boundJob.job_id,source_digest:candidate.source_digest,expected_version:0,selected:'B',rationale:'Synthetic fixture candidate review for dependency evidence only.',confirmation:'CONFIRM DEPENDENCY COMPLETION DEV-B '+boundJob.job_id};
  assert.equal((await post(dev,dc,completionPath,cbdy)).status(),403);
  assert.equal((await post(viewer,vc,completionPath,cbdy)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),completionPath,cbdy)).status(),403);
  assert.equal((await post(owner,csrf,completionPath,{...cbdy,source_digest:'wrong'})).status(),400);
  assert.equal((await post(owner,csrf,completionPath,{...cbdy,confirmation:'yes'})).status(),400);
  const completed=await post(reviewer,rc,completionPath,cbdy);assert.equal(completed.status(),201);
  assert.equal((await completed.json()).execution_authorized,false);
  const savedCompletion=await completionState();
  assert.equal(savedCompletion.state,'COMPLETION_EVIDENCE_CONFIRMED');
  assert.equal(savedCompletion.receipt.selected,'B');
  assert.equal(savedCompletion.latest_version,1);
  // P6.3g: real Git + real Docker replay on the exact bound coding job.
  // The preceding synthetic sandbox receipt remains immutable historical input.
  const engineering='/api/projects/'+pid+'/engineering';
  assert.equal((await post(dev,dc,engineering+'/workspace',{confirmation:'INITIALIZE PROJECT GIT WORKSPACE'})).status(),403);
  const initialized=await post(owner,csrf,engineering+'/workspace',{confirmation:'INITIALIZE PROJECT GIT WORKSPACE'});
  assert.equal(initialized.status(),200,await initialized.text());
  const baseline=await initialized.json();
  assert.equal(baseline.state,'READY');
  const selectionPath=engineering+'/candidate-selections/'+boundJob.job_id;
  const selection=await get(owner,selectionPath);
  assert.equal(selection.state,'AWAITING_SELECTION');
  const choose={job_id:boundJob.job_id,source_digest:selection.source_digest,expected_version:0,selected:'B',
   rationale:'Explicit fixture Tech Lead selection for the real Git-bound sandbox replay.',
   confirmation:'SELECT ENGINEERING DEV-B '+boundJob.job_id};
  assert.equal((await post(dev,dc,engineering+'/candidate-selections/confirm',choose)).status(),403);
  assert.equal((await post(reviewer,'0'.repeat(64),engineering+'/candidate-selections/confirm',choose)).status(),403);
  const choice=await post(reviewer,rc,engineering+'/candidate-selections/confirm',choose);
  assert.equal(choice.status(),201,await choice.text());
  const chosen=await choice.json();
  const sandboxPath=engineering+'/sandbox/'+boundJob.job_id;
  const readySandbox=await get(owner,sandboxPath);
  assert.equal(readySandbox.state,'AWAITING_EXPLICIT_SANDBOX');
  assert.equal((await post(owner,csrf,sandboxPath,{})).status(),404);
  const args=['tools/run_engineering_sandbox.py','--db',process.env.AI_COMPANY_DB,'--project',pid,'--job',boundJob.job_id,
   '--actor','ci-reviewer','--source-digest',readySandbox.source_digest,'--expected-version','0',
   '--confirm','RUN ENGINEERING SANDBOX '+boundJob.job_id];
  assert.ok(process.env.ORBIT_SANDBOX_PYTHON_IMAGE,'Real pinned Python image required');
  const replay=JSON.parse(execFileSync('python',args,{stdio:'pipe',timeout:120000}).toString());
  assert.equal(replay.gate,'PASS');
  assert.equal(replay.selection_digest,chosen.digest);
  assert.equal(replay.selected,'B');
  assert.notEqual(replay.git.A.commit,replay.git.B.commit);
  for(const lane of ['A','B']){
   assert.equal(replay.git[lane].parent,baseline.base_commit);
   assert.equal(replay.git[lane].source_sha256,selection.source.bound_evidence.candidates[lane].digest);
  }
  const sandboxSaved=await get(owner,sandboxPath);
  assert.equal(sandboxSaved.state,'PASS');
  assert.equal(sandboxSaved.receipt.digest,replay.digest);
  assert.equal(sandboxSaved.execution_authorized,false);
  for(const lane of ['A','B'])assert.ok(sandboxSaved.receipt.lanes[lane].test_count>0);
  assert.deepEqual(await get(owner,engineering+'/workspace'),baseline);
  assert.equal((await get(owner,selectionPath)).receipt.digest,chosen.digest);
  const fsSandbox=require('node:fs');
  fsSandbox.writeFileSync(process.env.ORBIT_ENGINEERING_SANDBOX_EVIDENCE,JSON.stringify({
   schema:'orbit.engineering-sandbox-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
   run_attempt:process.env.GITHUB_RUN_ATTEMPT,transport:'synthetic_inference_real_git_real_docker',
   project_id:pid,job_id:boundJob.job_id,base_commit:baseline.base_commit,selection_digest:chosen.digest,
   receipt:sandboxSaved.receipt,execution_authorized:false,merge_authorized:false,production_release_authorized:false
  }),{flag:'wx'});
  console.log('P6.3g real Git/Docker A/B replay, selection binding and immutable receipt PASS');
  // P6.3i: actual HTTP defect lifecycle and explicit real Docker retest.
  const qualityPath=engineering+'/quality/'+boundJob.job_id;
  const qcPath=engineering+'/qc/'+boundJob.job_id;
  const defectPath=qualityPath+'/defects';
  const qualityBefore=await get(owner,qualityPath);
  assert.equal(qualityBefore.state,'QUALITY_EVIDENCE_PASS');
  const defectId='fixture-defect-1';
  const makeDefect=(action,version,source,extra={})=>({action,defect_id:defectId,expected_version:version,
   source_digest:source,rationale:'Explicit fixture defect review and evidence for engineering quality.',
   confirmation:'DEFECT '+action+' '+boundJob.job_id+' '+defectId,...extra});
  const openDefect=makeDefect('OPEN',0,qualityBefore.source_digest,{severity:'HIGH',category:'TEST',title:'Review fixture test coverage'});
  assert.equal((await post(dev,dc,defectPath,openDefect)).status(),403);
  assert.equal((await post(reviewer,'0'.repeat(64),defectPath,openDefect)).status(),403);
  assert.equal((await post(reviewer,rc,defectPath,{...openDefect,source_digest:'wrong'})).status(),400);
  const opened=await post(reviewer,rc,defectPath,openDefect);
  assert.equal(opened.status(),201,await opened.text());
  const openReceipt=await opened.json();
  assert.equal((await post(reviewer,rc,defectPath,openDefect)).status(),400);
  const qualityOpen=await get(owner,qualityPath);
  assert.equal(qualityOpen.state,'BLOCK');
  assert.equal(qualityOpen.counts.OPEN,1);
  const qcOpen=await get(owner,qcPath);
  assert.equal(qcOpen.state,'BLOCK');
  assert.equal(qcOpen.checks.defects,'BLOCK');
  const readyDefect=makeDefect('READY_FOR_RETEST',1,qualityOpen.source_digest);
  assert.equal((await post(viewer,vc,defectPath,readyDefect)).status(),403);
  const readyResponse=await post(dev,dc,defectPath,readyDefect);
  assert.equal(readyResponse.status(),201,await readyResponse.text());
  const readyReceipt=await readyResponse.json();
  const qualityReady=await get(owner,qualityPath);
  assert.equal(qualityReady.counts.READY_FOR_RETEST,1);
  assert.equal((await post(reviewer,rc,defectPath,makeDefect('CLOSED',2,qualityReady.source_digest))).status(),400);
  const retestArgs=args.slice();
  retestArgs[retestArgs.indexOf('--expected-version')+1]='1';
  const retest=JSON.parse(execFileSync('python',retestArgs,{stdio:'pipe',timeout:120000}).toString());
  assert.equal(retest.gate,'PASS');
  assert.notEqual(retest.digest,replay.digest);
  const qualityRetest=await get(owner,qualityPath);
  const closeDefect=makeDefect('CLOSED',2,qualityRetest.source_digest);
  assert.equal((await post(dev,dc,defectPath,closeDefect)).status(),403);
  const closed=await post(reviewer,rc,defectPath,closeDefect);
  assert.equal(closed.status(),201,await closed.text());
  const closeReceipt=await closed.json();
  const qualityClosed=await get(owner,qualityPath);
  assert.equal(qualityClosed.state,'QUALITY_EVIDENCE_PASS');
  assert.deepEqual(qualityClosed.counts,{OPEN:0,READY_FOR_RETEST:0,CLOSED:1});
  assert.deepEqual(qualityClosed.defects[0].history.map(x=>x.digest),[openReceipt.digest,readyReceipt.digest,closeReceipt.digest]);
  assert.equal(qualityClosed.execution_authorized,false);
  const finalSandbox=await get(owner,sandboxPath);
  assert.equal(finalSandbox.receipt.digest,retest.digest);
  const sandboxEvidenceFile=process.env.ORBIT_ENGINEERING_SANDBOX_EVIDENCE;
  const sandboxEvidence=JSON.parse(fsSandbox.readFileSync(sandboxEvidenceFile));
  const initialSandbox=sandboxEvidence.receipt;
  sandboxEvidence.receipt=finalSandbox.receipt;
  fsSandbox.writeFileSync(sandboxEvidenceFile,JSON.stringify(sandboxEvidence));
  fsSandbox.writeFileSync(process.env.ORBIT_ENGINEERING_QUALITY_EVIDENCE,JSON.stringify({
   schema:'orbit.engineering-quality-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
   run_attempt:process.env.GITHUB_RUN_ATTEMPT,transport:'synthetic_inference_real_git_docker_http',
   project_id:pid,job_id:boundJob.job_id,initial_sandbox:initialSandbox,retest_sandbox_digest:retest.digest,
   prior_close_blocked:true,quality:qualityClosed
  }),{flag:'wx'});
  console.log('P6.3i defect lifecycle, fresh real Docker retest and quality evidence PASS');
  const draftPath=engineering+'/draft-pr/'+boundJob.job_id;
  assert.equal((await get(owner,draftPath)).state,'AWAITING_EXPLICIT_DRAFT');
  assert.equal((await post(owner,csrf,draftPath,{})).status(),404);
  const draftEvidence=JSON.parse(execFileSync('python',['tests/browser/engineering_draft_browser.py',pid,boundJob.job_id],{stdio:'pipe',timeout:60000}).toString());
  assert.equal(draftEvidence.plan.source.sandbox_digest,retest.digest);
  assert.equal(draftEvidence.plan.source.git.commit,replay.git.B.commit);
  assert.equal(draftEvidence.receipt.remote.draft,true);
  const draftSaved=await get(owner,draftPath);
  assert.equal(draftSaved.state,'CREATED_DRAFT');
  assert.equal(draftSaved.plan_digest,draftEvidence.plan_digest);
  assert.equal(draftSaved.execution_authorized,false);
  fsSandbox.writeFileSync(process.env.ORBIT_ENGINEERING_DRAFT_EVIDENCE,JSON.stringify(draftEvidence),{flag:'wx'});
  console.log('P6.3h Git-bound draft PR contract, real SQLite receipt and duplicate rejection PASS');
  const qcPassed=await get(owner,qcPath);
  assert.equal(qcPassed.state,'QA_QC_EVIDENCE_PASS',JSON.stringify(qcPassed));
  assert.equal(qcPassed.selected,'B');
  assert.deepEqual(await get(viewer,qcPath),qcPassed);
  assert.equal((await post(owner,csrf,qcPath,{})).status(),404);
  assert.equal(qcPassed.remote_live_verified,false);
  assert.equal(qcPassed.execution_authorized,false);
  const testPlanPath=engineering+'/test-plans/'+boundJob.job_id;
  const planInitial=await get(owner,testPlanPath);
  assert.equal(planInitial.state,'AWAITING_TEST_PLAN');
  const planBody={source_digest:planInitial.source_digest,expected_version:0,
   confirmation:'CONFIRM ACCEPTANCE TEST PLAN '+boundJob.job_id,
   cases:planInitial.template.map(t=>({...t,scenario:'Fixture scenario '+t.id+' for '+t.criterion_id,
    expected:'Fixture expected observable result '+t.id}))};
  assert.equal((await post(dev,dc,testPlanPath,planBody)).status(),403);
  assert.equal((await post(reviewer,'0'.repeat(64),testPlanPath,planBody)).status(),403);
  assert.equal((await post(reviewer,rc,testPlanPath,{...planBody,cases:planBody.cases.slice(1)})).status(),400);
  assert.equal((await post(reviewer,rc,testPlanPath,{...planBody,source_digest:'bad'})).status(),400);
  const planResponse=await post(reviewer,rc,testPlanPath,planBody);
  assert.equal(planResponse.status(),201,await planResponse.text());
  const planReceipt=await planResponse.json();
  assert.equal((await post(reviewer,rc,testPlanPath,planBody)).status(),400);
  const planPassed=await get(owner,testPlanPath);
  assert.equal(planPassed.state,'TEST_PLAN_COVERAGE_PASS');
  assert.equal(planPassed.execution_status,'NOT_EXECUTED');
  assert.equal(planPassed.history[0].digest,planReceipt.digest);
  assert.deepEqual(await get(viewer,testPlanPath),planPassed);
  assert.equal(planPassed.assertion_status,'NOT_READY');
  const executableBody={...planBody,expected_version:1,cases:planBody.cases.map(t=>({...t,
   execution:{runtime:'python',module:'main',function:'add',
    arguments:t.kind==='POSITIVE'?[2,3]:t.kind==='NEGATIVE'?[2,'bad']:[0,0],
    assertion:t.kind==='NEGATIVE'?{operator:'raises',exception:'TypeError'}:{operator:'equals',value:t.kind==='POSITIVE'?5:0}}
  }))};
  const invalidExecution={...executableBody,cases:executableBody.cases.map((t,i)=>i===0?{...t,execution:{...t.execution,command:'echo forbidden'}}:t)};
  assert.equal((await post(reviewer,rc,testPlanPath,invalidExecution)).status(),400);
  assert.equal((await post(dev,dc,testPlanPath,executableBody)).status(),403);
  assert.equal((await post(reviewer,rc,testPlanPath,executableBody)).status(),201);
  const executablePlan=await get(owner,testPlanPath);
  assert.equal(executablePlan.assertion_status,'ASSERTION_CONTRACT_READY');
  assert.equal(executablePlan.execution_status,'NOT_EXECUTED');
  assert.equal(executablePlan.latest_version,2);
  assert.deepEqual(executablePlan.history[0],planPassed.history[0]);
  assert.equal((await post(reviewer,rc,testPlanPath,{...planBody,expected_version:2})).status(),400);
  const runnerSandbox=await get(owner,sandboxPath);
  assert.equal(runnerSandbox.state,'PASS');
  const gitChangesPath=engineering+'/git-changes/'+boundJob.job_id;
  const gitChanges=await get(owner,gitChangesPath);
  assert.equal(gitChanges.state,'GIT_CHANGE_EVIDENCE_READY',JSON.stringify(gitChanges));
  assert.equal(gitChanges.source.selected,'B');
  assert.deepEqual(gitChanges.source.git,runnerSandbox.receipt.git);
  assert.equal(gitChanges.source.sandbox_digest,runnerSandbox.receipt.digest);
  assert.deepEqual(gitChanges.comparisons.baseline_to_B.changes.map(x=>x.path),['main.py','test_main.py']);
  assert.deepEqual(gitChanges.comparisons.baseline_to_B.counts,{ADDED:2,MODIFIED:0,DELETED:0});
  assert.deepEqual(gitChanges.comparisons.A_to_B.changes,[]);
  assert.equal(gitChanges.comparisons.A_to_B.unchanged_count,2);
  assert.deepEqual(await get(viewer,gitChangesPath),gitChanges);
  assert.equal((await post(owner,csrf,gitChangesPath,{})).status(),404);
  const impactPath=engineering+'/dependency-impact/'+boundJob.job_id;
  const impactEvidence=await get(owner,impactPath);
  assert.equal(impactEvidence.state,'DEPENDENCY_IMPACT_READY',JSON.stringify(impactEvidence));
  assert.equal(impactEvidence.source.git_change_evidence_digest,gitChanges.evidence_digest);
  assert.deepEqual(impactEvidence.graphs.B.edges,[{importer:'test_main.py',dependency:'main.py'}]);
  assert.deepEqual(impactEvidence.graphs.B.uncertainties,[]);
  assert.deepEqual(impactEvidence.comparisons.baseline_to_B.current_impacted_paths,['main.py','test_main.py']);
  assert.deepEqual(impactEvidence.comparisons.A_to_B.impacted_paths,[]);
  assert.equal(impactEvidence.full_regression_required,true);
  assert.equal(impactEvidence.selective_execution_authorized,false);
  assert.deepEqual(await get(viewer,impactPath),impactEvidence);
  assert.equal((await post(owner,csrf,impactPath,{})).status(),404);
  const mappingPath=engineering+'/impacted-tests/'+boundJob.job_id;
  const initialMapping=await get(owner,mappingPath);
  assert.equal(initialMapping.state,'IMPACTED_TEST_MAPPING_READY',JSON.stringify(initialMapping));
  assert.equal(initialMapping.source.impact_evidence_digest,impactEvidence.evidence_digest);
  assert.equal(initialMapping.source.runner_source.plan_digest,executablePlan.history[1].digest);
  assert.equal(initialMapping.mappings.baseline_to_B.impacted_count,3);
  assert.equal(initialMapping.mappings.A_to_B.impacted_count,0);
  assert.equal(initialMapping.mappings.A_to_B.required_count,3);
  assert.deepEqual(initialMapping.mappings.baseline_to_B.cases.map(x=>x.case_id),executablePlan.history[1].snapshot.cases.map(x=>x.id));
  assert.ok(initialMapping.mappings.baseline_to_B.cases.every(x=>x.required&&x.reason==='DIRECT_CHANGE'));
  assert.deepEqual(await get(viewer,mappingPath),initialMapping);
  assert.equal((await post(owner,csrf,mappingPath,{})).status(),404);
  const runnerArgs=['tools/run_acceptance_assertions.py','--db',process.env.AI_COMPANY_DB,'--project',pid,'--job',boundJob.job_id,
   '--actor','ci-reviewer','--plan-digest',executablePlan.history[1].digest,'--source-digest',executablePlan.source_digest,
   '--assertion-digest',executablePlan.assertion_contract_digest,'--sandbox-digest',runnerSandbox.receipt.digest,
   '--confirm','RUN ACCEPTANCE ASSERTIONS '+boundJob.job_id];
  const deniedArgs=runnerArgs.slice();deniedArgs[deniedArgs.indexOf('--actor')+1]='ci-developer';
  assert.throws(()=>execFileSync('python',deniedArgs,{stdio:'pipe',timeout:60000}),e=>e.status===1);
  const runnerResult=JSON.parse(execFileSync('python',runnerArgs,{stdio:'pipe',timeout:150000}).toString());
  assert.equal(runnerResult.report.gate,'PASS',JSON.stringify(runnerResult));
  assert.equal(runnerResult.report.executed_count,executablePlan.history[1].snapshot.cases.length);
  assert.deepEqual(runnerResult.report.results.map(x=>x.case_id),executablePlan.history[1].snapshot.cases.map(x=>x.id));
  assert.ok(runnerResult.report.results.every(x=>x.status==='PASS'&&x.executed===true));
  assert.equal(runnerResult.report.persisted,false);
  assert.equal(runnerResult.report.source.candidate_digest,runnerSandbox.receipt.git.B.source_sha256);
  assert.deepEqual(await get(owner,testPlanPath),executablePlan);
  const executionGatePath=engineering+'/execution-quality/'+boundJob.job_id;
  const executionGateBefore=await get(owner,executionGatePath);
  assert.equal(executionGateBefore.state,'BLOCK');
  assert.equal(executionGateBefore.checks.legacy_qc,'PASS');
  assert.equal(executionGateBefore.checks.test_plan,'PASS');
  assert.equal(executionGateBefore.checks.execution_receipt,'BLOCK');
  assert.equal((await post(owner,csrf,executionGatePath,runnerResult)).status(),404);
  const registryPath=engineering+'/assertion-runs/'+boundJob.job_id;
  const registryInitial=await get(owner,registryPath);
  assert.equal(registryInitial.state,'AWAITING_EXECUTION');
  assert.equal(registryInitial.latest_version,0);
  assert.equal((await post(owner,csrf,registryPath,runnerResult)).status(),404);
  const persistArgs=[...runnerArgs,'--expected-registry-version','0'];
  const persistedResult=JSON.parse(execFileSync('python',persistArgs,{stdio:'pipe',timeout:150000}).toString());
  assert.equal(persistedResult.report.gate,'PASS');
  const registryPassed=await get(owner,registryPath);
  assert.equal(registryPassed.state,'EXECUTION_RECORDED_PASS');
  assert.equal(registryPassed.latest_version,1);
  assert.deepEqual(registryPassed.current_receipt,persistedResult.receipt);
  assert.deepEqual(await get(viewer,registryPath),registryPassed);
  assert.throws(()=>execFileSync('python',persistArgs,{stdio:'pipe',timeout:60000}),e=>e.status===1);
  const persistAgain=[...runnerArgs,'--expected-registry-version','1'];
  const persistedAgain=JSON.parse(execFileSync('python',persistAgain,{stdio:'pipe',timeout:150000}).toString());
  const registrySecond=await get(owner,registryPath);
  assert.equal(registrySecond.latest_version,2);
  assert.deepEqual(registrySecond.history[0],registryPassed.history[0]);
  assert.deepEqual(registrySecond.current_receipt,persistedAgain.receipt);
  assert.equal(registrySecond.history[1].snapshot.previous_digest,registryPassed.history[0].digest);
  const executionGatePassed=await get(owner,executionGatePath);
  assert.equal(executionGatePassed.state,'EXECUTION_QUALITY_PASS',JSON.stringify(executionGatePassed));
  assert.equal(executionGatePassed.receipts.execution,registrySecond.current_receipt.digest);
  assert.equal(executionGatePassed.coverage.executed_count,executablePlan.history[1].snapshot.cases.length);
  assert.ok(Object.values(executionGatePassed.checks).every(x=>x==='PASS'));
  assert.deepEqual(await get(viewer,executionGatePath),executionGatePassed);
  assert.equal(executionGatePassed.execution_authorized,false);
  // Final lifecycle: explicitly revise a single expected value, execute real
  // Docker assertions, preserve the BLOCK receipt, then approve and rerun.
  const badCases=executableBody.cases.map(t=>t.kind==='POSITIVE'
    ?{...t,execution:{...t.execution,assertion:{operator:'equals',value:6}}}:t);
  assert.equal(badCases.filter(t=>t.kind==='POSITIVE').length,1);
  const badPlanResponse=await post(reviewer,rc,testPlanPath,{...executableBody,expected_version:2,cases:badCases});
  assert.equal(badPlanResponse.status(),201,await badPlanResponse.text());
  const failedPlan=await get(owner,testPlanPath);
  const gateAfterRevision=await get(owner,executionGatePath);
  assert.equal(gateAfterRevision.state,'BLOCK');
  const registryAfterRevision=await get(owner,registryPath);
  assert.equal(registryAfterRevision.state,'STALE');
  assert.deepEqual(registryAfterRevision.history,registrySecond.history);
  function assertionArgsFor(p,v){
    const args=runnerArgs.slice();
    args[args.indexOf('--plan-digest')+1]=p.history.at(-1).digest;
    args[args.indexOf('--assertion-digest')+1]=p.assertion_contract_digest;
    return [...args,'--expected-registry-version',String(v)];
  }
  assert.throws(()=>execFileSync('python',[...runnerArgs,'--expected-registry-version','2'],{stdio:'pipe',timeout:60000}),e=>e.status===1);
  let failedRun;
  try{
    execFileSync('python',assertionArgsFor(failedPlan,2),{stdio:'pipe',timeout:150000});
    assert.fail('Expected real assertion failure');
  }catch(e){
    assert.equal(e.status,2);
    failedRun=JSON.parse(e.stdout.toString());
  }
  assert.equal(failedRun.report.gate,'BLOCK');
  assert.equal(failedRun.report.executed_count,failedRun.report.case_count);
  assert.equal(failedRun.report.results.filter(x=>x.status==='FAIL').length,1);
  const registryFailed=await get(owner,registryPath);
  const gateFailed=await get(owner,executionGatePath);
  assert.equal(registryFailed.state,'EXECUTION_RECORDED_BLOCK');
  assert.equal(registryFailed.latest_version,3);
  assert.deepEqual(registryFailed.current_receipt,failedRun.receipt);
  assert.equal(gateFailed.state,'BLOCK');
  assert.equal(gateFailed.checks.legacy_qc,'PASS');
  assert.equal(gateFailed.checks.test_plan,'PASS');
  const correctedResponse=await post(reviewer,rc,testPlanPath,{...executableBody,expected_version:3});
  assert.equal(correctedResponse.status(),201,await correctedResponse.text());
  const correctedPlan=await get(owner,testPlanPath);
  const gateBeforeRecovery=await get(owner,executionGatePath);
  assert.equal(gateBeforeRecovery.state,'BLOCK');
  const registryBeforeRecovery=await get(owner,registryPath);
  assert.equal(registryBeforeRecovery.state,'STALE');
  assert.deepEqual(registryBeforeRecovery.history,registryFailed.history);
  const recoveredRun=JSON.parse(execFileSync('python',assertionArgsFor(correctedPlan,3),{stdio:'pipe',timeout:150000}).toString());
  const registryRecovered=await get(owner,registryPath);
  const gateRecovered=await get(owner,executionGatePath);
  const recoveredMapping=await get(owner,mappingPath);
  assert.equal(recoveredMapping.state,'IMPACTED_TEST_MAPPING_READY',JSON.stringify(recoveredMapping));
  assert.notEqual(recoveredMapping.evidence_digest,initialMapping.evidence_digest);
  assert.equal(recoveredMapping.source.runner_source.plan_version,4);
  assert.deepEqual(recoveredMapping.mappings,initialMapping.mappings);
  assert.equal(recoveredMapping.full_regression_required,true);
  assert.equal(recoveredMapping.selective_execution_authorized,false);
  assert.equal(registryRecovered.state,'EXECUTION_RECORDED_PASS');
  assert.equal(registryRecovered.latest_version,4);
  assert.deepEqual(registryRecovered.current_receipt,recoveredRun.receipt);
  assert.deepEqual(registryRecovered.history.slice(0,3),registryFailed.history);
  assert.equal(gateRecovered.state,'EXECUTION_QUALITY_PASS');
  assert.notEqual(gateRecovered.evidence_digest,executionGatePassed.evidence_digest);
  assert.equal(gateRecovered.receipts.execution,registryRecovered.current_receipt.digest);
  assert.equal(gateRecovered.execution_authorized,false);
  const guardArgs=['tools/check_execution_quality.py','--db',process.env.AI_COMPANY_DB,'--project',pid,'--job',boundJob.job_id,'--actor','ci-reviewer','--expected-digest'];
  assert.throws(()=>execFileSync('python',[...guardArgs,executionGatePassed.evidence_digest],{stdio:'pipe',timeout:60000}),e=>e.status===1);
  assert.deepEqual(JSON.parse(execFileSync('python',[...guardArgs,gateRecovered.evidence_digest],{stdio:'pipe',timeout:60000}).toString()),gateRecovered);
  const eligible=(await get(owner,'/api/projects/'+pid+'/state')).dependency_queue.items.find(x=>x.package_id===edge.target);
  assert.equal(eligible.state,'READY_FOR_EXPLICIT_SUBMISSION');
  assert.equal(eligible.source.prerequisites[0].digest,savedCompletion.receipt.digest);
  assert.equal(eligible.source.extension_digest,extReceipt.digest);
  assert.equal((await post(owner,csrf,base+'coding',blockedLegacy)).status(),400);
  // Positive dependent path through real authenticated HTTP, actual dispatcher and
  // durable SQLite pins. Only inference and sandbox transport are synthetic.
  const dependentBody={...missingPrerequisite,source_digest:eligible.source_digest};
  for(const [page,token] of [[viewer,vc],[reviewer,rc]])
   assert.equal((await post(page,token,dependentPath,dependentBody)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),dependentPath,dependentBody)).status(),403);
  for(const change of [{source_digest:'wrong'},{binding_digest:'wrong'},{confirmation:'yes'},{adoption_version:2}]){
   const bad=await post(owner,csrf,dependentPath,{...dependentBody,...change});
   assert.equal(bad.status(),400,await bad.text());
  }
  assert.equal((await get(owner,'/api/projects/'+pid+'/state')).workflow.coding_jobs.some(j=>j.source_binding?.package_id===edge.target),false);
  // Inject failure after the real pin INSERT and again after the real audit
  // INSERT. All transaction-owned rows must match exactly before and after.
  for(const [fault,message] of [
   ['dependency-pin-fault-on','fixture dependency pin persistence fault'],
   ['dependency-audit-fault-on','fixture dependency audit persistence fault']
  ]){
   const before=JSON.parse(evidenceFixture(fault,pid,edge.target).toString());
   let failure;
   try{failure=await post(dev,dc,dependentPath,dependentBody)}
   finally{
    const after=JSON.parse(evidenceFixture('dependency-fault-off',pid,edge.target).toString());
    assert.deepEqual(after,before);
   }
   assert.equal(failure.status(),400,await failure.text());
   assert.equal((await failure.json()).error,message);
   const restored=(await get(owner,'/api/projects/'+pid+'/state')).dependency_queue.items.find(x=>x.package_id===edge.target);
   assert.equal(restored.state,'READY_FOR_EXPLICIT_SUBMISSION');
   assert.equal(restored.source_digest,eligible.source_digest);
   console.log('Dependent atomic rollback verified: '+fault+'; exact job/queue/pin/audit/event/usage rows unchanged');
  checkpoint(fault==='dependency-pin-fault-on'?'rollback_dependency_pin':'rollback_dependency_audit');
  }
  const staleDispatch=JSON.parse(evidenceFixture('stale-dispatch-copy',pid,boundJob.job_id).toString());
  assert.deepEqual(staleDispatch,['before_claim','after_routing'].map(scenario=>({scenario,queue:'dead',reason:'coding_source_invalid',job:'failed',model_calls:0,pin_unchanged:true})));
  console.log('Stale dispatch protection verified before claim and after routing: zero model calls; immutable pins; no bound retry');
  checkpoint('stale_dispatch_zero_calls');
  const recoveredAttempt=JSON.parse(evidenceFixture('bound-retry-copy',pid,boundJob.job_id).toString());
  assert.deepEqual(recoveredAttempt,{interrupted:true,rollback:true,immutable_history:true,duplicate_rejected:true,dispatcher:'succeeded',qa:'BLOCK',model_calls:4});
  console.log('Bound recovery verified: interrupted attempt, atomic rollback, immutable history, duplicate rejection, fresh dispatcher and QA BLOCK');
  const recoveryPath=base+'retry';
  const invalidRetry={queue_id:boundJob.queue.id,source_digest:'wrong',rationale:'Explicit recovery test with an invalid source.',confirmation:'RETRY BOUND WORK PACKAGE'};
  assert.equal((await post(viewer,vc,recoveryPath,invalidRetry)).status(),403);
  assert.equal((await post(reviewer,rc,recoveryPath,invalidRetry)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),recoveryPath,invalidRetry)).status(),403);
  assert.equal((await post(dev,dc,recoveryPath,invalidRetry)).status(),400);
  const dependentSubmitted=await post(dev,dc,dependentPath,dependentBody);
  assert.equal(dependentSubmitted.status(),202,await dependentSubmitted.text());
  const dependentJob=await dependentSubmitted.json();
  assert.equal(dependentJob.status,'queued');
  assert.equal(dependentJob.production_release_authorized,false);
  assert.ok(dependentJob.job_id&&dependentJob.queue_id);
  assert.notEqual(dependentJob.job_id,boundJob.job_id);
  assert.notEqual(dependentJob.queue_id,boundJob.queue.id);
  const dependentState=()=>get(owner,'/api/projects/'+pid+'/state');
  // Queue polling must not repeatedly run the expensive project evidence graph.
  // The existing 30-second dispatch deadline and every final evidence assertion remain.
  const dispatchStart=performance.now();
  const dependentDeadline=dispatchStart+30000;
  const dispatchSamples=[];
  let dependentQueue;
  while(performance.now()<dependentDeadline){
   const started=performance.now();
   const queue=await get(owner,'/api/projects/'+pid+'/queue');
   dependentQueue=queue.tasks.find(q=>q.id===dependentJob.queue_id);
   assert.ok(dependentQueue,'Dependent queue identity missing');
   assert.equal(dependentQueue.coding_job_id,dependentJob.job_id);
   dispatchSamples.push({elapsed_ms:Math.round(performance.now()-dispatchStart),
    request_ms:Math.round(performance.now()-started),status:dependentQueue.status,coding_status:dependentQueue.coding_status});
   if(dependentQueue.status==='succeeded')break;
   if(['dead','cancelled','interrupted'].includes(dependentQueue.status))break;
   await new Promise(r=>setTimeout(r,200));
  }
  console.log('Dependent dispatch lifecycle: '+JSON.stringify(dispatchSamples));
  assert.equal(dependentQueue?.status,'succeeded',JSON.stringify(dispatchSamples));
  assert.ok(performance.now()<=dependentDeadline,'Dependent dispatch exceeded original 30-second budget');
  const dependentReady=(await dependentState()).workflow.coding_jobs.find(j=>j.job_id===dependentJob.job_id);
  assert.equal(dependentReady?.queue?.status,'succeeded',JSON.stringify(dependentReady));
  assert.equal(dependentReady.status,'ready');
  assert.equal(dependentReady.planning_binding,'BOUND');
  assert.equal(dependentReady.queue.id,dependentJob.queue_id);
  assert.equal(dependentReady.source_binding.package_id,edge.target);
  assert.equal(dependentReady.source_binding.adoption_version,1);
  assert.equal(dependentReady.source_binding.binding_digest,dependentBinding);
  assert.equal(dependentReady.source_binding.spec_digest,eligible.source.spec_digest);
  assert.equal(dependentReady.source_binding.dependency_source_digest,eligible.source_digest);
  assert.equal(dependentReady.qa.state,'BLOCK');
  const pin=JSON.parse(evidenceFixture('dependency-pin',pid,dependentJob.job_id).toString());
  assert.equal(pin.digest,eligible.source_digest);
  assert.deepEqual(pin.source,eligible.source);
  assert.equal(pin.queue_id,dependentJob.queue_id);
  assert.equal(pin.actor,'ci-developer');
  assert.equal(pin.source.prerequisites[0].job_id,boundJob.job_id);
  assert.equal(pin.source.prerequisites[0].selected_digest,savedCompletion.receipt.selected_digest);
  assert.equal((await dependentState()).dependency_queue.items.find(x=>x.package_id===edge.target).state,'SUBMITTED');
  assert.equal((await post(owner,csrf,dependentPath,dependentBody)).status(),400);
  assert.equal((await post(owner,csrf,base+'coding',blockedLegacy)).status(),400);
  console.log('Dependent HTTP 202; real dispatcher succeeded; immutable prerequisite and contract pin verified');
  checkpoint('dependent_dispatch_and_pin');
  // QA cannot be attested using a successful queue alone.
  assert.equal((await post(reviewer,rc,base+'qa',{...qaBody,job_id:dependentJob.job_id})).status(),400);
  evidenceFixture('report',pid,dependentJob.job_id);
  let dependentQA=(await dependentState()).workflow.coding_jobs.find(j=>j.job_id===dependentJob.job_id).qa;
  assert.equal(dependentQA.state,'AWAITING_HUMAN_QA');
  assert.equal(dependentQA.source.dependency_source_digest,pin.digest);
  assert.equal(dependentQA.source.binding_digest,dependentBinding);
  assert.equal(dependentQA.latest_version,0);
  assert.ok(dependentQA.source.acceptance.length);
  assert.deepEqual(Object.keys(dependentQA.source.candidates).sort(),['A','B']);
  const dependentQARequest={job_id:dependentJob.job_id,source_digest:dependentQA.source_digest,expected_version:0,
   criteria:dependentQA.source.acceptance.map(c=>({id:c.id,verdict:'PASS',rationale:'Synthetic dependent acceptance fixture; not functional product certification.'})),
   confirmation:'ATTEST WORK PACKAGE QA'};
  assert.equal((await post(dev,dc,base+'qa',dependentQARequest)).status(),403);
  assert.equal((await post(reviewer,rc,base+'qa',{...dependentQARequest,source_digest:'wrong'})).status(),400);
  const dependentAttest=await post(reviewer,rc,base+'qa',dependentQARequest);
  assert.equal(dependentAttest.status(),201,await dependentAttest.text());
  const dependentReceipt=await dependentAttest.json();
  assert.equal(dependentReceipt.version,1);
  assert.equal(dependentReceipt.execution_authorized,false);
  const dependentPersisted=JSON.parse(evidenceFixture('qa-receipt',pid,dependentJob.job_id).toString());
  assert.equal(dependentPersisted.digest,dependentReceipt.digest);
  assert.equal(dependentPersisted.source_digest,dependentQARequest.source_digest);
  assert.deepEqual(dependentPersisted.criteria,dependentQARequest.criteria);
  dependentQA=(await dependentState()).workflow.coding_jobs.find(j=>j.job_id===dependentJob.job_id).qa;
  assert.equal(dependentQA.state,'HUMAN_QA_PASS');
  assert.equal(dependentQA.dependency_completed,false);
  assert.equal(dependentQA.production_release_authorized,false);
  console.log('Dependent QA HTTP 201; A/B sandbox evidence and persisted criterion receipt verified');
  checkpoint('dependent_qa_receipt');
  const dependentCompletionState=async()=> (await dependentState()).dependency_completion.items.find(x=>x.job_id===dependentJob.job_id);
  const dependentCandidate=await dependentCompletionState();
  assert.equal(dependentCandidate.state,'AWAITING_CONFIRMATION');
  assert.equal(dependentCandidate.source.dependency_source_digest,pin.digest);
  assert.equal(dependentCandidate.source.qa_digest,dependentReceipt.digest);
  const dependentCompletionBody={job_id:dependentJob.job_id,source_digest:dependentCandidate.source_digest,expected_version:0,selected:'A',
   rationale:'Synthetic dependent candidate reviewed explicitly for development evidence only.',
   confirmation:'CONFIRM DEPENDENCY COMPLETION DEV-A '+dependentJob.job_id};
  assert.equal((await post(dev,dc,completionPath,dependentCompletionBody)).status(),403);
  assert.equal((await post(reviewer,rc,completionPath,{...dependentCompletionBody,source_digest:'wrong'})).status(),400);
  const dependentCompleted=await post(reviewer,rc,completionPath,dependentCompletionBody);
  assert.equal(dependentCompleted.status(),201,await dependentCompleted.text());
  const dependentCompletedReceipt=await dependentCompleted.json();
  assert.equal(dependentCompletedReceipt.version,1);
  assert.equal(dependentCompletedReceipt.execution_authorized,false);
  assert.equal(dependentCompletedReceipt.automatic_dispatch,false);
  assert.equal(dependentCompletedReceipt.production_release_authorized,false);
  const dependentSaved=await dependentCompletionState();
  assert.equal(dependentSaved.state,'COMPLETION_EVIDENCE_CONFIRMED');
  assert.equal(dependentSaved.receipt.selected,'A');
  assert.equal(dependentSaved.receipt.digest,dependentCompletedReceipt.digest);
  const persistedCompletion=JSON.parse(evidenceFixture('dependency-completion',pid,dependentJob.job_id).toString());
  assert.equal(persistedCompletion.digest,dependentCompletedReceipt.digest);
  assert.equal(persistedCompletion.source_digest,dependentCompletionBody.source_digest);
  assert.equal(persistedCompletion.dependency_source_digest,pin.digest);
  assert.equal(persistedCompletion.selected_digest,dependentSaved.receipt.selected_digest);
  assert.equal((await post(reviewer,rc,completionPath,dependentCompletionBody)).status(),400);
  console.log('Dependent completion HTTP 201; selected candidate and upstream evidence pinned');
  checkpoint('dependent_completion_receipt');
  const verifyPackage=adopted.current.snapshot.bundle.wbs.document.deliverables.flatMap(d=>d.packages).find(p=>p.kind==='verify'&&p.depends_on.includes(wp.id));
  assert.ok(verifyPackage);
  const vb=await post(owner,csrf,base+'bind',{...bindingBody,package_id:verifyPackage.id});
  assert.equal(vb.status(),201);
  const verifyDigest=(await vb.json()).digest;
  const dbdy={adoption_version:1,package_id:verifyPackage.id,binding_digest:verifyDigest,source_digest:'missing',confirmation:'QUEUE DEPENDENT WORK PACKAGE'};
  assert.equal((await post(viewer,vc,dependentPath,dbdy)).status(),403);
  assert.equal((await post(reviewer,rc,dependentPath,dbdy)).status(),403);
  assert.equal((await post(owner,'0'.repeat(64),dependentPath,dbdy)).status(),403);
  assert.equal((await post(owner,csrf,dependentPath,dbdy)).status(),400);
  assert.equal((await get(owner,'/api/projects/'+pid+'/state')).dependency_queue.items.find(x=>x.package_id===verifyPackage.id).state,'BLOCK');
  assert.equal((await post(owner,csrf,completionPath,cbdy)).status(),400);
  evidenceFixture('reopen-check',pid,boundJob.job_id);
  evidenceFixture('report',pid,boundJob.job_id);
  const staleQA=(await get(owner,'/api/projects/'+pid+'/state')).workflow.coding_jobs.find(j=>j.job_id===boundJob.job_id).qa;
  assert.equal(staleQA.state,'STALE');
  assert.equal((await completionState()).state,'STALE');
  assert.equal((await get(owner,sandboxPath)).state,'STALE');
  assert.equal((await get(owner,draftPath)).state,'STALE_OR_INVALID');
  assert.equal((await get(owner,qualityPath)).state,'BLOCK');
  const qcStale=await get(owner,qcPath);
  assert.equal(qcStale.state,'BLOCK');
  assert.equal(qcStale.checks.human_qa,'BLOCK');
  assert.equal(qcStale.checks.sandbox,'BLOCK');
  fsSandbox.writeFileSync(process.env.ORBIT_ENGINEERING_QC_EVIDENCE,JSON.stringify({
   schema:'orbit.engineering-qc-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
   run_attempt:process.env.GITHUB_RUN_ATTEMPT,transport:'synthetic_inference_real_git_docker_http',
   open:qcOpen,passed:qcPassed,stale:qcStale,read_only:true
  }),{flag:'wx'});
  const planStale=await get(owner,testPlanPath);
  assert.equal(planStale.state,'STALE');
  assert.deepEqual(planStale.history,correctedPlan.history);
  assert.equal(planStale.assertion_status,'NOT_READY');
  assert.equal(planStale.assertion_contract_digest,null);
  assert.equal((await post(reviewer,rc,testPlanPath,{...planBody,expected_version:1})).status(),400);
  fsSandbox.writeFileSync(process.env.ORBIT_TEST_PLAN_EVIDENCE,JSON.stringify({
    schema:'orbit.acceptance-test-plan-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,transport:'synthetic_test_plan_real_http',
    initial:planInitial,passed:planPassed,stale:planStale,rbac_rejected:true,csrf_rejected:true,
    incomplete_rejected:true,duplicate_version_rejected:true,stale_write_rejected:true
  }),{flag:'wx'});
  fsSandbox.writeFileSync(process.env.ORBIT_ASSERTION_CONTRACT_EVIDENCE,JSON.stringify({
    schema:'orbit.assertion-contract-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,legacy:planPassed,upgraded:executablePlan,stale:planStale,
    shell_rejected:true,downgrade_rejected:true,rbac_rejected:true
  }),{flag:'wx'});
  assert.throws(()=>execFileSync('python',runnerArgs,{stdio:'pipe',timeout:60000}),e=>e.status===1);
  fsSandbox.writeFileSync(process.env.ORBIT_ASSERTION_RUNNER_EVIDENCE,JSON.stringify({
    schema:'orbit.assertion-runner-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,transport:'real_git_docker_assertions',
    result:runnerResult,rbac_rejected:true,stale_rejected:true
  }),{flag:'wx'});
  const registryStale=await get(owner,registryPath);
  assert.equal(registryStale.state,'STALE');
  assert.equal(registryStale.current_receipt,null);
  assert.deepEqual(registryStale.history,registryRecovered.history);
  assert.throws(()=>execFileSync('python',assertionArgsFor(correctedPlan,4),{stdio:'pipe',timeout:60000}),e=>e.status===1);
  fsSandbox.writeFileSync(process.env.ORBIT_ASSERTION_REGISTRY_EVIDENCE,JSON.stringify({
    schema:'orbit.assertion-registry-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,initial:registryInitial,first:registryPassed,second:registrySecond,
    stale:registryStale,duplicate_rejected:true,post_rejected:true,stale_rejected:true
  }),{flag:'wx'});
  const executionGateStale=await get(owner,executionGatePath);
  assert.equal(executionGateStale.state,'BLOCK');
  assert.equal(executionGateStale.checks.execution_receipt,'BLOCK');
  assert.equal(executionGateStale.checks.legacy_qc,'BLOCK');
  fsSandbox.writeFileSync(process.env.ORBIT_EXECUTION_GATE_EVIDENCE,JSON.stringify({
    schema:'orbit.execution-quality-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,before:executionGateBefore,passed:executionGatePassed,
    stale:executionGateStale,post_rejected:true,viewer_read:true
  }),{flag:'wx'});
  assert.throws(()=>execFileSync('python',[...guardArgs,gateRecovered.evidence_digest],{stdio:'pipe',timeout:60000}),e=>e.status===1);
  fsSandbox.writeFileSync(process.env.ORBIT_FINAL_EXECUTION_EVIDENCE,JSON.stringify({
    schema:'orbit.final-automated-test-execution.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,failed_plan:failedPlan,corrected_plan:correctedPlan,
    after_revision:{registry:registryAfterRevision,gate:gateAfterRevision},
    failed:{registry:registryFailed,gate:gateFailed,result:failedRun},
    before_recovery:{registry:registryBeforeRecovery,gate:gateBeforeRecovery},
    recovered:{registry:registryRecovered,gate:gateRecovered,result:recoveredRun},
    stale:{plan:planStale,registry:registryStale,gate:executionGateStale},
    stale_authorization_rejected:true,old_gate_digest_rejected:true,stale_guard_rejected:true
  }),{flag:'wx'});
  const gitChangesStale=await get(owner,gitChangesPath);
  assert.equal(gitChangesStale.state,'BLOCK');
  assert.deepEqual(gitChangesStale.comparisons,{});
  fsSandbox.writeFileSync(process.env.ORBIT_GIT_CHANGE_EVIDENCE,JSON.stringify({
    schema:'orbit.git-change-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,current:gitChanges,stale:gitChangesStale,
    viewer_read:true,post_rejected:true
  }),{flag:'wx'});
  const impactStale=await get(owner,impactPath);
  assert.equal(impactStale.state,'BLOCK');
  assert.deepEqual(impactStale.graphs,{});
  assert.equal(impactStale.full_regression_required,true);
  fsSandbox.writeFileSync(process.env.ORBIT_DEPENDENCY_IMPACT_EVIDENCE,JSON.stringify({
    schema:'orbit.dependency-impact-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,current:impactEvidence,stale:impactStale,
    viewer_read:true,post_rejected:true
  }),{flag:'wx'});
  const staleMapping=await get(owner,mappingPath);
  assert.equal(staleMapping.state,'BLOCK');
  assert.deepEqual(staleMapping.mappings,{});
  assert.equal(staleMapping.full_regression_required,true);
  fsSandbox.writeFileSync(process.env.ORBIT_IMPACTED_TEST_EVIDENCE,JSON.stringify({
    schema:'orbit.impacted-test-browser.v1',source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,
    run_attempt:process.env.GITHUB_RUN_ATTEMPT,initial:initialMapping,recovered:recoveredMapping,stale:staleMapping,
    viewer_read:true,post_rejected:true
  }),{flag:'wx'});
  console.log('P6.4d.3 exact impacted test mapping PASS');
  console.log('P6.4d.2 static dependency impact evidence PASS');
  console.log('P6.4d.1 exact Git tree change detection PASS');
  console.log('P6.4c.5 real assertion failure, durable BLOCK, explicit recovery and stale guard PASS');
  console.log('P6.4c.4 execution quality gate PASS');
  console.log('P6.4c.3 immutable assertion registry PASS');
  console.log('P6.4c.2 real Git/Docker individual assertions PASS');
  console.log('P6.4c.1 executable assertion contract and immutable legacy upgrade PASS');
  console.log('P6.4b acceptance test plan traceability and stale rejection PASS');
  console.log('P6.4a deterministic QC evidence, open/stale block and read-only HTTP PASS');
  assert.equal((await get(owner,'/api/projects/'+pid+'/state')).dependency_queue.items.find(x=>x.package_id===edge.target).state,'BLOCK');
  const staleDependent=(await dependentState()).workflow.coding_jobs.find(j=>j.job_id===dependentJob.job_id);
  assert.equal(staleDependent.planning_binding,'STALE');
  assert.equal(staleDependent.qa.state,'STALE');
  assert.equal((await dependentCompletionState()).state,'STALE');
  assert.equal((await post(reviewer,rc,completionPath,{...dependentCompletionBody,expected_version:1})).status(),400);
  assert.equal((await post(reviewer,rc,base+'qa',{...dependentQARequest,expected_version:1})).status(),400);
  console.log('Upstream report replacement invalidates dependent pin, QA and completion evidence');
  checkpoint('upstream_stale_propagation');
  assert.equal((await post(owner,csrf,completionPath,{...cbdy,expected_version:1})).status(),400);
  assert.equal((await post(owner,csrf,base+'qa',{...qaBody,source_digest:currentQA.source_digest,expected_version:1,criteria:currentQA.receipt.criteria})).status(),400);
  await studio.close();
  // Compare renderer cadence before retiring the long-lived page and after
  // creating a fresh page. The 1s sampling window is diagnostic, not a retry
  // or increase of any existing assertion/action timeout.
  const sampleFrames=page=>page.evaluate(()=>new Promise(resolve=>{
   const samples=[];const started=performance.now();let raf,timer,done=false;
   const finish=()=>{
    if(done)return;done=true;clearTimeout(timer);cancelAnimationFrame(raf);
    const stable=samples.some((s,i)=>i>0&&s.rect!==null&&JSON.stringify(s.rect)===JSON.stringify(samples[i-1].rect));
    resolve({visibility:document.visibilityState,focused:document.hasFocus(),elapsedMs:Math.round(performance.now()-started),frameCount:samples.length,stable,samples});
   };
   const tick=stamp=>{
    const b=document.querySelector('#reload'),r=b?.getBoundingClientRect();
    samples.push({stamp:Math.round(stamp*100)/100,rect:r?[r.x,r.y,r.width,r.height]:null,disabled:b?.disabled??null});
    if(samples.length===6)finish();else raf=requestAnimationFrame(tick);
   };
   timer=setTimeout(finish,1000);raf=requestAnimationFrame(tick);
  }));
  await owner.bringToFront();
  console.log('Retiring planning renderer: '+JSON.stringify(await sampleFrames(owner)));
  // No re-login, new project, database reset, or injected application state.
  const beforeIsolation=await get(owner,pp);
  assert.equal(beforeIsolation.current,null);
  assert.equal(beforeIsolation.wbs.adoption.current.digest,adopted.current.digest);
  // Transfer existing authenticated storage states in memory. A new process,
  // not merely a new page, isolates the legacy phase from the long-lived renderer.
  const ownerState=await ownerContext.storageState();
  const reviewerState=await reviewer.context().storageState();
  const devState=await dev.context().storageState();
  await owner.close();
  await browser.close();
  recoveryBrowser=await chromium.launch({headless:true});
  const legacyContext=await recoveryBrowser.newContext({storageState:ownerState});
  const legacy=await legacyContext.newPage();
  assert.equal(legacy.context(),legacyContext);
  assert.notEqual(legacyContext.browser(),browser);
  const sameSession=await get(legacy,'/api/auth/session');
  assert.equal(sameSession.csrf_token,csrf);
  assert.equal(sameSession.user,'ci-browser-user');
  legacy.on('dialog',d=>d.accept());
  await legacy.bringToFront();
  await openPlanning(legacy,pid,beforeIsolation.requirements_input.digest,'owner');
  checkpoint('owner_navigation_bootstrap');
  const afterIsolation=await get(legacy,pp);
  assert.equal(afterIsolation.current,null);
  assert.deepEqual(afterIsolation.wbs.adoption.current,beforeIsolation.wbs.adoption.current);
  assert.equal(afterIsolation.requirements_input.digest,beforeIsolation.requirements_input.digest);
  const freshFrames=await sampleFrames(legacy);
  console.log('Fresh planning renderer and unchanged session/project: '+JSON.stringify(freshFrames));
  assert.ok(freshFrames.frameCount>=2&&freshFrames.stable,'Fresh renderer must produce consecutive stable frames');
  checkpoint('same_session_and_adoption');
  // Observe the exact mutation HTTP response; a UI timeout alone hides its cause.
  let seedCommitted=false,failedRefreshCount=0;
  const planningUrl=ORIGIN+pp;
  const seedUrl=planningUrl+'/seed';
  const interceptSeed=async route=>{
   assert.equal(route.request().method(),'POST');
   const response=await route.fetch();
   const state=await response.json();
   seedCommitted=response.ok();
   await route.fulfill({status:response.status(),json:state,headers:{'cache-control':'no-store'}});
  };
  const failRefresh=async route=>{
   if(seedCommitted&&route.request().method()==='GET'&&failedRefreshCount===0){
    ++failedRefreshCount;
    await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({error:'Synthetic reload failure after committed seed'})});
   }else await route.continue();
  };
  await legacy.route(planningUrl,failRefresh);
  await legacy.route(seedUrl,interceptSeed,{times:1});
  try{
   const [seedResponse,failedRefresh]=await Promise.all([
    legacy.waitForResponse(r=>r.url()===seedUrl&&r.request().method()==='POST'),
    legacy.waitForResponse(r=>r.url()===planningUrl&&r.request().method()==='GET'&&r.status()===503),
    legacy.locator('#seed').click()
   ]);
   assert.equal(seedResponse.status(),200,await seedResponse.text());
   assert.equal((await seedResponse.json()).current.version,1);
   assert.equal(failedRefresh.status(),503);
   assert.equal(failedRefreshCount,1);
   await legacy.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('Plan v1'));
   await legacy.waitForFunction(()=>document.querySelector('#status').textContent.includes('tải lại thất bại'));
   assert.equal(await legacy.locator('#seed').isDisabled(),true);
   assert.equal(await legacy.locator('#save').isDisabled(),true);
   assert.equal(await legacy.locator('#reload').isDisabled(),false);
  }finally{
   // These are the only routes on the legacy page. Drain all active handlers
   // before restoring normal network traffic. Do not ignore handler errors.
   await legacy.unrouteAll({behavior:'wait'});
  }
  const reloadButton=legacy.locator('#reload');
  const reloadDiagnostics=()=>reloadButton.evaluate(button=>{
   const rect=button.getBoundingClientRect(),style=getComputedStyle(button);
   const x=rect.left+rect.width/2,y=rect.top+rect.height/2;
   const hit=document.elementFromPoint(x,y);
   return {visibility:document.visibilityState,focused:document.hasFocus(),disabled:button.disabled,
    display:style.display,visibilityStyle:style.visibility,scrollBehavior:getComputedStyle(document.documentElement).scrollBehavior,
    rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},viewport:{width:innerWidth,height:innerHeight},
    scroll:{x:scrollX,y:scrollY},hit:hit?{tag:hit.tagName,id:hit.id}:null,
    panelHidden:document.querySelector('#panel').hidden,status:document.querySelector('#status').textContent};
  });
  await legacy.bringToFront();
  assert.equal(await reloadButton.isVisible(),true);
  assert.equal(await reloadButton.isEnabled(),true);
  const beforeScroll=await reloadDiagnostics();
  assert.equal(beforeScroll.scrollBehavior,'auto');
  const recoveryFrames=await sampleFrames(legacy);
  console.log('Legacy reload renderer after HTTP 503: '+JSON.stringify(recoveryFrames));
  assert.ok(recoveryFrames.frameCount>=2&&recoveryFrames.stable,'Reload recovery must produce consecutive stable frames');
  checkpoint('recovery_stable_frames');
  let manualReload;
  try{
   // Normal user-equivalent scrolling and clicking; keep all actionability
   // checks active and use the existing Playwright timeouts.
   await reloadButton.scrollIntoViewIfNeeded();
   console.log('Legacy reload actionability before click: '+JSON.stringify(await reloadDiagnostics()));
   [manualReload]=await Promise.all([
    legacy.waitForResponse(r=>r.url()===planningUrl&&r.request().method()==='GET'),
    reloadButton.click()
   ]);
  }catch(err){
   console.error('Legacy reload actionability failure: '+JSON.stringify(await reloadDiagnostics()));
   console.error('Legacy reload frame cadence on failure: '+JSON.stringify(await sampleFrames(legacy)));
   throw err;
  }
  assert.equal(manualReload.status(),200,await manualReload.text());
  const recovered=await manualReload.json();
  assert.equal(recovered.project_id,pid);
  assert.equal(recovered.current.version,1);
  await legacy.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('Plan v1')&&!document.querySelector('#save').disabled);
  let data=await get(legacy,pp);assert.equal(data.execution_ready,false);assert.equal(data.analysis.task_count,4);
  assert.equal(recovered.current.digest,data.current.digest);
  console.log('Legacy seed HTTP 200; exactly one refresh HTTP 503; manual reload HTTP 200 and persisted Plan v1 digest verified');
  checkpoint('legacy_reload_and_digest');
  assert.equal(await legacy.locator('#tasks tr').count(),4);
  const approval={version:1,digest:data.current.digest,requirements_version:req.version,requirements_digest:req.digest,confirmation:'APPROVE PROJECT PLAN'};
  const legacyReviewerContext=await recoveryBrowser.newContext({storageState:reviewerState});
  const legacyReviewerSession=await get(legacyReviewerContext,'/api/auth/session');
  assert.equal(legacyReviewerSession.csrf_token,rc);
  assert.equal(legacyReviewerSession.user,'ci-reviewer');
  assert.equal((await post(legacyReviewerContext,rc,pp+'/approve',approval)).status(),400);
  let estimated=data.current.document;for(const task of estimated.tasks)task.effort_minutes=15;
  await legacy.locator('#document').fill(JSON.stringify(estimated));
  const [saveResponse]=await Promise.all([legacy.waitForResponse(r=>r.url()===planningUrl&&r.request().method()==='POST'),legacy.locator('#save').click()]);
  assert.equal(saveResponse.status(),200,await saveResponse.text());
  await legacy.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('Plan v2')&&!document.querySelector('#reload').disabled);
  data=await get(legacy,pp);assert.equal(data.analysis.total_effort_minutes,60);
  assert.equal(data.analysis.dependency_graph.critical_path_minutes,30);
  assert.equal(data.analysis.dependency_graph.critical_nodes.length,4);
  await legacy.locator('#graph-source').selectOption('plan');
  await legacy.waitForFunction(()=>document.querySelector('#graph-status').textContent.includes('CPM READY · 30 phút'));
  assert.equal(await legacy.locator('#graph-nodes tr').count(),4);
  assert.equal(await legacy.locator('#graph-edges li').count(),2);
  const ready={...approval,version:2,digest:data.current.digest};
  const legacyDevContext=await recoveryBrowser.newContext({storageState:devState});
  const legacyDevSession=await get(legacyDevContext,'/api/auth/session');
  assert.equal(legacyDevSession.csrf_token,dc);
  assert.equal(legacyDevSession.user,'ci-developer');
  assert.equal((await post(legacyDevContext,dc,pp+'/approve',ready)).status(),403);
  await legacyDevContext.close();
  const legacyReviewer=await legacyReviewerContext.newPage();
  legacyReviewer.on('dialog',d=>d.accept());
  await legacyReviewer.bringToFront();
  await openPlanning(legacyReviewer,pid,beforeIsolation.requirements_input.digest,'reviewer');
  checkpoint('reviewer_navigation_bootstrap');
  assert.equal(await legacyReviewer.locator('#save').isDisabled(),true);
  const [approveResponse]=await Promise.all([legacyReviewer.waitForResponse(r=>r.url()===planningUrl+'/approve'&&r.request().method()==='POST'),legacyReviewer.locator('#approve').click()]);
  assert.equal(approveResponse.status(),200,await approveResponse.text());
  await legacyReviewer.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('READY')&&!document.querySelector('#reload').disabled);
  await legacyReviewerContext.close();
  assert.equal((await get(legacy,pp)).execution_ready,true);
  assert.equal((await post(legacy,csrf,rp,{expected_version:1,document:doc})).status(),200);
  await legacy.bringToFront();
  await legacy.locator('#reload').click();await legacy.waitForFunction(()=>document.querySelector('#plan-state').textContent.includes('STALE'));
  assert.equal((await get(legacy,pp)).execution_ready,false);
  assert.equal((await get(legacy,pp)).analysis,null);
  assert.equal((await get(legacy,pp)).wbs.dependency_graph,null);
  await legacy.waitForFunction(()=>document.querySelector('#graph-status').textContent.includes('STALE'));
  assert.equal(await legacy.locator('#graph-nodes tr').count(),0);
  assert.equal((await get(legacy,pp)).wbs.stale,true);
  assert.equal((await get(legacy,pp)).wbs.decomposition_ready,false);
  assert.equal(await legacy.locator('#wbs-save').isDisabled(),true);
  assert.equal(await legacy.locator('#estimate-save').isDisabled(),true);
  assert.equal(await legacy.locator('#schedule-save').isDisabled(),true);
  assert.equal(await legacy.locator('#review-run').isDisabled(),true);
  assert.equal(await legacy.locator('#adopt-bundle').isDisabled(),true);
  const staleAdoption=(await get(legacy,pp)).wbs.adoption;
  assert.equal(staleAdoption.stale,true);assert.equal(staleAdoption.current.digest,adopted.current.digest);
  assert.equal((await get(legacy,pp)).wbs.cross_review.quality_ready,false);
  assert.equal((await get(legacy,'/api/projects/'+pid+'/state')).dependency_extension.state,'STALE');
  const staleStudio=(await get(legacy,'/api/projects/'+pid+'/state')).workflow;
  assert.equal(staleStudio.coding_jobs.find(j=>j.job_id===boundJob.job_id).planning_binding,'STALE');
  assert.equal((await get(legacy,'/api/projects/'+pid+'/state')).engineering.contracts.find(x=>x.package_id===wp.id).state,'STALE');
  assert.equal((await post(legacy,csrf,engineeringPath,{...ebdy,expected_version:1})).status(),400);
  assert.equal((await post(legacy,csrf,base+'coding',queueBody)).status(),400);
  assert.equal((await get(legacy,pp)).wbs.sprint_schedule.analysis,null);
  assert.equal(await legacy.locator('#seed').isDisabled(),true);
  assert.equal((await post(legacy,csrf,pp+'/seed',{...seed,expected_version:2})).status(),400);
  checkpoint('legacy_approval_and_prd_stale');
 }finally{
  try{if(recoveryBrowser)await recoveryBrowser.close()}
  finally{if(browser.isConnected())await browser.close()}
 }
 // Only emit after every assertion AND browser cleanup succeeds. The whole
 // node test suite must also pass before CI verifies or accepts this evidence.
 if(process.env.ORBIT_DEPENDENCY_EVIDENCE){
  assert.equal(process.env.ORBIT_REQUIREMENTS_BROWSER_FIXTURE,'1');
  const report={schema:'orbit.dependency-browser-evidence.v1',milestone:'P6.3c.1e',
   source_commit:process.env.GITHUB_SHA,run_id:process.env.GITHUB_RUN_ID,run_attempt:process.env.GITHUB_RUN_ATTEMPT,
   transport:'isolated_synthetic_inference_and_sandbox_fixture',checkpoints:evidence,
   automatic_dispatch:false,execution_authorized:false,merge_authorized:false,production_release_authorized:false};
  require('node:fs').writeFileSync(process.env.ORBIT_DEPENDENCY_EVIDENCE,JSON.stringify(report,null,2)+'\n',{flag:'wx'});
 }
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
