/** Real Chromium browser E2E for the ORBIT Web-first MVP. No AI-generated code executed. */
'use strict';
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { chromium } = require('playwright');

const {login,headers,ORIGIN}=require('./auth-helper.cjs');

test('Web-first UI boots, project form excludes Mobile and creates a Web project', async () => {
  const browser = await chromium.launch({headless: true, args: ['--disable-gpu', '--no-sandbox']});
  const page = await browser.newPage({viewport: {width: 1365, height: 850}});
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  try {
    await login(page);
    for(const [path,mime] of [['/studio-line.js',/javascript/],['/studio-line.css',/text\/css/]]){
      const asset=await page.request.get(ORIGIN+path);
      assert.equal(asset.status(),200,path+' must be served by static allowlist');
      assert.match(asset.headers()['content-type'],mime);
    }
    assert.equal((await page.request.get(ORIGIN+'/not-allowlisted.js')).status(),404);
    const response = await page.goto(ORIGIN + '/', {waitUntil: 'domcontentloaded'});
    assert.equal(response.status(), 200);
    await page.locator('#projectSide .project-item').first().waitFor({timeout: 15000});
    await page.waitForFunction(() => document.querySelectorAll('#agentMembers .agent-card').length === 2, null, {timeout: 15000});
    assert.equal(await page.locator('#agentMembers .agent-card').count(), 2);
    assert.equal(await page.locator('#pipelineTrack').isVisible(), true);
    await page.locator('#studioLine[data-ready="true"]').waitFor({state:'visible'});
    const initialId=await page.locator('#studioLine').getAttribute('data-project-id');
    assert.ok(initialId);
    assert.equal(await page.locator('#studioLine [data-role-id]').count(),12);
    assert.equal(await page.locator('#studioLine .line-lane').count(),24);
    assert.deepEqual(await page.locator('#studioLine [data-role-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.roleId)),['po','research','ba','pm','design','techlead','dev','qa','qc','security','devops','marketing']);
    await page.locator('[data-role-id="pm"] .line-select').click();
    assert.equal(await page.locator('#officeDetails').evaluate(e=>e.open),true);
    assert.equal(await page.locator('#deptName').textContent(),'Project Manager');
    assert.equal(await page.locator('#roleWorkspace').getAttribute('data-role'),'pm');
    assert.equal(await page.locator('#roleWorkspace').getAttribute('data-project-id'),initialId);
    const roleIds=['po','research','ba','pm','design','techlead','dev','qa','qc','security','devops','marketing'];
    const titles=new Set();
    for(const role of roleIds){
      await page.locator('[data-role-id="'+role+'"] .line-select').click();
      assert.equal(await page.locator('#roleWorkspace').getAttribute('data-role'),role);
      titles.add(await page.locator('#roleWorkspace h2').textContent());
      assert.equal(await page.locator('#roleWorkspace .role-workspace-panel').count(),7);
    }
    assert.equal(titles.size,12);
    await page.locator('[data-role-id="pm"] .line-select').click();
    assert.equal(await page.locator('#roleWorkspace [data-focus-key="workspace-link"]').getAttribute('href'),'/planning.html');
    assert.equal(await page.locator('[data-role-id="pm"] .line-link').getAttribute('href'),'/planning.html');
    await page.locator('#newProjectBtn').click();
    await page.locator('#createModal:not(.hidden)').waitFor();
    const options = await page.locator('#newProjectForm select[name=platform] option').allTextContents();
    assert.deepEqual(options, ['Web app', 'SaaS + API']);
    const name = 'Web E2E ' + Date.now();
    await page.locator('#newProjectForm input[name=name]').fill(name);
    await page.locator('#newProjectForm textarea[name=idea]').fill('Test web application end to end with real Chromium and backend persistence');
    await page.locator('#newProjectForm button[type=submit]').click();
    await page.locator('#createModal').waitFor({state: 'hidden', timeout: 15000});
    await page.getByText(name, {exact: true}).first().waitFor({timeout: 15000});
    const state = await page.evaluate(async () => {
      const projects = (await (await fetch('/api/bootstrap')).json()).projects;
      const target = projects.find(p => p.name===document.querySelector('#projectSide .project-item.active strong').textContent);
      return {platform: target.platform, id: target.id};
    });
    assert.equal(state.platform, 'Web app');
    const detail = await (await page.request.get(ORIGIN + '/api/projects/' + state.id + '/state')).json();
    assert.equal(detail.tasks.length, 12);
    assert.equal(detail.project.platform, 'Web app');
    assert.equal(detail.handoff.project_id,state.id);
    assert.equal(detail.handoff.roles.length,12);
    assert.equal(detail.handoff.roles[0].input_status,'project_idea');
    assert.ok(detail.handoff.roles.every(r=>r.output.status==='blocked'&&r.consumption_status==='NOT_RECORDED'));
    assert.equal(detail.handoff.production_release_authorized,false);
    assert.notEqual(state.id,initialId);
    await page.waitForFunction(pid=>document.querySelector('#studioLine').dataset.projectId===pid&&document.querySelector('#studioLine').dataset.ready==='true',state.id);
    assert.equal(await page.locator('#studioLine [data-role-id]').count(),12);
    assert.equal(await page.locator('#studioLine .line-lane').count(),24);
    assert.deepEqual(await page.locator('#studioLine [data-role-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.status)),detail.tasks.map(t=>t.status));
    // Hold a real state response in the page, not a Playwright Route.
    // This also observes JSON consumption, rather than merely network arrival.
    await page.evaluate(pid=>{
      const original=window.fetch;
      const gate={held:false,released:false,consumed:false,failed:false};
      let release;
      const pending=new Promise(resolve=>{release=resolve});
      gate.release=()=>{gate.released=true;release()};
      window.__studioTestGate=gate;
      window.fetch=async function(input,...args){
        const response=await original.call(this,input,...args);
        const path=new URL(typeof input==='string'?input:input.url,location.href).pathname;
        if(path!=='/api/projects/'+pid+'/state'||gate.held)return response;
        const originalJson=response.json.bind(response);
        response.json=async()=>{
          const data=await originalJson();
          gate.held=true;
          await pending;
          // The next browser task runs after the application's await continuation.
          setTimeout(()=>{gate.consumed=true},0);
          return data;
        };
        return response;
      };
      gate.restore=()=>{gate.release();window.fetch=original};
    },state.id);
    try{
      await page.waitForFunction(()=>window.__studioTestGate.held,null,{timeout:10000});
      await page.locator('#projectSide [data-pid="'+initialId+'"]').click();
      await page.waitForFunction(pid=>document.querySelector('#studioLine').dataset.projectId===pid&&document.querySelector('#studioLine').dataset.ready==='true',initialId,{timeout:10000});
      // Record any transient repaint too, not only the final polling state.
      await page.evaluate(()=>{
        const holder=document.querySelector('#studioLine'),gate=window.__studioTestGate;
        gate.observed=[];
        gate.observer=new MutationObserver(()=>gate.observed.push(holder.dataset.projectId||null));
        gate.observer.observe(holder,{attributes:true,attributeFilter:['data-project-id']});
        gate.release();
      });
      await page.waitForFunction(()=>window.__studioTestGate.consumed,null,{timeout:10000});
      const isolation=await page.evaluate(()=>{
        const gate=window.__studioTestGate,holder=document.querySelector('#studioLine');
        gate.observer.disconnect();
        return {project:holder.dataset.projectId,ready:holder.dataset.ready,observed:gate.observed,
          roles:holder.querySelectorAll('[data-role-id]').length,agents:holder.querySelectorAll('.line-lane').length};
      });
      assert.equal(isolation.project,initialId);
      assert.equal(isolation.ready,'true');
      assert.ok(isolation.observed.every(pid=>pid===initialId),'Obsolete response repainted the selected project');
      assert.equal(isolation.roles,12);
      assert.equal(isolation.agents,24);
      assert.equal(await page.locator('#roleWorkspace').getAttribute('data-project-id'),initialId);
    }finally{
      await page.evaluate(()=>{const gate=window.__studioTestGate;gate.observer?.disconnect();gate.restore();delete window.__studioTestGate});
    }
    await page.locator('#projectSide [data-pid="'+state.id+'"]').click();
    await page.waitForFunction(pid=>document.querySelector('#studioLine').dataset.projectId===pid&&document.querySelector('#studioLine').dataset.ready==='true',state.id,{timeout:10000});
    assert.deepEqual(await page.locator('#studioLine [data-role-id]').evaluateAll(nodes=>nodes.map(n=>n.dataset.status)),detail.tasks.map(t=>t.status));
    assert.equal(await page.locator('#roleWorkspace').getAttribute('data-project-id'),state.id);
    assert.equal(await page.locator('#roleWorkspace .role-handoff').getAttribute('data-output-status'),'blocked');
    assert.match(await page.locator('#roleWorkspace .role-handoff').textContent(),/NOT_RECORDED/);
    await page.setViewportSize({width:390,height:844});
    assert.equal(await page.locator('#roleWorkspace .role-workspace-grid').first().evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),1);
    assert.equal(await page.locator('#studioLine .line-row').first().evaluate(e=>getComputedStyle(e).gridTemplateColumns.split(' ').length),1);
    assert.equal(await page.locator('#studioLine [data-role-id]').count(),12);
    assert.equal(await page.locator('#studioLine .line-lane').count(),24);
    assert.deepEqual(errors, [], 'Unexpected browser JavaScript errors: ' + errors.join('; '));
  } finally {
    await browser.close();
  }
});

test('API rejects cross-origin and unsafe project creation', async () => {
  const browser = await chromium.launch({headless: true, args: ['--disable-gpu', '--no-sandbox']});
  const page = await browser.newPage();
  try {
    const csrf=await login(page);
    const bootstrap = await page.request.get(ORIGIN + '/api/bootstrap');
    assert.equal(bootstrap.status(), 200);
    const data = await bootstrap.json();
    assert.equal(data.version, '0.6.0-web-first');
    assert.equal(data.agents.length, 24);
    const forbidden = await page.request.post(ORIGIN + '/api/projects', {
      headers: {'Content-Type':'application/json', 'X-ORBIT-UI':'1', 'Origin':'https://attacker.invalid'},
      data: {name:'Bad', idea:'Must not create this project'}
    });
    assert.equal(forbidden.status(), 403);
    const invalid = await page.request.post(ORIGIN + '/api/projects', {
      headers: headers(csrf),
      data: {name:'A', idea:'short'}
    });
    assert.equal(invalid.status(), 400);
  } finally {
    await browser.close();
  }
});

test('Quality dashboard shows unverified state for a real demo coding job', async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();
  const csrf=await login(page);
  await page.goto(ORIGIN+'/');
  await page.locator('#projectSide .project-item').first().waitFor();
  const b=await (await page.request.get(ORIGIN+'/api/bootstrap')).json();
  const pid=b.projects[0].id;
  const res=await page.request.post(ORIGIN+'/api/coding/start',{headers:headers(csrf),data:{project_id:pid,spec:'Quality dashboard browser test for a demo web feature'}});
  assert.equal(res.status(),202);
  const {job_id}=await res.json();
  await page.evaluate(id=>localStorage.setItem('orbit-project',id),pid);
  await page.reload();
  await page.locator('[data-job="'+job_id+'"]').click({timeout:20000});
  await page.waitForFunction(()=>document.querySelector('#codingQuality').textContent.includes('NOT VERIFIED'),null,{timeout:20000});
  const q=await (await page.request.get(ORIGIN+'/api/coding/'+job_id+'/quality')).json();
  assert.equal(q.selection_ready,false);
  assert.equal(q.production_approved,false);
  assert.match(await page.locator('#codingQuality').textContent(),/CHƯA NGHIỆM THU/);
 }finally{await browser.close()}
});

test('Studio handoff shows actual queued demo source and durable downstream receipt',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1365,height:850}});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  const csrf=await login(page);
  const created=await page.request.post(ORIGIN+'/api/projects',{headers:headers(csrf),data:{name:'Handoff E2E '+Date.now(),idea:'Verify real queued demo handoff and durable source binding',platform:'Web app'}});
  assert.equal(created.status(),201);
  const pid=(await created.json()).project_id;
  await page.addInitScript(({origin,id})=>{if(location.origin===origin)localStorage.setItem('orbit-project',id)},{origin:ORIGIN,id:pid});
  await page.goto(ORIGIN+'/');
  await page.locator('#projectSide [data-pid="'+pid+'"]').click();
  await page.waitForFunction(id=>document.querySelector('#studioLine').dataset.projectId===id&&document.querySelector('#studioLine').dataset.ready==='true',pid,{timeout:15000});
  const path=ORIGIN+'/api/projects/'+pid;
  async function step(stage){
   const started=await page.request.post(path+'/run',{headers:headers(csrf),data:{mode:'next'}});
   assert.ok([200,202].includes(started.status()),await started.text());
   const deadline=Date.now()+20000;
   while(Date.now()<deadline){
    const response=await page.request.get(path+'/state');
    assert.equal(response.status(),200);
    const data=await response.json();
    if(!data.running&&data.tasks.find(t=>t.stage_id===stage).status==='done')return data;
    await new Promise(resolve=>setTimeout(resolve,150));
   }
   assert.fail('Stage did not complete: '+stage);
  }
  const first=await step('po');
  assert.equal(first.workflow.project_id,pid);
  assert.equal(first.workflow.requirements.state,'MISSING');
  assert.equal(first.workflow.next_checkpoint,'APPROVE_PRD');
  assert.equal(first.workflow.execution_authorized,false);
  assert.ok(first.workflow.queue.tasks.some(q=>q.kind==='pipeline'&&q.status==='succeeded'));
  await page.locator('#studioWorkflow[data-project-id="'+pid+'"] [data-workflow-stage="requirements"]').waitFor();
  const source=first.handoff.roles[0].output;
  assert.equal(source.status,'reviewed_output');
  assert.match(source.content_digest,/^[a-f0-9]{64}$/);
  const second=await step('research');
  const target=second.handoff.roles[1];
  assert.equal(target.input_status,'reviewed_sources_available');
  assert.equal(target.output.status,'reviewed_output');
  assert.equal(target.consumption_status,'DEMO_DRAFTS');
  assert.equal(target.receipt.mode,'demo');
  const gate=second.quality.roles.find(r=>r.stage_id==='research');
  assert.equal(gate.state,'REVIEWED_OUTPUT');
  assert.equal(gate.mode,'demo');
  assert.equal(gate.run_id,target.receipt.run_id);
  assert.equal(gate.final.id,target.output.artifact_id);
  assert.deepEqual(gate.reviews.map(r=>r.score).sort((a,b)=>a-b),[89,92]);
  assert.equal(second.quality.production_release_authorized,false);
  const observed=second.activity.roles.find(r=>r.stage_id==='research');
  assert.equal(observed.run_id,target.receipt.run_id);
  assert.equal(observed.queue.status,'succeeded');
  assert.deepEqual(observed.agents.map(a=>a.state),['DEMO_DRAFT_RECORDED','DEMO_DRAFT_RECORDED']);
  assert.ok(observed.agents.every(a=>a.stage_attempt===null));
  assert.deepEqual(target.receipt.lanes,['A','B']);
  assert.deepEqual(target.receipt.sources,[source]);
  assert.match(target.receipt.context_digest,/^[a-f0-9]{64}$/);
  assert.equal(second.handoff.production_release_authorized,false);
  const researchButton=page.locator('[data-role-id="research"] .line-select');
  await researchButton.click();
  try{
   assert.equal(await researchButton.getAttribute('aria-pressed'),'true','Research selection was lost during polling');
   await page.locator('#roleWorkspace[data-project-id="'+pid+'"][data-role="research"] .role-handoff[data-consumption-status="DEMO_DRAFTS"][data-output-status="reviewed_output"]').waitFor({timeout:15000});
  }catch(err){
   console.error('Handoff renderer diagnostic: '+JSON.stringify(await page.evaluate(()=>{
    const line=document.querySelector('#studioLine'),role=document.querySelector('#roleWorkspace'),h=role?.querySelector('.role-handoff');
    return {project:line?.dataset.projectId,ready:line?.dataset.ready,role:role?.dataset.role,roleProject:role?.dataset.projectId,
      stale:role?.dataset.stale,selected:line?.querySelector('[aria-pressed="true"]')?.closest('[data-role-id]')?.dataset.roleId,
      consumption:h?.dataset.consumptionStatus,output:h?.dataset.outputStatus};
   })));
   throw err;
  }
  assert.equal(await page.locator('#roleWorkspace [data-activity-agent][data-activity-state="DEMO_DRAFT_RECORDED"]').count(),2);
  await page.locator('#roleWorkspace .role-quality[data-quality-state="REVIEWED_OUTPUT"]').waitFor();
  assert.equal(await page.locator('#roleWorkspace .role-quality [data-review-id]').count(),2);
  assert.match(await page.locator('#roleWorkspace .role-quality').textContent(),/DEMO/);
  const panel=page.locator('#roleWorkspace .role-handoff');
  assert.match(await panel.textContent(),new RegExp(source.content_digest));
  assert.match(await panel.textContent(),new RegExp(target.receipt.context_digest));
  await panel.locator('[data-focus-key="handoff-'+source.artifact_id+'"]').click();
  await page.locator('#artifactModal:not(.hidden)').waitFor();
  assert.match(await page.locator('#artifactBody').textContent(),/DEMO/);
  await page.locator('#artifactModal').getByRole('button',{name:'Đóng',exact:true}).click();
  await page.locator('#artifactModal').waitFor({state:'hidden'});
  await page.reload();
  await page.locator('#studioLine[data-ready="true"]').waitFor({timeout:15000});
  await page.locator('[data-role-id="research"] .line-select').click();
  await page.locator('#roleWorkspace .role-handoff[data-consumption-status="DEMO_DRAFTS"]').waitFor({timeout:15000});
  assert.match(await page.locator('#roleWorkspace .role-handoff').textContent(),new RegExp(target.receipt.context_digest));
  assert.deepEqual(errors,[]);
 }finally{await browser.close()}
});

test('Studio orchestration controls fail closed without adopted source and preserve project permission scope',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:390,height:844}});const csrf=await login(page);
  const created=await page.request.post(ORIGIN+'/api/projects',{headers:headers(csrf),data:{name:'SG6e '+Date.now(),idea:'Studio orchestration permission and missing source fixture',platform:'Web app'}});
  assert.equal(created.status(),201);const pid=(await created.json()).project_id;
  // Mobile CSS intentionally hides .project-side at <=760px. Restore the
  // existing persisted project selection before application bootstrap.
  await page.addInitScript(({origin,id})=>{if(location.origin===origin)localStorage.setItem('orbit-project',id)},{origin:ORIGIN,id:pid});
  await page.goto(ORIGIN+'/');
  await page.locator('#studioLine[data-project-id="'+pid+'"][data-ready="true"]').waitFor({timeout:15000});
  await page.locator('#studioWorkflow[data-project-id="'+pid+'"]').waitFor();
  assert.equal(await page.locator('#projectSide').isVisible(),false);
  assert.equal(await page.evaluate(()=>localStorage.getItem('orbit-project')),pid);
  assert.equal(await page.locator('#projectSide [data-pid="'+pid+'"].active').count(),1);
  const state=await (await page.request.get(ORIGIN+'/api/projects/'+pid+'/state')).json();
  assert.deepEqual(state.workflow_permissions,{project_id:pid,can_write:true,can_approve:true});
  assert.equal(await page.locator('#studioWorkflow [data-workflow-stage="qa"]').count(),1);
  assert.equal(await page.locator('#studioWorkflow form[data-studio-action]').count(),0);
  const response=await page.request.post(ORIGIN+'/api/projects/'+pid+'/studio/work-packages/bind',{headers:headers(csrf),data:{adoption_version:1,bundle_digest:'bad',package_id:'missing',confirmation:'BIND ADOPTED WORK PACKAGE'}});
  assert.ok(response.status()>=400);
  assert.equal(await page.locator('#studioWorkflow').evaluate(e=>e.scrollWidth<=e.clientWidth+2),true);
 }finally{await browser.close()}
});

test('Defect retest panel preserves historical occurrence and fails closed on stale evidence',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1365,height:900}}),csrf=await login(page);
  const created=await page.request.post(ORIGIN+'/api/projects',{headers:headers(csrf),data:{name:'Repair UI '+Date.now(),idea:'Explicit repair controls fixture',platform:'Web app'}});
  assert.equal(created.status(),201);const pid=(await created.json()).project_id;
  await page.addInitScript(({origin,id})=>{if(location.origin===origin)localStorage.setItem('orbit-project',id)},{origin:ORIGIN,id:pid});
  const j='fixture-repair-a',j2='fixture-repair-b',rd='a'.repeat(64),rd2='b'.repeat(64),fid='c'.repeat(64);
  let version=0,mismatch=false,submitted=null,hold=false,held=false,release;
  const pending=new Promise(resolve=>{release=resolve});
  const items=()=>[{finding_id:fid,registration_digest:rd,latest:false,severity:'HIGH',state:version?'ASSIGNED':'CLOSED',assignee:'ci-developer',history:[{digest:'d'.repeat(64),snapshot:{action:'CLOSE',actor:'ci-reviewer',note:'Old closure'}}]},
   {finding_id:fid,registration_digest:rd2,latest:true,severity:'HIGH',state:'OPEN',assignee:null,history:[]}];
  const digest=()=>String(version+1).repeat(64);
  const json=(route,body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
  await page.route('**/api/projects/'+pid+'/coding',route=>json(route,{jobs:[j,j2].map(id=>({id,status:'failed',spec:'Synthetic UI fixture '+id}))}));
  await page.route('**/api/coding/**',route=>{
   const parts=new URL(route.request().url()).pathname.split('/');const id=parts[3];
   return json(route,parts[4]==='verifications'?{verifications:[]}:parts[4]==='quality'?{job_id:id,status:'BLOCK'}:{id,status:'failed',spec:'Synthetic UI fixture'});
  });
  await page.route('**/api/projects/'+pid+'/engineering/defect-repairs/*',async route=>{
   const id=new URL(route.request().url()).pathname.split('/').at(-1);
   if(route.request().method()==='POST'){
    submitted=route.request().postDataJSON();version++;
    return json(route,{digest:'e'.repeat(64)},201);
   }
   const payload={project_id:pid,job_id:id,state:'READY',registry_state:'NO_CURRENT_FINDINGS',items:id===j?items():[],evidence_digest:digest()};
   if(hold&&id===j){held=true;await pending;}
   return json(route,payload);
  });
  await page.route('**/api/projects/'+pid+'/engineering/defect-retest-quality/*',route=>{
   const id=new URL(route.request().url()).pathname.split('/').at(-1);
   return json(route,{project_id:pid,job_id:id,state:'BLOCK',checks:{explicit_closure:'BLOCK'},items:id===j?items().map(x=>({registration_digest:x.registration_digest,status:x.state==='CLOSED'?'STALE_RETEST':'UNRESOLVED',closure_digest:null})):[],repair_digest:mismatch?'f'.repeat(64):digest(),evidence_digest:'9'.repeat(64),execution_digest:'8'.repeat(64)});
  });
  await page.goto(ORIGIN+'/');await page.locator('#studioLine[data-project-id="'+pid+'"][data-ready="true"]').waitFor({timeout:15000});
  await page.locator('[data-view="coding"]').click();
  await page.locator('#codingJobs [data-job="'+j+'"]').click();
  await page.locator('#defectRepairRefresh').click();
  await page.waitForFunction(()=>document.querySelector('#defectRepairItem').options.length===2);
  await page.locator('#defectRepairItem').selectOption(rd);
  assert.match(await page.locator('#defectRepairItem option').first().textContent(),/Lịch sử.*STALE_RETEST/);
  assert.deepEqual(await page.locator('#defectRepairAction option').allTextContents(),['REOPEN']);
  await page.locator('#defectRepairNote').fill('Explicit revalidation request');
  page.once('dialog',dialog=>dialog.accept());
  await page.locator('#defectRepairSubmit').click();
  await page.waitForFunction(()=>document.querySelector('#defectRepairStatus').textContent.includes('ASSIGNED'));
  assert.deepEqual(submitted,{action:'REOPEN',finding_id:fid,registration_digest:rd,expected_digest:'1'.repeat(64),assignee:null,note:'Explicit revalidation request',confirmation:'REOPEN DEFECT '+j+' '+fid});
  assert.match(await page.locator('#defectRetestStatus').textContent(),/BLOCK/);
  mismatch=true;await page.locator('#defectRepairRefresh').click();
  await page.waitForFunction(()=>document.querySelector('#defectRepairStatus').textContent.includes('Không thể xác minh'));
  assert.equal(await page.locator('#defectRepairSubmit').isDisabled(),true);
  mismatch=false;hold=true;await page.locator('#defectRepairRefresh').click();
  for(let i=0;i<100&&!held;i++)await new Promise(resolve=>setTimeout(resolve,50));
  assert.equal(held,true);
  await page.locator('#codingJobs [data-job="'+j2+'"]').click();
  await page.locator('#defectRepairRefresh').click();
  await page.waitForFunction(()=>document.querySelector('#defectRepairStatus').textContent.startsWith('READY'));
  const delayed=page.waitForResponse(response=>response.url().endsWith('/defect-repairs/'+j));
  release();await delayed;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.equal(await page.locator('#defectRepairItem option').count(),0);
  assert.equal(await page.locator('#defectRepairSubmit').isDisabled(),true);
 }finally{await browser.close()}
});

test('Security evidence panel is read-only and discards foreign and delayed job snapshots',async()=>{
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1365,height:900}}),csrf=await login(page);
  const created=await page.request.post(ORIGIN+'/api/projects',{headers:headers(csrf),data:{name:'Security Evidence UI '+Date.now(),idea:'Scope and stale snapshot fixture',platform:'Web app'}});
  assert.equal(created.status(),201);const pid=(await created.json()).project_id;
  await page.addInitScript(({origin,id})=>{if(location.origin===origin)localStorage.setItem('orbit-project',id)},{origin:ORIGIN,id:pid});
  const j='security-fixture-a',j2='security-fixture-b';
  const json=(route,body)=>route.fulfill({status:200,contentType:'application/json',body:JSON.stringify(body)});
  let hold=false,held=false,foreign=false,release,requests=[];
  const pending=new Promise(resolve=>{release=resolve});
  await page.route('**/api/projects/'+pid+'/coding',route=>json(route,{jobs:[j,j2].map(id=>({id,status:'failed',spec:'Security UI fixture '+id}))}));
  await page.route('**/api/coding/**',route=>{
   const parts=new URL(route.request().url()).pathname.split('/');const id=parts[3];
   return json(route,parts[4]==='verifications'?{verifications:[]}:parts[4]==='quality'?{job_id:id,status:'BLOCK'}:{id,status:'failed',spec:'Synthetic UI fixture'});
  });
  await page.route('**/api/projects/'+pid+'/engineering/security-evidence/*',async route=>{
   const id=new URL(route.request().url()).pathname.split('/').at(-1);requests.push(route.request().method());
   if(hold&&id===j){held=true;await pending;}
   return json(route,{schema:'orbit.security-evidence.v1',project_id:foreign?'foreign':pid,job_id:id,
    state:id===j?'SECURITY_EVIDENCE_READY':'BLOCK',security_gate:'BLOCK',
    checks:{exact_source:id===j?'PASS':'BLOCK'},assessments:{secret_scan:'NOT_ASSESSED',dependency_vulnerabilities:'NOT_ASSESSED'},
    source:id===j?{candidate_digest:'a'.repeat(64),execution_digest:'b'.repeat(64)}:null,evidence_digest:'c'.repeat(64)});
  });
  await page.goto(ORIGIN+'/');await page.locator('#studioLine[data-project-id="'+pid+'"][data-ready="true"]').waitFor({timeout:15000});
  await page.locator('[data-view="coding"]').click();
  await page.locator('#codingJobs [data-job="'+j+'"]').click();
  const panel=page.locator('#securityEvidenceStatus');
  await page.locator('#securityEvidenceRefresh').click();
  await page.waitForFunction(()=>document.querySelector('#securityEvidenceStatus').textContent.includes('SECURITY_EVIDENCE_READY'));
  assert.match(await panel.textContent(),/Security gate: BLOCK/);
  assert.match(await panel.textContent(),/secret_scan: NOT_ASSESSED/);
  foreign=true;await page.locator('#securityEvidenceRefresh').click();
  await page.waitForFunction(()=>document.querySelector('#securityEvidenceStatus').textContent.includes('Không thể xác minh'));
  assert.doesNotMatch(await panel.textContent(),/SECURITY_EVIDENCE_READY/);
  foreign=false;hold=true;await page.locator('#securityEvidenceRefresh').click();
  for(let i=0;i<100&&!held;i++)await new Promise(resolve=>setTimeout(resolve,50));
  assert.equal(held,true);
  await page.locator('#codingJobs [data-job="'+j2+'"]').click();
  await page.locator('#securityEvidenceRefresh').click();
  await page.waitForFunction(()=>document.querySelector('#securityEvidenceStatus').textContent.includes('exact_source: BLOCK'));
  const late=page.waitForResponse(response=>response.url().endsWith('/security-evidence/'+j));
  release();await late;
  await page.evaluate(()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve))));
  assert.doesNotMatch(await panel.textContent(),/SECURITY_EVIDENCE_READY/);
  assert.match(await panel.textContent(),/exact_source: BLOCK/);
  assert.deepEqual(requests,['GET','GET','GET','GET']);
 }finally{await browser.close()}
});
